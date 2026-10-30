# Vendored accelerator RTL

Unmodified copies from `openroad-chip-lab` at `d7b957c`: `rtl/training_tile_v4.v`, `rtl/training_tile_engine.v`, `rtl/fp32_accum_fma_pipe.v` and `third_party/hardfloat/` (Berkeley HardFloat Release 1; the BSD licence stays in each source).

`hardfloat/` is flattened, so its `SHA256SUMS` drops the upstream `RISCV/` prefix. Verify with `cd hardfloat && sha256sum -c SHA256SUMS`.

Change the design in the chip lab, then copy it here.
