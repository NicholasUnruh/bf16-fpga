# BF16 FPGA

An eight-lane BF16 training accelerator running on a Terasic DE1-SoC. The tile is the unmodified `training_tile_v4` from `openroad-chip-lab`; a PC feeds it over the board's USB-Blaster cable and bit-checks every result.

It trains a dense layer on silicon: loss 57.355 → 0.000780 in 193 jobs, matching chip-lab simulation.

```sh
make check      # tests, simulation, lint, Yosys synthesis
make build      # Quartus compile, fails on missed timing
make program    # load the volatile FPGA image
make train      # watch the loss on HEX and LEDs
make selftest   # random jobs, bit-compared
make bench      # throughput
```

| Path | Contents |
|---|---|
| `rtl/` | Board top and JTAG bridge |
| `rtl/vendor/` | Unmodified tile and HardFloat |
| `host/` | PC driver and reference model |
| `tb/`, `tests/` | RTL testbench, host unit tests |
| `quartus/` | Project, pins, timing constraints |
| `docs/` | [Design](docs/design.md), [results](docs/results.md) |

Requires Quartus Lite with Cyclone V support, Icarus Verilog, Verilator and Yosys.
