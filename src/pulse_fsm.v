/*
 * ============================================================
 *  pulse_fsm  (PROPOSED REVISION - not yet simulated)
 * ============================================================
 *  CPMG multi-echo sequencing core.
 *
 *  Timing definition (all values in clock cycles):
 *    pw   = pulse_width        : 90 deg pulse width (180 deg = 2*pw)
 *    dly  = delay_time         : gap from END of 90 to START of 1st 180
 *    tau_c = dly + 1.5*pw      : centre(90) -> centre(180) (physics tau)
 *
 *  CPMG condition (Meiboom-Gill):
 *    centre-to-centre spacing of consecutive 180s = 2*tau_c
 *    => gap from END of a 180 to START of the next 180
 *         G = 2*tau_c - 2*pw = 2*dly + pw
 *    The echo peak sits exactly in the middle of G, so G is split as
 *         DELAY_B (pre)  + READOUT (R) + DELAY_C (post) = G
 *         pre  = floor((G - R)/2),  post = (G - R) - pre
 *    => readout window centred on the echo to within 0.5 cycle,
 *       and 180-to-180 spacing is exact.
 *
 *  Safety / robustness additions:
 *    - parameters are copied into shadow registers while IDLE and
 *      frozen during a run (config writes cannot corrupt a run)
 *    - start is edge-detected (holding start high does not re-arm)
 *    - invalid parameters are rejected at start -> cfg_err = 1
 *    - rf_phase output: 0 for the 90 deg pulse (x), 1 for all
 *      180 deg pulses (y)  -> Meiboom-Gill 90 deg phase shift
 *    - counter reduced from 32 to 18 bits (max needed G = 131325)
 * ============================================================
 */

`default_nettype none

module pulse_fsm #(
    parameter integer READOUT_CYCLES = 50, // echo acquisition window
    parameter integer MIN_GAP_CYCLES = 1   // min idle cycles between
                                           // rf_gate and tr_switch
                                           // (set from real T/R ring-down spec)
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        start,        // level or pulse; rising edge used
    input  wire [3:0]  echo_count,   // number of echoes, 1..15 (0 = invalid)
    input  wire [7:0]  pulse_width,  // 90 deg pulse width, cycles (0 = invalid)
    input  wire [15:0] delay_time,   // gap end-of-90 -> start-of-180 (0 = invalid)

    output reg         rf_gate,      // 1 = RF pulse (90 or 180) active
    output reg         rf_phase,     // 0 = x (90 pulse), 1 = y (180 pulses)
    output reg         tr_switch,    // 0 = TX/protect, 1 = RX (readout only)
    output reg         seq_busy,
    output reg         seq_done,     // 1-cycle pulse at sequence end
    output reg         cfg_err,      // 1 = last start rejected (bad params)
    output reg  [3:0]  echo_index    // echoes completed (aligned to outputs)
);

    localparam [2:0]
        S_IDLE      = 3'd0,
        S_PULSE_90  = 3'd1,
        S_DELAY_A   = 3'd2, // dly                 (90 -> 1st 180)
        S_PULSE_180 = 3'd3,
        S_DELAY_B   = 3'd4, // pre  = floor((G-R)/2)
        S_READOUT   = 3'd5, // R    (echo centred in window)
        S_DELAY_C   = 3'd6; // post = (G-R) - pre

    localparam [17:0] R_CYC   = READOUT_CYCLES;
    localparam [17:0] GAP_MIN = READOUT_CYCLES + 2 * MIN_GAP_CYCLES;

    reg [2:0]  state, next_state;
    reg [17:0] cnt;
    reg [3:0]  echo_cnt;   // internal echo counter

    // Shadow registers: track config while IDLE, freeze while busy
    reg [3:0]  sh_n;
    reg [7:0]  sh_pw;
    reg [15:0] sh_dly;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sh_n   <= 4'd0;
            sh_pw  <= 8'd0;
            sh_dly <= 16'd0;
        end else if (state == S_IDLE) begin
            sh_n   <= echo_count;
            sh_pw  <= pulse_width;
            sh_dly <= delay_time;
        end
    end

    // Echo-gap arithmetic: G = 2*dly + pw (max 131325 < 2^18)
    wire [17:0] gap_total = {1'b0, sh_dly, 1'b0} + {10'd0, sh_pw};
    wire        gap_ok    = (gap_total >= GAP_MIN);
    wire [17:0] gap_rem   = gap_total - R_CYC;          // used only if gap_ok
    wire [17:0] pre_cyc   = {1'b0, gap_rem[17:1]};      // floor(rem/2)
    wire [17:0] post_cyc  = gap_rem - pre_cyc;          // ceil(rem/2)

    wire cfg_valid = (sh_n   != 4'd0)  &&
                     (sh_pw  != 8'd0)  &&
                     (sh_dly != 16'd0) &&
                     gap_ok;

    // Start edge detection
    reg start_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) start_d <= 1'b0;
        else        start_d <= start;
    end
    wire start_pulse = start & ~start_d;

    // Target length of the current state
    reg [17:0] target;
    always @(*) begin
        case (state)
            S_PULSE_90:  target = {10'd0, sh_pw};
            S_DELAY_A:   target = {2'd0,  sh_dly};
            S_PULSE_180: target = {9'd0,  sh_pw, 1'b0};   // x2
            S_DELAY_B:   target = pre_cyc;
            S_READOUT:   target = R_CYC;
            S_DELAY_C:   target = post_cyc;
            default:     target = 18'd1;
        endcase
    end

    // state lasts exactly `target` cycles (target >= 1 guaranteed by cfg_valid)
    wire cnt_done = ((cnt + 18'd1) >= target);

    // Counter: cleared on every state change (unchanged behaviour)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cnt <= 18'd0;
        else if (state != next_state)
            cnt <= 18'd0;
        else if (state != S_IDLE)
            cnt <= cnt + 18'd1;
        else
            cnt <= 18'd0;
    end

    // Echo counter (unchanged logic, internal)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            echo_cnt <= 4'd0;
        else if (state == S_IDLE)
            echo_cnt <= 4'd0;
        else if (state == S_READOUT && next_state == S_DELAY_C)
            echo_cnt <= echo_cnt + 4'd1;
    end

    wire more_echoes_left = (echo_cnt < sh_n);

    // FSM
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= S_IDLE;
        else        state <= next_state;
    end

    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE:      next_state = (start_pulse && cfg_valid) ? S_PULSE_90 : S_IDLE;
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

    // Configuration error flag (updated on every start attempt)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cfg_err <= 1'b0;
        else if (state == S_IDLE && start_pulse)
            cfg_err <= ~cfg_valid;
    end

    // Registered outputs (all share the same 1-cycle latency)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rf_gate    <= 1'b0;
            rf_phase   <= 1'b0;
            tr_switch  <= 1'b0;   // safe TX/protect default
            seq_busy   <= 1'b0;
            seq_done   <= 1'b0;
            echo_index <= 4'd0;
        end else begin
            rf_gate    <= (state == S_PULSE_90) || (state == S_PULSE_180);
            rf_phase   <= (state != S_IDLE) && (state != S_PULSE_90);
            tr_switch  <= (state == S_READOUT);
            seq_busy   <= (state != S_IDLE);
            seq_done   <= (state == S_DELAY_C) && cnt_done && !more_echoes_left;
            echo_index <= echo_cnt;
        end
    end

endmodule
