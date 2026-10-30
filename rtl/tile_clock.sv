// The tile closes 46.9 MHz on this device, so it runs at its 40 MHz design clock.
// Simulation, lint and Yosys pass the board clock through.
module tile_clock (
    input  logic clock_50,
    output logic tile_clk,
    output logic locked
);
`ifdef ALTERA_RESERVED_QIS
    altera_pll #(
        .fractional_vco_multiplier("false"),
        .reference_clock_frequency("50.0 MHz"),
        .operation_mode("direct"),
        .number_of_clocks(1),
        .output_clock_frequency0("40.000000 MHz"),
        .phase_shift0("0 ps"),
        .duty_cycle0(50),
        .pll_type("General"),
        .pll_subtype("General")
    ) pll (
        .rst(1'b0), .outclk(tile_clk), .locked(locked),
        .fboutclk(), .fbclk(1'b0), .refclk(clock_50)
    );
`else
    assign tile_clk = clock_50;
    assign locked = 1'b1;
`endif
endmodule
