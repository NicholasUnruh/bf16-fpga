// Altera virtual JTAG endpoint. Without Quartus the offline pins stand in for the TAP so
// that Yosys keeps the logic behind the bridge instead of proving it unreachable.
module jtag_link (
    input  logic offline_clock,
    input  logic offline_data,
    output logic tck,
    output logic tdi,
    output logic capture_dr,
    output logic shift_dr,
    input  logic tdo
);
`ifdef ALTERA_RESERVED_QIS
    logic [0:0] ir_in;
    logic cdr, sdr;

    sld_virtual_jtag #(
        .sld_auto_instance_index("NO"), .sld_instance_index(0), .sld_ir_width(1)
    ) node (
        .tdo(tdo), .ir_out(1'b0), .tck(tck), .tdi(tdi), .ir_in(ir_in),
        .virtual_state_cdr(cdr), .virtual_state_sdr(sdr)
    );
    assign capture_dr = cdr && ir_in[0];
    assign shift_dr = sdr && ir_in[0];
`else
    assign tck = offline_clock;
    assign tdi = offline_data;
    assign capture_dr = 1'b0;
    assign shift_dr = 1'b1;
`endif
endmodule
