/*
 * ============================================================
 *  config_regs
 * ============================================================
 *  Handles runtime configuration of the pulse sequencer:
 *    - echo_count  : number of echoes to acquire
 *    - pulse_width : 90 deg pulse width, in clock cycles
 *    - delay_time  : tau, in clock cycles (16-bit, loaded as
 *                    two 8-bit bytes: low then high)
 *
 *  Each field is written by pulsing its corresponding load_*
 *  strobe for one clock cycle while the desired byte is present
 *  on data_in. Strobes are edge-detected internally, so a strobe
 *  held high for multiple cycles only writes once.
 * ============================================================
 */

`default_nettype none

module config_regs (
    input  wire       clk,
    input  wire       rst_n,

    input  wire [7:0] data_in,       // byte to write (from ui_in)
    input  wire       load_echo,     // strobe: latch data_in[3:0] -> echo_count
    input  wire       load_width,    // strobe: latch data_in[7:0] -> pulse_width
    input  wire       load_delay_lo, // strobe: latch data_in[7:0] -> delay_time[7:0]
    input  wire       load_delay_hi, // strobe: latch data_in[7:0] -> delay_time[15:8]

    output reg  [3:0]  echo_count,
    output reg  [7:0]  pulse_width,
    output reg  [15:0] delay_time
);

    // ------------------------------------------------------------
    // Edge-detect each load strobe so a level held high doesn't
    // repeatedly rewrite the register every clock cycle.
    // ------------------------------------------------------------
    reg d_echo, d_width, d_dlylo, d_dlyhi;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            d_echo  <= 1'b0;
            d_width <= 1'b0;
            d_dlylo <= 1'b0;
            d_dlyhi <= 1'b0;
        end else begin
            d_echo  <= load_echo;
            d_width <= load_width;
            d_dlylo <= load_delay_lo;
            d_dlyhi <= load_delay_hi;
        end
    end

    wire p_echo  = load_echo     & ~d_echo;
    wire p_width = load_width    & ~d_width;
    wire p_dlylo = load_delay_lo & ~d_dlylo;
    wire p_dlyhi = load_delay_hi & ~d_dlyhi;

    // ------------------------------------------------------------
    // Registers (with sensible power-on defaults so the FSM has
    // valid, non-zero timing even before any configuration write)
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            echo_count  <= 4'd1;
            pulse_width <= 8'd10;
            delay_time  <= 16'd100;
        end else begin
            if (p_echo)
                echo_count <= data_in[3:0];
            if (p_width)
                pulse_width <= data_in[7:0];
            if (p_dlylo)
                delay_time[7:0] <= data_in[7:0];
            if (p_dlyhi)
                delay_time[15:8] <= data_in[7:0];
        end
    end

endmodule
