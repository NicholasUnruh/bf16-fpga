# Report the worst setup paths per clock from a finished compile (no board needed).
# Run from build/quartus after `make build`: quartus_sta -t ../../scripts/worst_paths.tcl
# Writes output_files/bf16.paths.rpt, read by scripts/report_figures.py.
project_open bf16
create_timing_netlist -model slow -temperature 85 -voltage 1100
read_sdc
update_timing_netlist
set out output_files/bf16.paths.rpt
file delete -force $out
foreach clock [list {clocks|pll|general[0].gpll~PLL_OUTPUT_COUNTER|divclk} altera_reserved_tck] {
    report_timing -setup -npaths 5 -detail summary -to_clock [get_clocks $clock] \
        -panel_name "Worst setup paths: $clock" -file $out -append
}
report_timing -setup -npaths 1 -detail full_path \
    -to_clock [get_clocks {clocks|pll|general[0].gpll~PLL_OUTPUT_COUNTER|divclk}] \
    -panel_name "Critical path detail" -file $out -append
delete_timing_netlist
project_close
