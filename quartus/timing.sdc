create_clock -name CLOCK_50 -period 20.000 [get_ports {CLOCK_50}]
derive_pll_clocks
derive_clock_uncertainty
# word_out, word_toggle and reply cross on purpose; see rtl/jtag_word_bridge.sv.
if {[llength [get_clocks -nowarn altera_reserved_tck]] == 0} {
    create_clock -name altera_reserved_tck -period 41.667 [get_ports {altera_reserved_tck}]
}
set_clock_groups -asynchronous -group {altera_reserved_tck} \
    -group [get_clocks {CLOCK_50 *divclk}]
