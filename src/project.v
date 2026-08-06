/*
 * ============================================================
 *  tt_um_ponprapa_nmr_pulse_sequencer - Tiny Tapeout wrapper
 * ============================================================
 *  Thin wrapper that maps the standard TT pin interface
 *  (ui_in / uo_out / uio_*) onto the high-precision
 *  nmr_pulse_sequencer core (see nmr_pulse_sequencer.v).
 *
 *  Pin mapping
 *  -----------
 *  ui_in[0]    = start_trigger  (pulse high for >=1 clk to start)
 *  ui_in[7:1]  = unused
 *
 *  uo_out[0]   = rf_gate    (1 = RF amplifier ON)
 *  uo_out[1]   = tr_switch  (0 = TX, 1 = RX)
 *  uo_out[2]   = seq_busy   (1 while a sequence is running)
 *  uo_out[3]   = seq_done   (1-cycle pulse at end of READOUT)
 *  uo_out[6:4] = state_out  (current FSM state, debug)
 *  uo_out[7]   = unused (tied 0)
 *
 *  uio_*       = unused (all inputs, high-Z / driven 0)
 *
 *  IMPORTANT - clock frequency assumption
 *  ---------------------------------------
 *  The core's timing parameters (*_NS) are converted to clock
 *  cycles using CLK_PERIOD_NS, which MUST match the actual
 *  clock frequency driving `clk` on silicon / in simulation:
 *
 *    - Tiny Tapeout demo board default clock is commonly 10 MHz
 *      (CLK_PERIOD_NS = 100)
 *    - The core was designed against a 100 MHz assumption in the
 *      standalone testbench (CLK_PERIOD_NS = 10)
 *
 *  Set CLK_PERIOD_NS below to match whatever clock source will
 *  actually drive this design before hardening. Getting this
 *  wrong will not break functionality (the FSM still sequences
 *  correctly) but every real-world duration will be off by
 *  whatever ratio the assumed vs. actual clock differs by.
 * ============================================================
 */

`default_nettype none

module tt_um_ponprapa_nmr_pulse_sequencer #(
    // --- Clock assumption: adjust to match the real clock source ---
    parameter integer CLK_PERIOD_NS   = 100,     // default: 10 MHz TT demo clock
    // --- Sequence timing (ns) - tune to real NMR requirements ---
    parameter integer PULSE_90_NS     = 5_000,    // 5 us
    parameter integer DELAY_TAU_NS    = 500_000,  // 500 us
    parameter integer PULSE_180_NS    = 10_000,   // 10 us
    parameter integer DELAY_ECHO_NS   = 500_000,  // 500 us
    parameter integer RINGDOWN_NS     = 200,      // 200 ns
    parameter integer READOUT_NS      = 1_000_000 // 1 ms
) (
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
    // Core signals
    // ------------------------------------------------------------
    wire        rf_gate;
    wire        tr_switch;
    wire [2:0]  state_out;
    wire        seq_busy;
    wire        seq_done;

    wire        start_trigger = ui_in[0] & ena;

    nmr_pulse_sequencer #(
        .CLK_PERIOD_NS (CLK_PERIOD_NS),
        .PULSE_90_NS   (PULSE_90_NS),
        .DELAY_TAU_NS  (DELAY_TAU_NS),
        .PULSE_180_NS  (PULSE_180_NS),
        .DELAY_ECHO_NS (DELAY_ECHO_NS),
        .RINGDOWN_NS   (RINGDOWN_NS),
        .READOUT_NS    (READOUT_NS)
    ) core (
        .clk           (clk),
        .rst_n         (rst_n),
        .start_trigger (start_trigger),
        .rf_gate       (rf_gate),
        .tr_switch     (tr_switch),
        .state_out     (state_out),
        .seq_busy      (seq_busy),
        .seq_done      (seq_done)
    );

    // ------------------------------------------------------------
    // Output pin mapping
    // ------------------------------------------------------------
    assign uo_out = {
        1'b0,        // [7]   unused
        state_out,   // [6:4] FSM state (debug)
        seq_done,    // [3]
        seq_busy,    // [2]
        tr_switch,   // [1]
        rf_gate      // [0]
    };

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    // ------------------------------------------------------------
    // Unused signal handling (avoid synthesis warnings)
    // ------------------------------------------------------------
    wire _unused = &{ui_in[7:1], uio_in, 1'b0};

endmodule
