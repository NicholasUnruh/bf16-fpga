module top (
    input  logic CLOCK_50,
    input  logic [3:0] KEY,
    output logic [9:0] LEDR,
    output logic [6:0] HEX0,
    output logic [6:0] HEX1,
    output logic [6:0] HEX2,
    output logic [6:0] HEX3,
    output logic [6:0] HEX4,
    output logic [6:0] HEX5
);
    logic tck, tdi, tdo, capture_dr, shift_dr, word_toggle;
    logic [63:0] word_in, reply;
    logic [23:0] display;
    logic tile_clk, locked;
    logic [1:0] reset_sync;

    tile_clock clocks (.clock_50(CLOCK_50), .tile_clk(tile_clk), .locked(locked));

    always_ff @(posedge tile_clk) reset_sync <= {reset_sync[0], ~KEY[0] || !locked};

    jtag_link link (
        .offline_clock(CLOCK_50), .offline_data(KEY[1]), .tck(tck), .tdi(tdi), .capture_dr(capture_dr), .shift_dr(shift_dr), .tdo(tdo)
    );
    jtag_word_bridge bridge (
        .tck(tck), .tdi(tdi), .capture_dr(capture_dr), .shift_dr(shift_dr), .tdo(tdo),
        .word_out(word_in), .word_toggle(word_toggle), .reply(reply)
    );
    tile_host host (
        .clk(tile_clk), .reset(reset_sync[1]), .word_in(word_in), .word_toggle(word_toggle),
        .reply(reply), .display(display), .leds(LEDR)
    );

    seven_segment h0 (.value(display[3:0]), .blank(1'b0), .segments_n(HEX0));
    seven_segment h1 (.value(display[7:4]), .blank(1'b0), .segments_n(HEX1));
    seven_segment h2 (.value(display[11:8]), .blank(1'b0), .segments_n(HEX2));
    seven_segment h3 (.value(display[15:12]), .blank(1'b0), .segments_n(HEX3));
    seven_segment h4 (.value(display[19:16]), .blank(1'b0), .segments_n(HEX4));
    seven_segment h5 (.value(display[23:20]), .blank(1'b0), .segments_n(HEX5));
endmodule
