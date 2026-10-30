.PHONY: check test sim lint synth build program selftest train bench clean

SOURCES := $(wildcard rtl/*.sv) $(wildcard rtl/vendor/*.v) $(wildcard rtl/vendor/hardfloat/*.v)
INCLUDES := -Irtl/vendor/hardfloat
READS := $(foreach file,$(SOURCES),read_verilog -sv $(INCLUDES) $(file);)
QUARTUS := build/quartus

# Everything that needs no board or Quartus. Run before every commit.
check: test sim lint synth

test:
	python3 -m unittest discover -s tests

sim:
	mkdir -p build
	iverilog -g2012 -s top_tb $(INCLUDES) -o build/sim.vvp $(SOURCES) tb/top_tb.sv
	vvp build/sim.vvp > build/sim.log
	grep -q "PASS: bf16-fpga" build/sim.log

lint:
	verilator --lint-only --top-module top -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL \
		-Wno-UNUSEDPARAM -Wno-PINCONNECTEMPTY -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
		-Wno-BLKSEQ $(INCLUDES) tb/lint.vlt $(SOURCES)

synth:
	mkdir -p build
	yosys -q -l build/synth.log -p '$(READS) synth_intel_alm -family cyclonev -top top; check -assert; write_json build/netlist.json'
	python3 scripts/gate.py synth build/netlist.json

# Compile for the board (about 6 minutes), failing on any timing violation.
build:
	mkdir -p $(QUARTUS)
	cp quartus/* $(QUARTUS)/
	cd $(QUARTUS) && quartus_sh --flow compile bf16
	python3 scripts/gate.py timing $(QUARTUS)/output_files/bf16.sta.rpt
	python3 scripts/gate.py pins $(QUARTUS)/output_files/bf16.pin quartus/bf16.qsf

# The HPS is device 1 on the JTAG chain; the FPGA is device 2.
program:
	quartus_pgm --mode=jtag --cable=1 -o "p;$(QUARTUS)/output_files/bf16.sof@2"

selftest:
	python3 host/bf16_host.py selftest

train:
	python3 host/bf16_host.py train

bench:
	python3 host/bf16_host.py bench

clean:
	rm -rf build
