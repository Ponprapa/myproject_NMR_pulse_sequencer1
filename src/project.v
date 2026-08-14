/*
 * ============================================================
 *  tt_um_ponprapa_nmr_pulse_sequencer (top-level wrapper)
 * ============================================================
 *  Connects the standard Tiny Tapeout pin interface to two
 *  linked submodules:
 *
 *    config_regs  - latches runtime-configurable parameters
 *                   (echo_count, pulse_width, delay_time)
 *    pulse_fsm    - CPMG-style multi-echo sequencing core,
 *                   consumes the config_regs outputs directly
 *
 *  ---------------------------------------------------------
 *  Configuration protocol (uio_in bits, all edge-triggered):
 *  ---------------------------------------------------------
 *    uio_in[0] = load_echo_count   : latch ui_in[3:0]  -> echo_count
 *    uio_in[1] = load_pulse_width  : latch ui_in[7:0]  -> pulse_width
 *    uio_in[2] = load_delay_low    : latch ui_in[7:0]  -> delay_time[7:0]
 *    uio_in[3] = load_delay_high   : latch ui_in[7:0]  -> delay_time[15:8]
 *    uio_in[4] = start_trigger     : begin the sequence
 *
 *  ---------------------------------------------------------
 *  Output pin mapping (uo_out):
 *  ---------------------------------------------------------
 *    uo_out[0]   = rf_gate     (1 = RF power amplifier ON)
 *    uo_out[1]   = sine_en     (1 = external sine/DDS source ON,
 *                                mirrors rf_gate exactly)
 *    uo_out[2]   = tr_switch   (0 = TX, 1 = RX; RX only during ECHO)
 *    uo_out[3]   = seq_busy
 *    uo_out[4]   = seq_done    (1-cycle pulse when sequence ends)
 *    uo_out[7:5] = echo_index[2:0] (which echo is active, debug)
 * ============================================================
 */

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

    // ------------------------------------------------------------
    // Configuration registers
    // ------------------------------------------------------------
    wire [3:0]  echo_count;
    wire [7:0]  pulse_width;
    wire [15:0] delay_time;

    config_regs u_config_regs (
        .clk           (clk),
        .rst_n         (rst_n),
        .data_in       (ui_in),
        .load_echo     (uio_in[0]),
        .load_width    (uio_in[1]),
        .load_delay_lo (uio_in[2]),
        .load_delay_hi (uio_in[3]),
        .echo_count    (echo_count),
        .pulse_width   (pulse_width),
        .delay_time    (delay_time)
    );

    // ------------------------------------------------------------
    // Sequencing core
    // ------------------------------------------------------------
    wire       rf_gate;
    wire       tr_switch;
    wire       seq_busy;
    wire       seq_done;
    wire [3:0] echo_index;

    wire start_trigger = uio_in[4] & ena;

    pulse_fsm u_pulse_fsm (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start_trigger),
        .echo_count  (echo_count),
        .pulse_width (pulse_width),
        .delay_time  (delay_time),
        .rf_gate     (rf_gate),
        .tr_switch   (tr_switch),
        .seq_busy    (seq_busy),
        .seq_done    (seq_done),
        .echo_index  (echo_index)
    );

    // sine_en mirrors rf_gate exactly (separate physical pin, same
    // timing, per the "pulse ON together with sine ON" requirement)
    wire sine_en = rf_gate;

    // ------------------------------------------------------------
    // Output pin mapping
    // ------------------------------------------------------------
    assign uo_out = {
        echo_index[2:0], // [7:5]
        seq_done,        // [4]
        seq_busy,        // [3]
        tr_switch,       // [2]
        sine_en,         // [1]
        rf_gate          // [0]
    };

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    wire _unused = &{uio_in[7:5], echo_index[3], 1'b0};

endmodule
