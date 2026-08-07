/*
 * ============================================================
 *  NMR Pulse Sequencer - High-Precision Timing Core
 * ============================================================
 *  Target: 100 MHz system clock (10 ns clock period)
 *  Timing resolution: 10 ns per counter tick (32-bit counter)
 *
 *  Sequence (FSM):
 *    IDLE -> PULSE_90 -> DELAY_TAU -> PULSE_180 -> DELAY_ECHO
 *          -> RINGDOWN -> READOUT -> IDLE
 *
 *  RINGDOWN is a dedicated safety state inserted between
 *  DELAY_ECHO and READOUT. It guarantees tr_switch cannot enter
 *  RX mode until a fixed ring-down guard time has elapsed after
 *  the last RF pulse closed, protecting the LNA from residual
 *  transmit-path energy. This is in addition to (not a
 *  replacement for) the physics-driven DELAY_ECHO wait.
 *
 *  All durations are specified in nanoseconds as Verilog
 *  parameters and converted internally to clock-cycle counts
 *  based on CLK_PERIOD_NS. Minimum 1 cycle is enforced so a
 *  zero-length parameter cannot collapse a state.
 * ============================================================
 */

`default_nettype none
`timescale 1ns/1ps

module nmr_pulse_sequencer #(
    parameter integer CLK_PERIOD_NS   = 10,      // 100 MHz
    parameter integer PULSE_90_NS     = 5_000,    // 5 us   (90 deg pulse width)
    parameter integer DELAY_TAU_NS    = 500_000,  // 500 us (tau delay)
    parameter integer PULSE_180_NS    = 10_000,   // 10 us  (180 deg pulse width)
    parameter integer DELAY_ECHO_NS   = 500_000,  // 500 us (echo delay, = tau)
    parameter integer RINGDOWN_NS     = 200,      // 200 ns (LNA protection guard)
    parameter integer READOUT_NS      = 1_000_000 // 1 ms   (acquisition window)
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start_trigger,

    output reg          rf_gate,     // 1 = RF amplifier ON
    output reg          tr_switch,   // 0 = TX mode, 1 = RX mode
    output reg  [2:0]   state_out,   // debug: current FSM state
    output reg          seq_busy,    // 1 while sequence is running
    output reg          seq_done     // 1-cycle pulse when READOUT completes
);

    // ------------------------------------------------------------
    // Convert nanosecond parameters to clock-cycle counts.
    // A minimum of 1 cycle is enforced to avoid a degenerate
    // (zero-length) state if a parameter is set to 0.
    // ------------------------------------------------------------
    function integer ns_to_cycles;
        input integer ns_val;
        begin
            ns_to_cycles = (ns_val / CLK_PERIOD_NS > 0) ? (ns_val / CLK_PERIOD_NS) : 1;
        end
    endfunction

    localparam integer PULSE_90_CYCLES   = ns_to_cycles(PULSE_90_NS);
    localparam integer DELAY_TAU_CYCLES  = ns_to_cycles(DELAY_TAU_NS);
    localparam integer PULSE_180_CYCLES  = ns_to_cycles(PULSE_180_NS);
    localparam integer DELAY_ECHO_CYCLES = ns_to_cycles(DELAY_ECHO_NS);
    localparam integer RINGDOWN_CYCLES   = ns_to_cycles(RINGDOWN_NS);
    localparam integer READOUT_CYCLES    = ns_to_cycles(READOUT_NS);

    // ------------------------------------------------------------
    // FSM state encoding
    // ------------------------------------------------------------
    localparam [2:0]
        S_IDLE       = 3'd0,
        S_PULSE_90   = 3'd1,
        S_DELAY_TAU  = 3'd2,
        S_PULSE_180  = 3'd3,
        S_DELAY_ECHO = 3'd4,
        S_RINGDOWN   = 3'd5,
        S_READOUT    = 3'd6;

    reg [2:0]  state, next_state;
    reg [31:0] cycle_cnt;      // 32-bit high-precision timing counter
    wire       cnt_done;

    // Target cycle count for the current state
    reg [31:0] target_cycles;

    always @(*) begin
        case (state)
            S_PULSE_90:   target_cycles = PULSE_90_CYCLES;
            S_DELAY_TAU:  target_cycles = DELAY_TAU_CYCLES;
            S_PULSE_180:  target_cycles = PULSE_180_CYCLES;
            S_DELAY_ECHO: target_cycles = DELAY_ECHO_CYCLES;
            S_RINGDOWN:   target_cycles = RINGDOWN_CYCLES;
            S_READOUT:    target_cycles = READOUT_CYCLES;
            default:      target_cycles = 32'd0;
        endcase
    end

    assign cnt_done = (cycle_cnt >= target_cycles - 32'd1);

    // ------------------------------------------------------------
    // Counter: increments every cycle while in a timed state,
    // resets whenever the FSM changes state.
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cycle_cnt <= 32'd0;
        else if (state != next_state)
            cycle_cnt <= 32'd0;
        else if (state != S_IDLE)
            cycle_cnt <= cycle_cnt + 32'd1;
        else
            cycle_cnt <= 32'd0;
    end

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
            S_IDLE:       next_state = start_trigger ? S_PULSE_90 : S_IDLE;
            S_PULSE_90:   next_state = cnt_done ? S_DELAY_TAU  : S_PULSE_90;
            S_DELAY_TAU:  next_state = cnt_done ? S_PULSE_180  : S_DELAY_TAU;
            S_PULSE_180:  next_state = cnt_done ? S_DELAY_ECHO : S_PULSE_180;
            S_DELAY_ECHO: next_state = cnt_done ? S_RINGDOWN   : S_DELAY_ECHO;
            S_RINGDOWN:   next_state = cnt_done ? S_READOUT    : S_RINGDOWN;
            S_READOUT:    next_state = cnt_done ? S_IDLE       : S_READOUT;
            default:      next_state = S_IDLE;
        endcase
    end

    // ------------------------------------------------------------
    // Output logic (registered, glitch-free)
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rf_gate   <= 1'b0;
            tr_switch <= 1'b0; // default to TX mode (safe state)
            seq_busy  <= 1'b0;
            seq_done  <= 1'b0;
            state_out <= S_IDLE;
        end else begin
            state_out <= state;

            // rf_gate: ON only during the two RF pulse states
            rf_gate <= (state == S_PULSE_90) || (state == S_PULSE_180);

            // tr_switch: TX (0) everywhere except READOUT.
            // RINGDOWN explicitly forces TX (0) even though the
            // pulse has already closed, guaranteeing the LNA is
            // protected until the guard time has fully elapsed.
            tr_switch <= (state == S_READOUT) ? 1'b1 : 1'b0;

            // seq_busy: high for the whole sequence except IDLE
            seq_busy <= (state != S_IDLE);

            // seq_done: single-cycle pulse on the READOUT -> IDLE transition
            seq_done <= (state == S_READOUT) && cnt_done;
        end
    end

endmodule
