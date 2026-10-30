// Executes JTAG command words against the unmodified training_tile_v4.
// Word layout is documented in docs/design.md; host/bf16_host.py is the other end.
module tile_host (
    input  logic clk,
    input  logic reset,
    input  logic [63:0] word_in,
    input  logic word_toggle,
    output logic [63:0] reply,
    output logic [23:0] display,
    output logic [9:0] leds
);
    localparam logic [3:0] OP_NOP = 4'd0;
    localparam logic [3:0] OP_WRITE = 4'd1;
    localparam logic [3:0] OP_READ = 4'd2;
    localparam logic [3:0] OP_START = 4'd3;
    localparam logic [3:0] OP_STATUS = 4'd4;
    localparam logic [3:0] OP_DISPLAY = 4'd5;
    localparam logic [15:0] REPLY_MAGIC = 16'hB16A;

    logic [2:0] toggle_sync;
    logic execute;
    logic [63:0] command;
    logic [15:0] sequence_count;
    logic [31:0] reply_data;
    logic read_pending;

    logic start, transpose_a, transpose_b, accumulate, job_bank, host_bank;
    logic [2:0] write_enable;
    logic [5:0] write_addr, read_addr;
    logic [31:0] write_data, read_data;
    logic write_ready, busy, done;
    logic [4:0] exception_flags;
    logic write_error, job_finished;
    logic [15:0] job_cycles;
    logic [7:0] job_count;

    training_tile_v4 tile (
        .clk(clk), .rst(reset), .start(start),
        .transpose_a(transpose_a), .transpose_b(transpose_b), .accumulate(accumulate),
        .job_bank(job_bank), .host_bank(host_bank),
        .write_enable(write_enable), .write_addr(write_addr), .write_data(write_data),
        .read_addr(read_addr), .read_data(read_data), .write_ready(write_ready),
        .busy(busy), .done(done), .exception_flags(exception_flags)
    );

    assign reply = {REPLY_MAGIC, sequence_count, reply_data};

    always_ff @(posedge clk) begin
        toggle_sync <= {toggle_sync[1:0], word_toggle};
        if (reset) begin
            execute <= 1'b0;
            sequence_count <= '0;
            reply_data <= '0;
            read_pending <= 1'b0;
            start <= 1'b0;
            transpose_a <= 1'b0;
            transpose_b <= 1'b0;
            accumulate <= 1'b0;
            job_bank <= 1'b0;
            host_bank <= 1'b0;
            write_enable <= '0;
            write_addr <= '0;
            read_addr <= '0;
            write_data <= '0;
            write_error <= 1'b0;
            job_finished <= 1'b0;
            job_cycles <= '0;
            job_count <= '0;
            display <= 24'h00BF16;
            leds <= '0;
        end else begin
            start <= 1'b0;
            write_enable <= '0;
            read_pending <= 1'b0;
            execute <= toggle_sync[2] ^ toggle_sync[1];
            if (toggle_sync[2] ^ toggle_sync[1]) begin
                command <= word_in;
                sequence_count <= sequence_count + 1'b1;
            end
            if (|write_enable && !write_ready) write_error <= 1'b1;
            if (read_pending) reply_data <= read_data;
            if (busy) job_cycles <= job_cycles + 1'b1;
            if (done) begin
                job_finished <= 1'b1;
                job_count <= job_count + 1'b1;
            end
            if (execute) begin
                case (command[63:60])
                    OP_WRITE: begin
                        host_bank <= command[52];
                        write_enable <= command[55:53];
                        write_addr <= command[45:40];
                        write_data <= command[31:0];
                    end
                    OP_READ: begin
                        host_bank <= command[52];
                        read_addr <= command[45:40];
                        read_pending <= 1'b1;
                    end
                    OP_START: begin
                        job_bank <= command[3];
                        accumulate <= command[2];
                        transpose_b <= command[1];
                        transpose_a <= command[0];
                        start <= 1'b1;
                        job_cycles <= '0;
                        job_finished <= 1'b0;
                    end
                    OP_STATUS: reply_data <= {job_cycles, job_count, exception_flags,
                                              write_error, job_finished, busy};
                    OP_DISPLAY: begin
                        display <= command[23:0];
                        leds <= command[33:24];
                    end
                    default: begin
                    end
                endcase
            end
        end
    end
endmodule
