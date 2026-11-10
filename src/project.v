`default_nettype none

module tt_um_ponprapa_nmr_pulse_sequencer (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire        ena,
    input  wire        clk,
    input  wire        rst_n
);

    // Input synchronisers (asynchronous pins -> clk domain).
    // Same depth for data and strobes so the captured byte matches.
    reg [7:0] ui_s1,  ui_s2;
    reg [4:0] uio_s1, uio_s2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ui_s1  <= 8'd0;  ui_s2  <= 8'd0;
            uio_s1 <= 5'd0;  uio_s2 <= 5'd0;
        end else begin
            ui_s1  <= ui_in;        ui_s2  <= ui_s1;
            uio_s1 <= uio_in[4:0];  uio_s2 <= uio_s1;
        end
    end

    wire [3:0]  echo_count;
    wire [7:0]  pulse_width;
    wire [15:0] delay_time;

    config_regs u_config_regs (            // module unchanged
        .clk           (clk),
        .rst_n         (rst_n),
        .data_in       (ui_s2),
        .load_echo     (uio_s2[0]),
        .load_width    (uio_s2[1]),
        .load_delay_lo (uio_s2[2]),
        .load_delay_hi (uio_s2[3]),
        .echo_count    (echo_count),
        .pulse_width   (pulse_width),
        .delay_time    (delay_time)
    );

    wire       rf_gate, rf_phase, tr_switch;
    wire       seq_busy, seq_done, cfg_err;
    wire [3:0] echo_index;

    wire start_trigger = uio_s2[4] & ena;

    pulse_fsm u_pulse_fsm (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start_trigger),
        .echo_count  (echo_count),
        .pulse_width (pulse_width),
        .delay_time  (delay_time),
        .rf_gate     (rf_gate),
        .rf_phase    (rf_phase),
        .tr_switch   (tr_switch),
        .seq_busy    (seq_busy),
        .seq_done    (seq_done),
        .cfg_err     (cfg_err),
        .echo_index  (echo_index)
    );

    wire sine_en = rf_gate;

    assign uo_out = {               // unchanged mapping
        echo_index[2:0], // [7:5]
        seq_done,        // [4]
        seq_busy,        // [3]
        tr_switch,       // [2]
        sine_en,         // [1]
        rf_gate          // [0]
    };

    assign uio_out = {1'b0, cfg_err, rf_phase, 5'b0};
    assign uio_oe  = 8'b0110_0000;   // uio[6:5] outputs, others inputs

    wire _unused = &{uio_in[7:5], echo_index[3], 1'b0};

endmodule
