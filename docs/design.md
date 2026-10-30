# Design

```text
PC: bf16_host.py ── socket ── quartus_stp ── USB-Blaster
                                                 │ JTAG, 24 MHz
FPGA: jtag_word_bridge ── tile_host ── training_tile_v4
              TCK domain │ 40 MHz domain
```

The bare tile closes 46.9 MHz, below the 50 MHz board clock, so a PLL runs it at its 40 MHz design clock.

## JTAG link

`jtag_word_bridge` moves 64-bit words during one long DR scan; `tile_host` executes them. One scan can carry thousands of words. A finished word stays stable for 64 TCK edges, far longer than the clock crossing needs, so no FIFO is required.

| Op `[63:60]` | Fields | Effect |
|---|---|---|
| 1 WRITE | enable `[55:53]`, bank `[52]`, address `[45:40]`, data `[31:0]` | Tile host write |
| 2 READ | bank `[52]`, address `[45:40]` | Reply is one C element |
| 3 START | job bank `[3]`, accumulate `[2]`, transpose B `[1]`, transpose A `[0]` | Start job |
| 4 STATUS | none | Reply: cycles `[31:16]`, jobs `[15:8]`, flags `[7:3]`, write error, finished, busy |
| 5 DISPLAY | LEDs `[33:24]`, HEX `[23:0]` | Update board outputs |

Replies are `{B16A, sequence, data}`, and the host checks every tag. Word *n* carries the reply to word *n−2*. A job finishes within two word times at 24 MHz TCK, hence two NOPs after START.

`quartus_stp` buffers stdout until it exits, so `vjtag_server.tcl` talks to Python over a loopback socket.

## TDI skew

On hardware, TDI reaches the bridge 7 TCK after its TDO framing, so `pack_scan` advances each scan by `TDI_SKEW_BITS`. This was measured by sweeping all 64 offsets and holds at 6, 16 and 24 MHz, so it counts edges rather than time. Its cause inside Altera's encrypted hub is unknown, and `tb/top_tb.sv` does not model it. If a future build changes it, tag or result checks fail loudly; rerun the sweep.

## Offline builds

Quartus defines `ALTERA_RESERVED_QIS`. Without it, `jtag_link` and `tile_clock` use stand-ins: the board clock drives the bridge, so Yosys must keep and map the whole tile.
