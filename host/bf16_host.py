#!/usr/bin/env python3
"""Run training_tile_v4 on the DE1-SoC over USB JTAG and bit-check every result."""
from __future__ import annotations

import argparse
import dataclasses
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

DIM = 8
ELEMENTS = DIM * DIM
WORD_BITS = 64
REPLY_MAGIC = 0xB16A
REPLY_LAG = 2  # Word n carries the reply to word n-2; see docs/design.md.
TDI_SKEW_BITS = 7  # Measured on this board: TDI reaches the bridge 7 tck after its TDO framing.
MAX_WORDS_PER_SCAN = 4096
TILE_MHZ = 40
SERVER_TIMEOUT_S = 30
SERVER = Path(__file__).with_name("vjtag_server.tcl")

Matrix = list[int]  # 64 FP32 bit patterns, row-major.


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def value(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw))[0]


def bf16(raw: int) -> int:
    """Round FP32 to BF16 exactly as the chip-lab host does, returned as FP32 bits."""
    if raw & 0xFFFF == 0:
        return raw
    if raw & 0x7F800000 == 0x7F800000 and raw & 0x7FFFFF:
        return (raw & 0xFFFF0000) | 0x00400000
    return (raw + 0x7FFF + ((raw >> 16) & 1)) & 0xFFFF0000


def _exact(raw: int) -> Fraction:
    exponent = (raw >> 23) & 0xFF
    fraction = raw & 0x7FFFFF
    if exponent == 0xFF:
        raise ValueError("reference model covers finite values only")
    significand = fraction if exponent == 0 else fraction | 0x800000
    magnitude = Fraction(significand) * Fraction(2) ** (max(exponent, 1) - 150)
    return -magnitude if raw >> 31 else magnitude


def _round_fp32(number: Fraction) -> int:
    """Round an exact nonzero value to FP32, nearest-even, including subnormals."""
    magnitude = abs(number)
    log2 = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if Fraction(2) ** log2 > magnitude:
        log2 -= 1
    unit = Fraction(2) ** (max(log2, -126) - 23)
    scaled = magnitude / unit
    whole = scaled.numerator // scaled.denominator
    remainder = scaled - whole
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and whole & 1):
        whole += 1
    rounded = whole * unit
    sign = 0x80000000 if number < 0 else 0
    if rounded >= Fraction(2) ** 128:
        return sign | 0x7F800000
    return sign | bits(float(rounded))


def fma(a: int, b: int, c: int) -> int:
    """FP32 a*b+c with one nearest-even rounding, as hardware and std::fma do."""
    product = _exact(a) * _exact(b)
    result = product + _exact(c)
    if result != 0:
        return _round_fp32(result)
    product_negative = bool((a ^ b) >> 31)
    both_negative = product == 0 and product_negative and bool(c >> 31)
    return 0x80000000 if both_negative else 0


def reference(a: Matrix, b: Matrix, c: Matrix | None = None, transpose_a: bool = False,
              transpose_b: bool = False, accumulate: bool = False) -> Matrix:
    """Software model of one tile job; A and B must already be BF16 values."""
    out = list(c) if accumulate and c else [0] * ELEMENTS
    for inner in range(DIM):
        for row in range(DIM):
            left = a[inner * DIM + row] if transpose_a else a[row * DIM + inner]
            for column in range(DIM):
                right = b[column * DIM + inner] if transpose_b else b[inner * DIM + column]
                out[row * DIM + column] = fma(left, right, out[row * DIM + column])
    return out


def loss(prediction: Matrix, target: Matrix) -> float:
    return sum(0.5 * (value(p) - value(t)) ** 2 for p, t in zip(prediction, target))


def write_word(enable: int, bank: int, address: int, data: int) -> int:
    return 1 << 60 | enable << 53 | bank << 52 | address << 40 | data


def read_word(bank: int, address: int) -> int:
    return 2 << 60 | bank << 52 | address << 40


def start_word(job_bank: int, accumulate: bool, transpose_b: bool, transpose_a: bool) -> int:
    return 3 << 60 | job_bank << 3 | int(accumulate) << 2 | int(transpose_b) << 1 | int(transpose_a)


def display_word(digits: int, leds: int) -> int:
    return 5 << 60 | (leds & 0x3FF) << 24 | (digits & 0xFFFFFF)


NOP = 0
STATUS = 4 << 60


def pack_scan(words: list[int]) -> int:
    """First word in the low bits, advanced so the bridge sees each word aligned."""
    packed = 0
    for index, word in enumerate(words):
        packed |= word << (index * WORD_BITS)
    return packed >> TDI_SKEW_BITS


def job_words(a: Matrix, b: Matrix, c: Matrix | None, transpose_a: bool, transpose_b: bool,
              accumulate: bool, bank: int) -> list[int]:
    """Words that load, run and read back one job; replies 'status' then 64 C values."""
    words = []
    for enable, matrix in ((0b001, a), (0b010, b)):
        for index in range(0, ELEMENTS, 2):
            pair = (bf16(matrix[index]) >> 16) | (bf16(matrix[index + 1]) & 0xFFFF0000)
            words.append(write_word(enable, bank, index, pair))
    if accumulate and c:
        words += [write_word(0b100, bank, index, c[index]) for index in range(ELEMENTS)]
    words += [start_word(bank, accumulate, transpose_b, transpose_a), NOP, NOP, STATUS]
    words += [read_word(bank, index) for index in range(ELEMENTS)]
    return words


@dataclasses.dataclass(frozen=True)
class Status:
    busy: bool
    finished: bool
    write_error: bool
    flags: int
    jobs: int
    cycles: int

    @classmethod
    def decode(cls, data: int) -> "Status":
        return cls(bool(data & 1), bool(data & 2), bool(data & 4), (data >> 3) & 0x1F,
                   (data >> 8) & 0xFF, data >> 16)


class Link:
    """One quartus_stp session holding the virtual JTAG node."""

    def __init__(self) -> None:
        tool = shutil.which("quartus_stp") or str(
            Path.home() / "altera_lite/25.1std/quartus/bin/quartus_stp"
        )
        self.sequence: int | None = None
        self.log = tempfile.TemporaryFile(mode="w+")
        with socket.create_server(("127.0.0.1", 0)) as listener:
            listener.settimeout(SERVER_TIMEOUT_S)
            port = listener.getsockname()[1]
            self.process = subprocess.Popen(
                [tool, "-t", str(SERVER)], stdin=subprocess.DEVNULL, stdout=self.log,
                stderr=subprocess.STDOUT, env={**os.environ, "BF16_HOST_PORT": str(port)},
            )
            try:
                self.connection, _ = listener.accept()
            except TimeoutError:
                self.process.kill()
                raise RuntimeError("quartus_stp never connected:\n" + self._log_tail()) from None
        self.stream = self.connection.makefile("rw", newline="\n")
        if self._read_line() != "READY":
            raise RuntimeError("quartus_stp did not report READY")

    def _log_tail(self) -> str:
        self.log.seek(0)
        return "".join(self.log.readlines()[-12:])

    def _read_line(self) -> str:
        line = self.stream.readline()
        if not line:
            self.process.wait(timeout=20)
            raise RuntimeError("quartus_stp exited:\n" + self._log_tail())
        return line.strip()

    def close(self) -> None:
        self.stream.close()
        self.connection.close()
        self.process.wait(timeout=20)

    def _scan(self, words: list[int]) -> list[int]:
        packed = pack_scan(words)
        hex_digits = len(words) * WORD_BITS // 4
        self.stream.write(f"{len(words) * WORD_BITS} {packed:0{hex_digits}x}\n")
        self.stream.flush()
        reply = int(self._read_line(), 16)
        mask = (1 << WORD_BITS) - 1
        return [(reply >> (index * WORD_BITS)) & mask for index in range(len(words))]

    def transact(self, words: list[int]) -> list[int]:
        """Send words in one scan; return each word's 32-bit reply, checking every tag."""
        # The skew costs the low bits of the first word and the high bits of the last.
        replies = self._scan([NOP, *words, *([NOP] * REPLY_LAG)])
        if replies[0] >> 48 != REPLY_MAGIC:
            raise RuntimeError(f"no tile on the link: reply {replies[0]:016x}")
        if self.sequence is None:
            self.sequence = (replies[0] >> 32) & 0xFFFF
        self.sequence = (self.sequence + 1) & 0xFFFF  # The leading NOP.
        results = []
        for offset, reply in enumerate(replies[1 + REPLY_LAG:]):
            expected = (self.sequence + 1 + offset) & 0xFFFF
            if reply >> 32 != (REPLY_MAGIC << 16 | expected):
                raise RuntimeError(f"word {offset}: reply {reply:016x}, sequence {expected}")
            results.append(reply & 0xFFFFFFFF)
        # Executed words: the payload, then the two trailing NOPs.
        self.sequence = (self.sequence + len(words) + REPLY_LAG) & 0xFFFF
        return results


class Tile:
    """Runs jobs, alternating buffers, and compares each output with the reference."""

    def __init__(self, link: Link) -> None:
        self.link = link
        self.bank = 0
        self.jobs = 0
        self.flops = 0
        self.max_cycles = 0

    def run(self, a: Matrix, b: Matrix, c: Matrix | None = None, transpose_a: bool = False,
            transpose_b: bool = False, accumulate: bool = False) -> Matrix:
        words = job_words(a, b, c, transpose_a, transpose_b, accumulate, self.bank)
        replies = self.link.transact(words)
        status = Status.decode(replies[-ELEMENTS - 1])
        output = replies[-ELEMENTS:]
        if status.busy or not status.finished or status.write_error:
            raise RuntimeError(f"bad job status: {status}")
        expected = reference([bf16(x) for x in a], [bf16(x) for x in b], c, transpose_a,
                             transpose_b, accumulate)
        mismatches = [i for i in range(ELEMENTS) if output[i] != expected[i]]
        if mismatches:
            first = mismatches[0]
            raise RuntimeError(f"{len(mismatches)} wrong elements; C[{first}]="
                               f"{output[first]:08x}, expected {expected[first]:08x}")
        self.bank ^= 1
        self.jobs += 1
        self.flops += 2 * DIM ** 3
        self.max_cycles = max(self.max_cycles, status.cycles)
        return output

    def show(self, digits: int, leds: int) -> None:
        self.link.transact([display_word(digits, leds)])


def random_operand(rng: random.Random) -> int:
    """A finite value spanning subnormals to large exponents, with random sign."""
    return rng.getrandbits(32) & 0x8F7FFFFF | rng.randrange(96, 160) << 23 if rng.random() < .9 \
        else rng.getrandbits(1) << 31 | rng.getrandbits(23)


def command_selftest(tile: Tile, args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    for job in range(args.jobs):
        a = [random_operand(rng) for _ in range(ELEMENTS)]
        b = [random_operand(rng) for _ in range(ELEMENTS)]
        accumulate = job % 2 == 1
        c = [random_operand(rng) for _ in range(ELEMENTS)] if accumulate else None
        tile.run(a, b, c, bool(job & 2), bool(job & 4), accumulate)
    print(f"selftest: {tile.jobs} jobs, {tile.jobs * ELEMENTS} FP32 results, "
          f"{tile.flops // 2} FMAs bit-identical to the reference; "
          f"job length {tile.max_cycles} clocks")


def command_train(tile: Tile, args: argparse.Namespace) -> None:
    """The chip lab's bf16_training_test: one dense layer, SGD, FP32 master weights."""
    x = [0.0] * ELEMENTS
    for i in range(DIM):
        x[i * DIM + i] = 1.0
        x[i * DIM + (i + 1) % DIM] = -0.25 if i % 2 else 0.25
    x = [bits(v) for v in x]
    target_weights = [bits((i - (ELEMENTS // 2 - 1)) / (2 * DIM)) for i in range(ELEMENTS)]
    step = [0] * ELEMENTS
    for i in range(DIM):
        step[i * (DIM + 1)] = bits(-0.125)
    target = reference(x, [bf16(w) for w in target_weights])
    weights = [0] * ELEMENTS
    started = time.monotonic()
    for epoch in range(args.epochs + 1):
        y = tile.run(x, weights)
        current = loss(y, target)
        print(f"epoch {epoch:3d}  loss {current:12.6f}", flush=True)
        digits = int(f"{min(round(current * 10000), 999999):06d}", 16)
        tile.show(digits, (1 << (10 * (epoch + 1) // (args.epochs + 1))) - 1)
        if epoch == args.epochs:
            break
        dy = [bits(value(p) - value(t)) for p, t in zip(y, target)]
        dw = tile.run(x, dy, transpose_a=True)
        tile.run(dy, weights, transpose_b=True)
        weights = tile.run(step, dw, weights, accumulate=True)
        time.sleep(args.delay)
    print(f"train: {tile.jobs} jobs bit-identical to the reference in "
          f"{time.monotonic() - started:.1f} s; final loss {current:.6f}")


def command_bench(tile: Tile, args: argparse.Namespace) -> None:
    """Whole-system throughput: every job's operands and results cross the JTAG link."""
    rng = random.Random(args.seed)
    a = [bits(rng.uniform(-1, 1)) for _ in range(ELEMENTS)]
    b = [bits(rng.uniform(-1, 1)) for _ in range(ELEMENTS)]
    expected = reference([bf16(x) for x in a], [bf16(x) for x in b])
    words: list[int] = []
    per_job = len(job_words(a, b, None, False, False, False, 0))
    jobs_per_scan = max(1, MAX_WORDS_PER_SCAN // per_job)
    for job in range(jobs_per_scan):
        words += job_words(a, b, None, False, False, False, job & 1)
    started = time.monotonic()
    total = 0
    for _ in range(args.scans):
        replies = tile.link.transact(words)
        for job in range(jobs_per_scan):
            end = (job + 1) * per_job
            if replies[end - ELEMENTS:end] != expected:
                raise RuntimeError(f"benchmark job {job} result is wrong")
        total += jobs_per_scan
    elapsed = time.monotonic() - started
    status = Status.decode(tile.link.transact([STATUS])[0])
    flops = total * 2 * DIM ** 3
    print(f"bench: {total} jobs in {elapsed:.3f} s through JTAG = {flops / elapsed / 1e6:.2f} "
          f"MFLOPS end to end; one job = {status.cycles} clocks = "
          f"{2 * DIM ** 3 / status.cycles * TILE_MHZ:.1f} MFLOPS on the chip at {TILE_MHZ} MHz")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selftest = commands.add_parser("selftest", help="random jobs, bit-compared")
    selftest.add_argument("--jobs", type=int, default=200)
    selftest.add_argument("--seed", type=int, default=1)
    train = commands.add_parser("train", help="train a dense layer on the tile")
    train.add_argument("--epochs", type=int, default=48)
    train.add_argument("--delay", type=float, default=0.25, help="seconds between epochs")
    bench = commands.add_parser("bench", help="measure throughput")
    bench.add_argument("--scans", type=int, default=20)
    bench.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    handlers = {"selftest": command_selftest, "train": command_train, "bench": command_bench}
    link = Link()
    try:
        handlers[args.command](Tile(link), args)
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
