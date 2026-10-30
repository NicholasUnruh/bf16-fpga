# BF16 FPGA

- Scope: `training_tile_v4` running on a DE1-SoC, plus the JTAG link and host that drive it. ASIC design and tile changes belong in `openroad-chip-lab`; small board demos belong in `de1-soc-playground`.
- `rtl/vendor/` is unmodified. Change the design in the chip lab, then copy it here and update `rtl/vendor/README.md`.
- Run `make check` before committing. It must report real ALUTs: a design Yosys optimizes away fails the gate.
- Board claims need board evidence: `make build program selftest train`. Simulation does not model the JTAG hub (see the skew note in `docs/design.md`).
- Reset is active-low `KEY[0]`. Pins live only in `quartus/bf16.qsf`.
- `make build` fails on negative slack. Do not weaken `quartus/timing.sdc` or `scripts/gate.py` to pass.
- Programming is volatile: it changes the FPGA until power-off, never the flash or microSD.
- `host/bf16_host.py` bit-compares every job with an exact FP32 reference. Keep it that way; a reference mismatch is a finding, not noise.
- Keep README at or below 200 words and each `docs/` file at or below 500.
