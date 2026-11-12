# BF16 FPGA

An eight-lane BF16 matrix tile with FP32 accumulation, taken unmodified from an ASIC design flow and running on a Terasic DE1-SoC (Cyclone V), driven and bit-checked from a PC over the board's USB-Blaster cable.

| Metric (DE1-SoC, 5CSEMA5F31C6) | Result |
|---|---|
| Fit | 14,425 / 32,070 ALMs (45%), 8 DSPs, 1 PLL |
| Tile clock | 40 MHz; Fmax 44.8 MHz, setup slack +2.67 ns |
| Peak rate | 611 MFLOPS on the chip, one job at a time |
| Training | 193 jobs, loss 57.355 → 0.000780 |
| Random jobs | 500 jobs, 256,000 FMAs bit-identical |

## Why it matters

The same `training_tile_v4` RTL that is routed to a SKY130HD layout in the chip lab runs here on real silicon. Every result returned over JTAG is compared bit for bit with an exact FP32 reference, so the board run checks the ASIC design's arithmetic, not just its simulation.

## Quick start

Requires Python 3, Icarus Verilog, Verilator and Yosys; board steps also need Quartus Prime Lite with Cyclone V support and a DE1-SoC on USB.

```sh
make check      # host tests, RTL simulation, Verilator lint, Yosys synthesis
make build      # Quartus compile; fails on missed timing or misplaced pins
make program    # load the volatile FPGA image (lost at power-off)
make selftest   # random jobs, bit-compared with the reference
make train      # train a dense layer; loss shown on HEX and LEDs
make bench      # throughput
```

## Repository layout

| Path | Contents |
|---|---|
| `rtl/` | Board top, PLL wrapper, JTAG link and word bridge, tile host |
| `rtl/vendor/` | Unmodified tile and Berkeley HardFloat ([provenance](rtl/vendor/README.md)) |
| `host/` | PC driver, exact FP32 reference model, Quartus JTAG server |
| `tb/`, `tests/` | RTL testbench, host unit tests |
| `quartus/` | Project, pin assignments, timing constraints |
| `scripts/gate.py` | Build gates: synthesized ALUTs, timing slack, pin placement |
| `docs/` | Design and results |

## Results and verification

- [docs/results.md](docs/results.md): measured fit, timing, throughput, training and random-job results, and what the tests do not cover.
- [docs/design.md](docs/design.md): clocking, the 64-bit JTAG word protocol and the measured TDI skew.
- The training run matches chip-lab simulation (57.3555 → 0.000779807).

## Limitations

- End-to-end rate is about 0.4 MFLOPS: JTAG and Python are the bottleneck, not the tile.
- The host runs one job at a time, so the tile's two-buffer overlap is unused.
- The host reference covers finite values; infinities and NaNs are covered only in chip-lab simulation.
- Simulation does not model the JTAG hub's TDI skew; it was measured on the board.

## Related projects

- [openroad-chip-lab](https://github.com/NicholasUnruh/openroad-chip-lab): source of the tile; numerics study, RTL and SKY130HD layout.
- [cuda-gemm](https://github.com/NicholasUnruh/cuda-gemm): the same GEMM workload on a GPU, from a naive kernel to tensor cores.
- Portfolio: https://genwealth.world

## License

MIT. See [LICENSE](LICENSE). Vendored HardFloat keeps its BSD license.
