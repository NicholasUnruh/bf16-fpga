#!/usr/bin/env python3
"""Render the figures in docs/img/ from real tool outputs.

  resources, timing: build/quartus/output_files/bf16.{fit,sta,paths}.rpt
                     (`make build`, then scripts/worst_paths.tcl for bf16.paths.rpt)
  jtag-word, jtag-protocol: a VCD of tb/top_tb.sv, simulated here with Icarus Verilog
  jtag-fields: the command decoder in rtl/tile_host.sv
  training-loss: host/bf16_host.py's training run on its exact FP32 reference model

Run from the repository root:
  uv run --with matplotlib --with pillow python scripts/figures.py [--assets DIR]
--reports points at another checkout's output_files.
--assets also writes .webp copies and resources.json / timing.json / wavejson.json there.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import bf16_host as host  # noqa: E402

REPORTS = ROOT / "build/quartus/output_files"
IMG = ROOT / "docs/img"
BG, INK, MUTED, GRID = "#0a0b12", "#f2f2f0", "#9a9ca6", "#2a2c36"
ACCENT, BLUE, AQUA, VIOLET, YELLOW = (
    "#f07a45",
    "#3987e5",
    "#199e70",
    "#9085e9",
    "#c98500",
)
TILE_CLOCK = "clocks|pll|general[0].gpll~PLL_OUTPUT_COUNTER|divclk"
TCK_CLOCK = "altera_reserved_tck"

plt.rcParams.update(
    {
        "svg.fonttype": "none",
        "font.family": "sans-serif",
        "font.sans-serif": ["Inter", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 11,
        "text.color": INK,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.edgecolor": GRID,
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
    }
)


def save(fig, name: str, assets: Path | None) -> None:
    fig.savefig(IMG / f"{name}.svg")
    if assets:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=100)
        Image.open(buffer).convert("RGB").save(
            assets / f"{name}.webp", "WEBP", quality=82
        )
    plt.close(fig)


def table_rows(report: str, title: str) -> list[list[str]]:
    """Rows of the first ';'-delimited panel whose title line starts with `title`."""
    lines = report.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"; {title}"))
    rows, borders = [], 0
    for line in lines[start + 1 :]:
        if line.startswith("+"):
            borders += 1
            if borders == 3:
                break
            continue
        if borders == 2 and line.startswith(";"):
            rows.append([cell.strip() for cell in line.split(";")[1:-1]])
    return rows


# ---------------------------------------------------------------- resources


def total(cell: str) -> float:
    return float(cell.split("(")[0])


def resources(assets: Path | None) -> None:
    fit = (REPORTS / "bf16.fit.rpt").read_text(encoding="latin-1")
    summary = (REPORTS / "bf16.fit.summary").read_text(encoding="latin-1")
    rows = table_rows(fit, "Fitter Resource Utilization by Entity")
    nodes = {
        row[14]: {
            "alms": total(row[1]),
            "regs": total(row[7]),
            "dsps": total(row[11]),
            "m10ks": total(row[10]),
            "self_alms": float(row[1].split("(")[1].rstrip(")")),
            "self_regs": float(row[7].split("(")[1].rstrip(")")),
        }
        for row in rows
    }
    engine = "|top|tile_host:host|training_tile_v4:tile|training_tile_engine:engine"
    lanes = [f"{engine}|fp32_accum_fma_pipe:lanes[{i}].fma" for i in range(8)]
    jtag = [
        "|top|jtag_link:link",
        "|top|jtag_word_bridge:bridge",
        "|top|sld_hub:auto_hub",
    ]
    display = [f"|top|seven_segment:h{i}" for i in range(6)]
    groups = [
        ("8 FMA lanes", ACCENT, lanes, False),
        ("Operand banks + issue (engine)", BLUE, [engine], True),
        ("tile_host (decoder, replies)", AQUA, ["|top|tile_host:host"], True),
        ("JTAG: hub + word bridge", VIOLET, jtag, False),
        (
            "Board display, top, PLL",
            YELLOW,
            [*display, "|top", "|top|tile_clock:clocks"],
            None,
        ),
    ]

    def amount(names: list[str], own: bool | None, key: str) -> float:
        if own is None:  # top contributes only its own cells
            return (
                sum(nodes[n][key] for n in names[:-2])
                + nodes["|top"][f"self_{key}"]
                + nodes[names[-1]][key]
            )
        return sum(nodes[n][f"self_{key}" if own else key] for n in names)

    device = {
        key: re.search(pattern, summary).group(1).replace(",", "")
        for key, pattern in {
            "alm_capacity": r"ALMs\) : [\d,.]+ / ([\d,]+)",
            "dsp_capacity": r"DSP Blocks : \d+ / (\d+)",
            "m10k_capacity": r"RAM Blocks : \d+ / (\d+)",
            "plls": r"PLLs : (\d+) /",
        }.items()
    }
    data = {
        "source": "build/quartus/output_files/bf16.fit.rpt (Fitter Resource Utilization by Entity)",
        "device": "5CSEMA5F31C6",
        "totals": {
            "alms_needed": nodes["|top"]["alms"],
            "registers": nodes["|top"]["regs"],
            "dsps": nodes["|top"]["dsps"],
            "m10ks": nodes["|top"]["m10ks"],
            **{k: int(v) for k, v in device.items()},
        },
        "groups": [],
        "modules": {
            name.rsplit("|", 1)[-1] or "top": nodes[name]
            for name in [
                "|top",
                *jtag,
                "|top|tile_clock:clocks|altera_pll:pll",
                "|top|tile_host:host",
                "|top|tile_host:host|training_tile_v4:tile",
                engine,
                *lanes,
            ]
        },
    }
    for label, color, names, own in groups:
        data["groups"].append(
            {
                "label": label,
                "color": color,
                "alms": round(amount(names, own, "alms"), 1),
                "registers": round(amount(names, own, "regs")),
            }
        )
    for key, field in (("alms", "alms_needed"), ("registers", "registers")):
        assert abs(sum(g[key] for g in data["groups"]) - data["totals"][field]) < 1, key

    lane0 = lanes[0]
    children = [
        (name.rsplit("|", 1)[-1].split(":")[1], nodes[name]["alms"])
        for name in nodes
        if name.startswith(lane0 + "|") and name.count("|") == lane0.count("|") + 1
    ]
    stage_names = {
        "post": "postMul (add, normalize)",
        "round_result": "round",
        "pre": "preMul (align C)",
        "convert_c": "FP32 C to recoded",
        "convert_result": "recoded to FP32",
        "convert_a": "A to recoded",
        "convert_b": "B to recoded",
    }
    stages = sorted(
        ((stage_names.get(n, n), a) for n, a in children if n in stage_names),
        key=lambda item: -item[1],
    )
    other = nodes[lane0]["alms"] - sum(a for _, a in stages)
    stages.append(("pipeline regs, small parts", round(other, 1)))
    data["lane0_alms"] = {"total": nodes[lane0]["alms"], "stages": dict(stages)}

    fig, axes = plt.subplots(
        3, 1, figsize=(16, 6.4), gridspec_kw={"height_ratios": [1, 1, 1]}
    )
    bars = [
        (
            "ALMs needed",
            "alms",
            data["totals"]["alms_needed"],
            data["totals"]["alm_capacity"],
        ),
        ("Registers", "registers", data["totals"]["registers"], None),
    ]
    for ax, (title, key, whole, capacity) in zip(axes[:2], bars):
        left = 0.0
        for group in data["groups"]:
            width = group[key]
            ax.barh(
                0,
                width,
                left=left,
                color=group["color"],
                height=0.6,
                edgecolor=BG,
                linewidth=2,
            )
            if width / whole > 0.15:
                ax.text(
                    left + width / 2,
                    0,
                    f"{group['label']}\n{width:,.0f}",
                    ha="center",
                    va="center",
                    fontsize=10,
                    color=BG if group["color"] in (ACCENT, YELLOW) else INK,
                )
            left += width
        tiny = [g for g in data["groups"] if g[key] / whole <= 0.15]
        ax.text(
            whole * 1.01,
            0,
            "\n".join(f"{g['label']}: {g[key]:,.0f}" for g in tiny),
            va="center",
            fontsize=9,
            color=MUTED,
        )
        extra = f" of {capacity:,} ({100 * whole / capacity:.0f}%)" if capacity else ""
        ax.set_title(
            f"{title}: {whole:,.1f}{extra}"
            if key == "alms"
            else f"{title}: {whole:,.0f}",
            loc="left",
            fontsize=12,
            color=INK,
        )
        ax.set_xlim(0, whole * 1.6)
    left = 0.0
    for index, (label, alms) in enumerate(stages):
        color = (
            ACCENT
            if index == 0
            else [
                "#c7643a",
                "#a8532f",
                "#8a4426",
                "#6e371f",
                "#552b19",
                "#3f2013",
                "#5a5c66",
            ][min(index - 1, 6)]
        )
        axes[2].barh(
            0, alms, left=left, color=color, height=0.6, edgecolor=BG, linewidth=2
        )
        if alms >= 60:
            axes[2].text(
                left + alms / 2,
                0.42 if index % 2 else -0.42,
                f"{label}\n{alms:,.1f}",
                ha="center",
                va="bottom" if index % 2 else "top",
                fontsize=9,
                color=INK,
            )
        left += alms
    axes[2].text(
        left * 1.01,
        0,
        "\n".join(f"{label}: {alms:,.1f}" for label, alms in stages if alms < 60),
        va="center",
        fontsize=9,
        color=MUTED,
    )
    axes[2].set_xlim(0, nodes[lane0]["alms"] * 1.6)
    axes[2].set_ylim(-1.1, 1.1)
    axes[2].set_title(
        f"One FMA lane (lane 0): {nodes[lane0]['alms']:,.1f} ALMs, 1 DSP, by HardFloat stage",
        loc="left",
        fontsize=12,
        color=INK,
    )
    t = data["totals"]
    fig.text(
        0.69,
        0.03,
        f"DSP blocks: {t['dsps']:.0f} / {t['dsp_capacity']} (one 8x8 multiply per lane)\n"
        f"M10K blocks: {t['m10ks']:.0f} / {t['m10k_capacity']} (operand banks are flip-flops)\n"
        f"PLLs: {t['plls']} (50 MHz to 40 MHz tile clock)",
        fontsize=11,
        color=MUTED,
        va="bottom",
    )
    for ax in axes:
        ax.set_yticks([])
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.tight_layout()
    save(fig, "fpga-resources", assets)
    if assets:
        (assets / "resources.json").write_text(json.dumps(data, separators=(",", ":")))


# ---------------------------------------------------------------- timing


def timing(assets: Path | None) -> None:
    sta = (REPORTS / "bf16.sta.rpt").read_text(encoding="latin-1")
    paths = (REPORTS / "bf16.paths.rpt").read_text(encoding="latin-1")
    periods = {row[0]: float(row[2]) for row in table_rows(sta, "Clocks")}
    fmax = {
        row[2]: float(row[0].split()[0])
        for row in table_rows(sta, "Slow 1100mV 85C Model Fmax Summary")
    }
    slack = {
        row[0]: float(row[1])
        for row in table_rows(sta, "Slow 1100mV 85C Model Setup Summary")
    }
    worst = {}
    for clock in (TILE_CLOCK, TCK_CLOCK):
        row = table_rows(paths, f"Worst setup paths: {clock}")[0]
        worst[clock] = {"slack_ns": float(row[0]), "from": row[1], "to": row[2]}
    stats = {row[0]: row for row in table_rows(paths, "Statistics")}
    arrival = table_rows(paths, "Data Arrival Path")
    data_start = next(i for i, r in enumerate(arrival) if r[6] == "data path")
    launch = float(arrival[data_start][0]) - float(arrival[data_start][1])
    summary = {row[0]: row[1] for row in table_rows(paths, "Path Summary")}
    required = float(summary["Data Required Time"])

    def stage(element: str) -> str:
        for key, label in (
            ("convert_b", "B: BF16 to recoded (leading-zero count)"),
            ("|pre|", "preMul: align addend"),
            ("c_s1", "preMul: align addend"),
            ("state_s1", "preMul: align addend"),
        ):
            if key in element:
                return label
        return "B bank read mux (issue_index, fanout 288)"

    segments: list[list] = [["clock tree to launch register", 0.0, launch]]
    for row in arrival[data_start + 1 :]:
        if not row[0].strip():
            continue
        label = stage(row[6])
        if segments[-1][0] != label:
            segments.append([label, segments[-1][2], segments[-1][2]])
        segments[-1][2] = float(row[0])
    critical = {
        "from": worst[TILE_CLOCK]["from"],
        "to": worst[TILE_CLOCK]["to"],
        "logic_levels": int(stats["Number of Logic Levels"][2]),
        "data_delay_ns": float(stats["Data Delay"][1]),
        "clock_skew_ns": float(stats["Clock Skew"][1]),
        "arrival_ns": float(summary["Data Arrival Time"]),
        "required_ns": required,
        "segments": [
            {"stage": s, "start_ns": round(a, 3), "end_ns": round(b, 3)}
            for s, a, b in segments
        ],
    }
    data = {
        "source": "build/quartus/output_files/bf16.sta.rpt (Slow 1100mV 85C) and bf16.paths.rpt",
        "domains": [
            {
                "name": "tile clock (PLL)",
                "clock": TILE_CLOCK,
                "period_ns": periods[TILE_CLOCK],
                "constrained_mhz": round(1000 / periods[TILE_CLOCK], 3),
                "fmax_mhz": fmax[TILE_CLOCK],
                "setup_slack_ns": slack[TILE_CLOCK],
                "worst_path": worst[TILE_CLOCK],
            },
            {
                "name": "JTAG TCK",
                "clock": TCK_CLOCK,
                "period_ns": periods[TCK_CLOCK],
                "constrained_mhz": round(1000 / periods[TCK_CLOCK], 3),
                "fmax_mhz": fmax[TCK_CLOCK],
                "setup_slack_ns": slack[TCK_CLOCK],
                "worst_path": worst[TCK_CLOCK],
                "host_tck_mhz": 24,
                "note": "Quartus analyzed TCK at its 30 MHz default; the host runs 24 MHz",
            },
        ],
        "critical_path": critical,
    }

    fig, axes = plt.subplots(
        2, 1, figsize=(16, 5.6), gridspec_kw={"height_ratios": [1.5, 1]}
    )
    ax = axes[0]
    shades = [GRID, BLUE, "#2a6bb8", ACCENT]
    for index, (label, start, end) in enumerate(segments):
        ax.barh(
            0,
            end - start,
            left=start,
            color=shades[index % len(shades)],
            height=0.5,
            edgecolor=BG,
            linewidth=2,
        )
        ax.text(
            (start + end) / 2,
            0.36 if index % 2 else -0.36,
            f"{label}\n{end - start:.2f} ns",
            ha="center",
            va="bottom" if index % 2 else "top",
            fontsize=9.5,
            color=INK,
        )
    end = critical["arrival_ns"]
    ax.barh(
        0,
        required - end,
        left=end,
        color="none",
        hatch="///",
        edgecolor=ACCENT,
        height=0.5,
    )
    ax.text(
        (end + required) / 2,
        0.36,
        f"slack\n+{slack[TILE_CLOCK]:.3f} ns",
        ha="center",
        va="bottom",
        fontsize=10,
        color=ACCENT,
    )
    ax.axvline(required, color=INK, linewidth=1)
    ax.axvline(periods[TILE_CLOCK], color=MUTED, linewidth=1, linestyle=":")
    ax.text(
        periods[TILE_CLOCK],
        -0.75,
        f"{periods[TILE_CLOCK]:g} ns period",
        ha="center",
        fontsize=9,
        color=MUTED,
    )
    ax.text(required, 0.95, "required", ha="center", fontsize=9, color=INK)
    ax.set_xlim(0, 29)
    ax.set_ylim(-1.0, 1.1)
    ax.set_yticks([])
    ax.set_xlabel("ns from launch clock edge (slow 85 C corner)")
    ax.set_title(
        f"Tile clock 40 MHz: critical path, {critical['logic_levels']} logic levels, "
        f"issue_index[3] to lanes[3].fma state_s1[1]; Fmax {fmax[TILE_CLOCK]} MHz",
        loc="left",
        fontsize=12,
        color=INK,
    )
    ax = axes[1]
    for row, domain in enumerate(data["domains"]):
        used = domain["period_ns"] - domain["setup_slack_ns"]
        ax.barh(row, used, color=BLUE, height=0.5, edgecolor=BG, linewidth=2)
        ax.barh(
            row,
            domain["setup_slack_ns"],
            left=used,
            color="none",
            hatch="///",
            edgecolor=ACCENT,
            height=0.5,
        )
        ax.text(
            domain["period_ns"] + 0.4,
            row,
            f"{domain['name']}: period {domain['period_ns']:g} ns ({domain['constrained_mhz']:g} MHz), "
            f"slack +{domain['setup_slack_ns']:.3f} ns, Fmax {domain['fmax_mhz']:g} MHz",
            va="center",
            fontsize=10,
            color=INK,
        )
    ax.text(
        0,
        1.55,
        "Setup slack per clock domain (hatched); TCK analyzed at Quartus's 30 MHz default, "
        "the host clocks it at 24 MHz; the domains cross only through a toggle synchronizer",
        fontsize=9.5,
        color=MUTED,
    )
    ax.set_yticks([])
    ax.set_xlim(0, 80)
    ax.set_ylim(-0.6, 1.9)
    ax.set_xlabel("ns")
    for a in axes:
        for side in ("top", "right", "left"):
            a.spines[side].set_visible(False)
    fig.tight_layout()
    save(fig, "fpga-timing", assets)
    if assets:
        (assets / "timing.json").write_text(json.dumps(data, separators=(",", ":")))


# ---------------------------------------------------------------- JTAG waveforms

DUMPED = [
    "top_tb.tck",
    "top_tb.tdi",
    "top_tb.tdo",
    "top_tb.shift_dr",
    "top_tb.clk",
    "top_tb.bridge.bit_index",
    "top_tb.bridge.word_toggle",
    "top_tb.bridge.word_out",
    "top_tb.dut.execute",
    "top_tb.dut.sequence_count",
    "top_tb.dut.reply_data",
]


def simulate() -> dict[str, list[tuple[int, int]]]:
    """Run tb/top_tb.sv with a VCD dump; return {signal: [(time_ps, value)]}."""
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    (build / "wave_dump.sv").write_text(
        'module wave_dump;\n  initial begin\n    $dumpfile("build/wave.vcd");\n'
        f"    $dumpvars(0, {', '.join(DUMPED)});\n  end\nendmodule\n"
    )
    sources = sorted(
        str(p.relative_to(ROOT))
        for p in [
            *ROOT.glob("rtl/*.sv"),
            *ROOT.glob("rtl/vendor/*.v"),
            *ROOT.glob("rtl/vendor/hardfloat/*.v"),
        ]
    )
    subprocess.run(
        [
            "iverilog",
            "-g2012",
            "-s",
            "top_tb",
            "-s",
            "wave_dump",
            "-Irtl/vendor/hardfloat",
            "-o",
            "build/wave.vvp",
            *sources,
            "tb/top_tb.sv",
            "build/wave_dump.sv",
        ],
        cwd=ROOT,
        check=True,
        timeout=300,
    )
    log = subprocess.run(
        ["vvp", "build/wave.vvp"],
        cwd=ROOT,
        check=True,
        timeout=300,
        capture_output=True,
        text=True,
    ).stdout
    assert "PASS: bf16-fpga" in log, log
    names, changes, now, scope, defined = {}, {}, 0, [], False
    for line in (build / "wave.vcd").read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "$scope":
            scope.append(parts[2])
        elif parts[0] == "$upscope":
            scope.pop()
        elif parts[0] == "$var":
            names.setdefault(parts[3], ".".join([*scope, parts[4]]))
        elif parts[0] == "$enddefinitions":
            defined = True
        elif not defined:
            continue
        elif parts[0].startswith("#"):
            now = int(parts[0][1:])
        elif parts[0][0] in "01xz" and len(parts) == 1:
            changes.setdefault(names[parts[0][1:]], []).append(
                (now, int(parts[0][0]) if parts[0][0] in "01" else 0)
            )
        elif parts[0][0] == "b":
            bitsv = parts[0][1:].replace("x", "0").replace("z", "0")
            changes.setdefault(names[parts[1]], []).append((now, int(bitsv, 2)))
    return changes


def at(trace: list[tuple[int, int]], time: int) -> int:
    value = 0
    for when, new in trace:
        if when > time:
            break
        value = new
    return value


def words(changes) -> list[dict]:
    """Frame every word by bit_index at each rising TCK while shifting."""
    rises = [t for t, v in changes["top_tb.tck"] if v == 1]
    frames, tdi, tdo, start = [], [], [], None
    for t in rises:
        if not at(changes["top_tb.shift_dr"], t - 1):
            continue
        index = at(changes["top_tb.bridge.bit_index"], t - 1)
        if index == 0:
            tdi, tdo, start = [], [], t
        tdi.append(at(changes["top_tb.tdi"], t - 1))
        tdo.append(at(changes["top_tb.tdo"], t - 1))
        if index == 63 and start is not None:
            frames.append(
                {
                    "start": start,
                    "end": t,
                    "tdi": sum(b << i for i, b in enumerate(tdi)),
                    "tdo": sum(b << i for i, b in enumerate(tdo)),
                }
            )
    return frames


def rtl_fields() -> dict[str, list[tuple[str, int, int]]]:
    """Command fields per opcode, read from tile_host's decoder."""
    rtl = (ROOT / "rtl/tile_host.sv").read_text()
    fields = {}
    for op, body in re.findall(r"OP_(\w+): begin(.*?)\n\s*end", rtl, flags=re.S):
        fields[op] = [
            (name, int(hi), int(lo or hi))
            for name, hi, lo in re.findall(
                r"(\w+) <= command\[(\d+)(?::(\d+))?\]", body
            )
        ]
    return fields


def op_name(word: int) -> str:
    return {0: "NOP", 1: "WRITE", 2: "READ", 3: "START", 4: "STATUS", 5: "DISPLAY"}[
        word >> 60
    ]


def jtag(assets: Path | None) -> None:
    changes = simulate()
    frames = words(changes)
    tck_ps = changes["top_tb.tck"][2][0] - changes["top_tb.tck"][0][0]
    lag, skew = host.REPLY_LAG, host.TDI_SKEW_BITS
    for n, frame in enumerate(
        frames[lag:], start=lag
    ):  # the reply framing the RTL promises
        assert frame["tdo"] >> 32 == (host.REPLY_MAGIC << 16 | (n - lag + 1)), (
            n,
            hex(frame["tdo"]),
        )
    fields = rtl_fields()

    # Bit-level crop: READ C[10] from bank 0 in the first result check.
    target = host.read_word(0, 10)
    n = next(i for i, f in enumerate(frames) if f["tdi"] == target)
    frame = frames[n]
    t0 = frame["start"] - tck_ps // 2 - 2 * tck_ps
    span = 74
    t1 = t0 + span * tck_ps

    def window(name: str) -> list[tuple[float, int]]:
        trace = changes[name]
        points = [(0.0, at(trace, t0))]
        points += [((t - t0) / tck_ps, v) for t, v in trace if t0 < t < t1]
        return points

    reply = frame["tdo"]
    tdi_bands = [
        (f"op = {target >> 60}", 60, 63),
        ("bank = 0", 52, 52),
        ("addr = 10", 40, 45),
        ("unused, 0", 0, 39),
    ]
    tdo_bands = [
        (f"data = C[8] = 0x{reply & 0xFFFFFFFF:08X}", 0, 31),
        (f"seq = {(reply >> 32) & 0xFFFF}", 32, 47),
        (f"magic 0x{reply >> 48:04X}", 48, 63),
    ]
    first_bit = (frame["start"] - t0) / tck_ps
    rows = [
        ("TCK  (tb 24 MHz)", "top_tb.tck", "clock"),
        ("shift_dr", "top_tb.shift_dr", "bit"),
        ("TDI  host to bridge", "top_tb.tdi", "bit"),
        ("TDO  bridge to host", "top_tb.tdo", "bit"),
        ("bit_index", "top_tb.bridge.bit_index", "bus"),
        ("word_toggle", "top_tb.bridge.word_toggle", "bit"),
        ("clk  (tile domain)", "top_tb.clk", "clock"),
        ("execute", "top_tb.dut.execute", "bit"),
        ("sequence_count", "top_tb.dut.sequence_count", "bus"),
        ("reply_data", "top_tb.dut.reply_data", "bus"),
    ]
    fig, ax = plt.subplots(figsize=(16, 7.2))
    height = 1.0
    for r, (label, name, kind) in enumerate(rows):
        y = -r * 1.6
        ax.text(
            -1.0,
            y + height / 2,
            label,
            ha="right",
            va="center",
            fontsize=10.5,
            color=INK if r < 6 else MUTED,
        )
        points = window(name)
        if kind in ("bit", "clock"):
            xs, ys = [], []
            for i, (x, v) in enumerate(points):
                if i:
                    xs.append(x)
                    ys.append(ys[-1])
                xs.append(x)
                ys.append(y + v * height)
            xs.append(span)
            ys.append(ys[-1])
            color = (
                ACCENT
                if name in ("top_tb.tdi", "top_tb.tdo")
                else (MUTED if kind == "clock" else INK)
            )
            ax.plot(xs, ys, color=color, linewidth=1.3 if kind == "clock" else 1.8)
        else:
            edges = [*points, (span, None)]
            for (x, v), (nx, _) in zip(edges, edges[1:]):
                ax.add_patch(
                    Rectangle(
                        (x + 0.08, y + 0.1),
                        nx - x - 0.16,
                        height - 0.2,
                        fill=False,
                        edgecolor=BLUE,
                        linewidth=1.2,
                    )
                )
                text = f"{v}" if name != "top_tb.dut.reply_data" else f"0x{v:08X}"
                if nx - x > 0.8 and (name != "top_tb.bridge.bit_index" or v % 8 == 0):
                    ax.text(
                        (x + nx) / 2,
                        y + height / 2,
                        text,
                        ha="center",
                        va="center",
                        fontsize=8.5,
                    )
        bands = (
            tdi_bands
            if name == "top_tb.tdi"
            else tdo_bands
            if name == "top_tb.tdo"
            else []
        )
        for text, lo, hi in bands:
            # tb drives TDI on the falling edge before bit i is sampled; TDO bit i is the value
            # launched on the rising edge before the one that samples it.
            shift = -0.5 if name == "top_tb.tdi" else -1.0
            x0, x1 = first_bit + lo + shift, first_bit + hi + 1 + shift
            ax.add_patch(
                Rectangle(
                    (x0, y - 0.18),
                    x1 - x0,
                    height + 0.36,
                    color=ACCENT,
                    alpha=0.10,
                    linewidth=0,
                )
            )
            ax.text(
                (x0 + x1) / 2,
                y + height + 0.24,
                f"{text}  [{hi}:{lo}]" if hi != lo else f"{text}  [{hi}]",
                ha="center",
                va="bottom",
                fontsize=8.5,
                color=ACCENT,
            )
    for x in (first_bit, first_bit + 64):
        ax.axvline(x, color=GRID, linewidth=1, zorder=0)
    ax.text(
        first_bit + 32,
        2.0,
        f"one 64-bit word = 64 TCK, LSB first: word {n + 1} = "
        f"READ C[10]; its own reply returns {lag} words later",
        ha="center",
        fontsize=11,
        color=INK,
    )
    ax.set_xlim(-14, span + 0.5)
    ax.set_ylim(-len(rows) * 1.6 + 0.3, 2.6)
    ax.axis("off")
    fig.tight_layout()
    save(fig, "jtag-word", assets)

    # Word-level view: the job's START, then STATUS, from the same simulation.
    s = next(i for i, f in enumerate(frames) if f["tdi"] >> 60 == 4)
    view = frames[s - 3 : s + 3]
    fig, ax = plt.subplots(figsize=(16, 5.6))
    width = 2.3
    for k, frame in enumerate(view):
        x = k * width
        word = frame["tdi"]
        label = op_name(word) + (" (job, bank 0)" if word >> 60 == 3 else "")
        ax.add_patch(
            Rectangle((x + 0.05, 2.0), width - 0.1, 0.8, fill=False, edgecolor=INK)
        )
        ax.text(
            x + width / 2,
            2.4,
            f"{label}\nword {s - 3 + k + 1}",
            ha="center",
            va="center",
            fontsize=10,
        )
        rep = frame["tdo"]
        data = rep & 0xFFFFFFFF
        detail = f"seq {(rep >> 32) & 0xFFFF}\n0x{data:08X}"
        if view[k - lag]["tdi"] >> 60 == 4 and k >= lag:
            status = host.Status.decode(data)
            detail = (
                f"seq {(rep >> 32) & 0xFFFF}: STATUS reply\n{status.cycles} cycles, job {status.jobs}, "
                f"finished={int(status.finished)}"
            )
        highlight = k >= lag and view[k - lag]["tdi"] >> 60 == 4
        ax.add_patch(
            Rectangle(
                (x + 0.05, 0.4),
                width - 0.1,
                0.9,
                fill=highlight,
                alpha=0.18 if highlight else 1,
                facecolor=ACCENT,
                edgecolor=ACCENT if highlight else MUTED,
            )
        )
        ax.text(x + width / 2, 0.85, detail, ha="center", va="center", fontsize=9)
        if k + lag < len(view):
            ax.add_patch(
                FancyArrowPatch(
                    (x + width / 2, 1.95),
                    ((k + lag) * width + width / 2, 1.35),
                    arrowstyle="-|>",
                    mutation_scale=12,
                    color=ACCENT if word >> 60 == 4 else GRID,
                    connectionstyle="arc3,rad=-0.15",
                )
            )
    ax.text(-0.2, 2.4, "TDI\n(command)", ha="right", va="center", color=INK)
    ax.text(-0.2, 0.85, "TDO\n(reply)", ha="right", va="center", color=INK)
    ax.text(
        0,
        3.25,
        f"Reply lag: word n carries the reply to word n-{lag} (simulated, tb/top_tb.sv). "
        "The tile needs 67 clocks, so the host sends two NOPs before STATUS.",
        fontsize=11,
        color=INK,
    )
    # Skew strip from host/bf16_host.py constants and the board measurement in docs/design.md.
    y = -1.0
    cells = 24
    scale = 6 * width / cells
    for i in range(cells):
        ax.add_patch(
            Rectangle(
                (i * scale, y),
                scale * 0.9,
                0.45,
                fill=False,
                edgecolor=MUTED,
                linewidth=0.8,
            )
        )
        ax.text(
            i * scale + scale * 0.45,
            y + 0.22,
            str(i),
            ha="center",
            va="center",
            fontsize=7.5,
            color=MUTED,
        )
        if i + skew < cells:
            ax.add_patch(
                Rectangle(
                    ((i + skew) * scale, y - 0.9),
                    scale * 0.9,
                    0.45,
                    fill=False,
                    edgecolor=ACCENT,
                    linewidth=0.8,
                )
            )
            ax.text(
                (i + skew) * scale + scale * 0.45,
                y - 0.68,
                str(i),
                ha="center",
                va="center",
                fontsize=7.5,
                color=ACCENT,
            )
    ax.add_patch(
        FancyArrowPatch(
            (0.45 * scale, y - 0.02),
            ((skew + 0.45) * scale, y - 0.43),
            arrowstyle="-|>",
            mutation_scale=12,
            color=ACCENT,
        )
    )
    ax.text(
        -0.2, y + 0.22, "host TDI bit", ha="right", va="center", fontsize=9, color=MUTED
    )
    ax.text(
        -0.2,
        y - 0.68,
        "bridge sees it",
        ha="right",
        va="center",
        fontsize=9,
        color=ACCENT,
    )
    ax.text(
        0,
        y - 1.35,
        f"Board only: TDI reaches the bridge {skew} TCK after the TDO framing (found by sweeping "
        f"all 64 offsets; same at 6, 16 and 24 MHz). pack_scan shifts every scan {skew} bits earlier. "
        "Simulation does not model it.",
        fontsize=9.5,
        color=MUTED,
    )
    ax.set_xlim(-1.6, 6 * width + 0.1)
    ax.set_ylim(y - 1.6, 3.5)
    ax.axis("off")
    fig.tight_layout()
    save(fig, "jtag-protocol", assets)

    # Field map, read from the RTL decoder.
    reply_fields = [("magic 0xB16A", 63, 48), ("sequence", 47, 32), ("data", 31, 0)]
    status_fields = [
        ("cycles", 31, 16),
        ("jobs", 15, 8),
        ("flags", 7, 3),
        ("wr err", 2, 2),
        ("done", 1, 1),
        ("busy", 0, 0),
    ]
    layouts = [
        (op, [("op", 63, 60), *fields[op]])
        for op in ("WRITE", "READ", "START", "DISPLAY")
    ]
    layouts += [
        ("STATUS", [("op", 63, 60)]),
        ("reply", reply_fields),
        ("STATUS data", status_fields),
    ]
    fig, ax = plt.subplots(figsize=(16, 5.2))
    for r, (name, spans) in enumerate(layouts):
        y = -r
        ax.text(
            -0.6,
            y + 0.35,
            name,
            ha="right",
            va="center",
            fontsize=10.5,
            color=INK if r < 5 else MUTED,
        )
        ax.add_patch(Rectangle((0, y), 64, 0.7, fill=False, edgecolor=GRID))
        for label, hi, lo in spans:
            x = 63 - hi
            ax.add_patch(
                Rectangle(
                    (x, y),
                    hi - lo + 1,
                    0.7,
                    facecolor=ACCENT if label == "op" else BLUE,
                    alpha=0.35,
                    edgecolor=INK,
                    linewidth=0.8,
                )
            )
            text = (
                label.replace("write_", "")
                .replace("read_", "")
                .replace("host_", "")
                .replace("job_bank", "job bank")
            )
            bit_range = f"[{hi}:{lo}]" if hi != lo else f"[{hi}]"
            ax.text(
                x + (hi - lo + 1) / 2,
                y + 0.35,
                f"{text}\n{bit_range}" if hi - lo >= 3 else text,
                ha="center",
                va="center",
                fontsize=8 if hi - lo >= 3 else 6.5,
                rotation=0 if hi - lo >= 3 else 90,
            )
    for bit in (63, 48, 32, 16, 0):
        ax.text(63 - bit + 0.5, 0.95, str(bit), ha="center", fontsize=8, color=MUTED)
    ax.text(
        0,
        1.45,
        "64-bit command and reply words, as decoded and assembled in rtl/tile_host.sv",
        fontsize=11,
        color=INK,
    )
    ax.set_xlim(-9, 64.5)
    ax.set_ylim(-len(layouts) + 0.5, 1.9)
    ax.axis("off")
    fig.tight_layout()
    save(fig, "jtag-fields", assets)

    if assets:

        def wave(name: str, kind: str) -> str:
            points = window(name)
            out, last = "", None
            for cycle in range(span):
                value = at([(round(x * 2), v) for x, v in points], cycle * 2 + 1)
                if kind == "bit":
                    out += "." if value == last else str(value)
                else:
                    out += "." if value == last else "="
                last = value
            return out

        wavejson = {
            "source": "tb/top_tb.sv simulated by scripts/figures.py; one char per TCK",
            "signal": [
                {"name": "tck", "wave": "p" + "." * (span - 1)},
                {"name": "tdi", "wave": wave("top_tb.tdi", "bit")},
                {"name": "tdo", "wave": wave("top_tb.tdo", "bit")},
                {"name": "shift_dr", "wave": wave("top_tb.shift_dr", "bit")},
                {
                    "name": "word_toggle",
                    "wave": wave("top_tb.bridge.word_toggle", "bit"),
                },
            ],
            "word": {
                "index": n + 1,
                "tdi": f"0x{target:016X}",
                "tdo": f"0x{reply:016X}",
                "first_bit_cycle": first_bit,
                "tdi_fields": tdi_bands,
                "tdo_fields": tdo_bands,
            },
            "reply_lag_words": lag,
            "tdi_skew_bits_board": skew,
            "fields": {op: spans for op, spans in layouts},
        }
        (assets / "wavejson.json").write_text(
            json.dumps(wavejson, separators=(",", ":"))
        )
        image = Image.open(assets / "jtag-word.webp")
        w, h = image.size
        crop = image.crop(
            (int(w * 0.525), int(h * 0.17), w, int(h * 0.17 + w * 0.475 / 1.6))
        )
        crop.resize((640, 400)).save(
            assets / "jtag-word-thumb.webp", "WEBP", quality=82
        )


# ---------------------------------------------------------------- training loss


class ReferenceTile:
    """host.Tile with the board replaced by the reference model it bit-checks against."""

    def __init__(self) -> None:
        self.jobs = 0

    def run(self, a, b, c=None, transpose_a=False, transpose_b=False, accumulate=False):
        self.jobs += 1
        return host.reference(
            [host.bf16(x) for x in a],
            [host.bf16(x) for x in b],
            c,
            transpose_a,
            transpose_b,
            accumulate,
        )

    def show(self, digits: int, leds: int) -> None:
        pass


def training(assets: Path | None) -> None:
    tile = ReferenceTile()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        host.command_train(tile, argparse.Namespace(epochs=48, delay=0))
    losses = [
        float(v) for v in re.findall(r"epoch +\d+ +loss +([\d.]+)", out.getvalue())
    ]
    assert tile.jobs == 193 and len(losses) == 49, (tile.jobs, len(losses))
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.plot(
        range(len(losses)), losses, color=ACCENT, linewidth=2, marker="o", markersize=4
    )
    ax.set_yscale("log")
    ax.set_xlabel("epoch (each update is 4 tile jobs: forward, dW, dX, SGD step)")
    ax.set_ylabel("loss, 0.5 * sum of squared error")
    for x, label, va in (
        (0, f"{losses[0]:.3f}", "bottom"),
        (len(losses) - 1, f"{losses[-1]:.6f}", "top"),
    ):
        ax.annotate(
            label,
            (x, losses[x]),
            textcoords="offset points",
            xytext=(6, 8 if va == "bottom" else -14),
            fontsize=11,
            color=INK,
        )
    ax.set_title(
        f"Dense-layer training on the tile: {tile.jobs} jobs, loss {losses[0]:.3f} to {losses[-1]:.6f}. "
        "Curve from the host's exact reference model; the board run matched every job bit for bit.",
        loc="left",
        fontsize=11.5,
        color=INK,
    )
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    save(fig, "training-loss", assets)
    if assets:
        (assets / "training-loss.json").write_text(
            json.dumps(
                {
                    "source": "host/bf16_host.py command_train on the reference model",
                    "jobs": tile.jobs,
                    "loss": losses,
                },
                separators=(",", ":"),
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--assets", type=Path, help="also write .webp and .json here")
    parser.add_argument("--reports", type=Path, help="Quartus output_files directory")
    args = parser.parse_args()
    global REPORTS
    REPORTS = args.reports or REPORTS
    IMG.mkdir(parents=True, exist_ok=True)
    if args.assets:
        args.assets.mkdir(parents=True, exist_ok=True)
    for figure in (resources, timing, jtag, training):
        figure(args.assets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
