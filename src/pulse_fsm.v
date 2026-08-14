/*
 * ============================================================
 *  pulse_fsm
 * ============================================================
 *  CPMG-style multi-echo sequencing core.
 *
 *  Sequence:
 *    90 deg pulse -> tau -> [180 deg pulse -> tau -> ECHO -> tau]
 *                              repeated `echo_count` times -> IDLE
 *
 *  Physical assumption: the 180 deg pulse takes exactly twice as
 *  long as the 90 deg pulse (fixed RF drive amplitude), so only
 *  `pulse_width` is taken as input; 180 deg internally uses
 *  pulse_width * 2.
 *
 *  All durations are in raw clock cycles, supplied at runtime
 *  from config_regs (this module has no knowledge of nanoseconds
 *  or the actual clock frequency - that is the caller's
 *  responsibility).
 * ============================================================
 */

`default_nettype none

module pulse_fsm #(
    parameter integer READOUT_CYCLES = 50 // fixed short echo-capture window
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        start,        // pulse high for 1 cycle to begin
    input  wire [3:0]  echo_count,   // number of echoes (0 treated as 1)
    input  wire [7:0]  pulse_width,  // 90 deg pulse width, in cycles
    input  wire [15:0] delay_time,   // tau, in cycles

    output reg          rf_gate,     // 1 = RF pulse (90 or 180) active
    output reg          tr_switch,   // 0 = TX, 1 = RX (only during ECHO)
    output reg          seq_busy,
    output reg          seq_done,    // 1-cycle pulse at sequence end
    output reg  [3:0]   echo_index   // which echo is currently active
);

    // ------------------------------------------------------------
    // FSM state encoding
    // ------------------------------------------------------------
    localparam [2:0]
        S_IDLE      = 3'd0,
        S_PULSE_90  = 3'd1,
        S_DELAY_A   = 3'd2, // tau before first 180
        S_PULSE_180 = 3'd3,
        S_DELAY_B   = 3'd4, // tau before echo/readout
        S_READOUT   = 3'd5, // echo capture window (RX)
        S_DELAY_C   = 3'd6; // tau after echo, before next 180 (or done)

    reg [2:0]  state, next_state;
    reg [31:0] cnt;

    wire [3:0] echo_count_eff = (echo_count == 4'd0) ? 4'd1 : echo_count;

    // ------------------------------------------------------------
    // Target cycle count for the current state
    // ------------------------------------------------------------
    reg [31:0] target;
    always @(*) begin
        case (state)
            S_PULSE_90:  target = {24'd0, pulse_width};
            S_DELAY_A:   target = {16'd0, delay_time};
            S_PULSE_180: target = {23'd0, pulse_width, 1'b0}; // x2
            S_DELAY_B:   target = {16'd0, delay_time};
            S_READOUT:   target = READOUT_CYCLES;
            S_DELAY_C:   target = {16'd0, delay_time};
            default:     target = 32'd0;
        endcase
    end

    wire cnt_done = (target == 0) ? 1'b1 : (cnt >= target - 32'd1);

    // ------------------------------------------------------------
    // Counter: resets on every state change
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cnt <= 32'd0;
        else if (state != next_state)
            cnt <= 32'd0;
        else if (state != S_IDLE)
            cnt <= cnt + 32'd1;
        else
            cnt <= 32'd0;
    end

    // ------------------------------------------------------------
    // Echo index counter
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            echo_index <= 4'd0;
        else if (state == S_IDLE)
            echo_index <= 4'd0;
        else if (state == S_READOUT && next_state == S_DELAY_C)
            echo_index <= echo_index + 4'd1;
    end

    wire more_echoes_left = (echo_index + 4'd1) < echo_count_eff;

    // ------------------------------------------------------------
    // FSM: state register
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= S_IDLE;
        else
            state <= next_state;
    end

    // ------------------------------------------------------------
    // FSM: next-state logic
    // ------------------------------------------------------------
    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE:      next_state = start ? S_PULSE_90 : S_IDLE;
            S_PULSE_90:  next_state = cnt_done ? S_DELAY_A   : S_PULSE_90;
            S_DELAY_A:   next_state = cnt_done ? S_PULSE_180 : S_DELAY_A;
            S_PULSE_180: next_state = cnt_done ? S_DELAY_B   : S_PULSE_180;
            S_DELAY_B:   next_state = cnt_done ? S_READOUT   : S_DELAY_B;
            S_READOUT:   next_state = cnt_done ? S_DELAY_C   : S_READOUT;
            S_DELAY_C:   next_state = cnt_done
                                        ? (more_echoes_left ? S_PULSE_180 : S_IDLE)
                                        : S_DELAY_C;
            default:     next_state = S_IDLE;
        endcase
    end

    // ------------------------------------------------------------
    // Registered outputs
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rf_gate   <= 1'b0;
            tr_switch <= 1'b0; // safe TX default
            seq_busy  <= 1'b0;
            seq_done  <= 1'b0;
        end else begin
            rf_gate   <= (state == S_PULSE_90) || (state == S_PULSE_180);
            tr_switch <= (state == S_READOUT) ? 1'b1 : 1'b0;
            seq_busy  <= (state != S_IDLE);
            seq_done  <= (state == S_DELAY_C) && cnt_done && !more_echoes_left;
        end
    end

endmodule
