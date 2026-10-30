// Moves fixed 64-bit words across the JTAG (tck) boundary during one long DR scan.
// A finished word toggles word_toggle and stays stable for the next 64 tck edges, far
// longer than clk needs to synchronize the toggle, so word_out and reply need no FIFO.
module jtag_word_bridge (
    input  logic tck,
    input  logic tdi,
    input  logic capture_dr,
    input  logic shift_dr,
    output logic tdo,
    output logic [63:0] word_out,
    output logic word_toggle,
    input  logic [63:0] reply
);
    logic [63:0] shifter;
    logic [5:0] bit_index;

    initial begin
        word_out = '0;
        word_toggle = 1'b0;
    end

    always_ff @(posedge tck) begin
        if (capture_dr) begin
            shifter <= reply;
            bit_index <= '0;
        end else if (shift_dr) begin
            bit_index <= bit_index + 1'b1;
            if (bit_index == 6'd63) begin
                word_out <= {tdi, shifter[63:1]};
                word_toggle <= ~word_toggle;
                shifter <= reply;
            end else begin
                shifter <= {tdi, shifter[63:1]};
            end
        end
    end
    assign tdo = shifter[0];
endmodule
