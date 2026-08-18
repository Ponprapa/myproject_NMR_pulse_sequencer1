"""
Cocotb testbench for tt_um_ponprapa_nmr_pulse_sequencer
(CPMG-style, runtime-configurable via config_regs + pulse_fsm).

Verifies:
  1. Reset leaves all outputs in the safe/idle state.
  2. The external configuration protocol correctly loads
     echo_count, pulse_width, and delay_time.
  3. rf_gate pulse widths observed on uo_out exactly match the
     configured pulse_width (90 deg) and pulse_width*2 (180 deg).
  4. sine_en mirrors rf_gate on every single sample (no skew).
  5. tr_switch is asserted only during the READOUT window, and
     NEVER overlaps with rf_gate (transmit/receive safety).
  6. The sequence correctly loops for the configured number of
     echoes (echo_index advances) and seq_done fires exactly
     once, after which the design returns to idle.

uo_out bit mapping (must match project.v):
  [0] rf_gate   [1] sine_en   [2] tr_switch
  [3] seq_busy  [4] seq_done  [7:5] echo_index[2:0]

uio_in bit mapping (config protocol, must match project.v):
  [0] load_echo_count   [1] load_pulse_width
  [2] load_delay_low    [3] load_delay_high
  [4] start_trigger
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

BIT_RF_GATE   = 0
BIT_SINE_EN   = 1
BIT_TR_SWITCH = 2
BIT_SEQ_BUSY  = 3
BIT_SEQ_DONE  = 4
ECHO_IDX_LSB  = 5

UIO_LOAD_ECHO  = 0
UIO_LOAD_WIDTH = 1
UIO_LOAD_DLO   = 2
UIO_LOAD_DHI   = 3
UIO_START      = 4

CLK_PERIOD_NS = 10  # 100 MHz for a fast, short test run


def decode(uo_out_val):
    return {
        "rf_gate":   (uo_out_val >> BIT_RF_GATE)   & 1,
        "sine_en":   (uo_out_val >> BIT_SINE_EN)   & 1,
        "tr_switch": (uo_out_val >> BIT_TR_SWITCH) & 1,
        "seq_busy":  (uo_out_val >> BIT_SEQ_BUSY)  & 1,
        "seq_done":  (uo_out_val >> BIT_SEQ_DONE)  & 1,
        "echo_idx":  (uo_out_val >> ECHO_IDX_LSB)  & 0x7,
    }


async def strobe(dut, bit):
    """Pulse one uio_in bit high for exactly one clock cycle."""
    dut.uio_in.value = (1 << bit)
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 1)


async def configure(dut, echo_count, pulse_width, delay_time):
    dut.ui_in.value = echo_count & 0xF
    await strobe(dut, UIO_LOAD_ECHO)

    dut.ui_in.value = pulse_width & 0xFF
    await strobe(dut, UIO_LOAD_WIDTH)

    dut.ui_in.value = delay_time & 0xFF
    await strobe(dut, UIO_LOAD_DLO)

    dut.ui_in.value = (delay_time >> 8) & 0xFF
    await strobe(dut, UIO_LOAD_DHI)

    dut.ui_in.value = 0


async def reset_dut(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


@cocotb.test()
async def test_reset_safe_state(dut):
    """After reset, everything must be idle/safe before any config."""
    dut._log.info("Start reset safety test")

    clock = Clock(dut.clk, CLK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    d = decode(int(dut.uo_out.value))
    assert d["rf_gate"] == 0, "rf_gate must be 0 after reset"
    assert d["sine_en"] == 0, "sine_en must be 0 after reset"
    assert d["tr_switch"] == 0, "tr_switch must be 0 (TX/safe) after reset"
    assert d["seq_busy"] == 0, "seq_busy must be 0 after reset"
    assert d["echo_idx"] == 0, "echo_idx must be 0 after reset"

    dut._log.info("Reset safety test passed")


@cocotb.test()
async def test_config_protocol(dut):
    """Configuration writes must not start the sequence by
    themselves - rf_gate/seq_busy must remain 0 until start_trigger
    is pulsed, even though non-default values were just written."""
    dut._log.info("Start config-protocol test")

    clock = Clock(dut.clk, CLK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    await configure(dut, echo_count=3, pulse_width=7, delay_time=20)

    await ClockCycles(dut.clk, 10)

    d = decode(int(dut.uo_out.value))
    assert d["seq_busy"] == 0, "Writing config must not auto-start the sequence"
    assert d["rf_gate"] == 0, "rf_gate must stay 0 until start_trigger"

    dut._log.info("Config-protocol test passed")


@cocotb.test()
async def test_cpmg_sequence_timing_and_safety(dut):
    """Run a full 2-echo CPMG sequence with known small parameters
    and verify: exact pulse widths, sine_en/rf_gate lockstep,
    tr_switch/rf_gate mutual exclusion, echo looping, and a single
    seq_done pulse at the very end."""
    dut._log.info("Start full CPMG sequence test")

    clock = Clock(dut.clk, CLK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    ECHO_COUNT  = 2
    PULSE_WIDTH = 5   # cycles (90 deg)
    DELAY_TIME  = 10  # cycles (tau)

    await configure(dut, echo_count=ECHO_COUNT,
                     pulse_width=PULSE_WIDTH, delay_time=DELAY_TIME)

    # Fire start_trigger
    dut.uio_in.value = (1 << UIO_START)
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0

    # Sample every cycle, tracking rf_gate / tr_switch run-lengths
    rf_runs = []      # list of (start_cycle, length) for rf_gate high runs
    tr_runs = []      # same for tr_switch
    echo_idx_trace = []
    seq_done_count = 0
    overlap_violations = 0
    sine_mismatch = 0

    in_rf_run = False
    rf_run_len = 0
    in_tr_run = False
    tr_run_len = 0

    MAX_CYCLES = 400  # generous margin over the ~175 cycles expected

    for i in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        d = decode(int(dut.uo_out.value))

        if d["rf_gate"] != d["sine_en"]:
            sine_mismatch += 1

        if d["rf_gate"] and d["tr_switch"]:
            overlap_violations += 1

        if d["rf_gate"]:
            rf_run_len += 1
            in_rf_run = True
        elif in_rf_run:
            rf_runs.append(rf_run_len)
            rf_run_len = 0
            in_rf_run = False

        if d["tr_switch"]:
            tr_run_len += 1
            in_tr_run = True
        elif in_tr_run:
            tr_runs.append(tr_run_len)
            tr_run_len = 0
            in_tr_run = False

        if not echo_idx_trace or echo_idx_trace[-1] != d["echo_idx"]:
            echo_idx_trace.append(d["echo_idx"])

        if d["seq_done"]:
            seq_done_count += 1

        # Stop shortly after the sequence returns to idle following
        # completion.
        if seq_done_count > 0 and not d["seq_busy"] and i > 20:
            break

    # Flush any run still in progress at loop end
    if in_rf_run:
        rf_runs.append(rf_run_len)
    if in_tr_run:
        tr_runs.append(tr_run_len)

    dut._log.info(f"rf_gate pulse widths observed: {rf_runs}")
    dut._log.info(f"tr_switch (readout) widths observed: {tr_runs}")
    dut._log.info(f"echo_idx trace: {echo_idx_trace}")
    dut._log.info(f"seq_done pulses seen: {seq_done_count}")

    # --- Check 1: sine_en tracked rf_gate on every sample ---
    assert sine_mismatch == 0, (
        f"sine_en differed from rf_gate on {sine_mismatch} sample(s) - "
        f"they must be identical at all times"
    )

    # --- Check 2: rf_gate and tr_switch never overlapped ---
    assert overlap_violations == 0, (
        f"rf_gate and tr_switch were both high simultaneously on "
        f"{overlap_violations} sample(s) - TX/RX safety violation"
    )

    # --- Check 3: exact pulse widths ---
    # Expected: one 90-deg pulse (PULSE_WIDTH), then one 180-deg
    # pulse (PULSE_WIDTH*2) per echo.
    expected_rf_runs = [PULSE_WIDTH] + [PULSE_WIDTH * 2] * ECHO_COUNT
    assert rf_runs == expected_rf_runs, (
        f"rf_gate pulse widths do not match configured pulse_width.\n"
        f"  expected: {expected_rf_runs}\n"
        f"  got:      {rf_runs}"
    )

    # --- Check 4: readout window fired once per echo ---
    assert len(tr_runs) == ECHO_COUNT, (
        f"expected {ECHO_COUNT} readout (tr_switch) windows, "
        f"got {len(tr_runs)}: {tr_runs}"
    )
    assert all(w == tr_runs[0] for w in tr_runs), (
        f"all readout windows should be the same fixed length, got {tr_runs}"
    )

    # --- Check 5: echo_idx advanced through 0..ECHO_COUNT-1 and
    #     returned to 0 at the end ---
    assert 0 in echo_idx_trace and (ECHO_COUNT - 1) in echo_idx_trace, (
        f"echo_idx did not visit the expected range 0..{ECHO_COUNT-1}: "
        f"{echo_idx_trace}"
    )
    assert echo_idx_trace[-1] == 0, (
        f"echo_idx should return to 0 once the sequence completes, "
        f"got trace ending in {echo_idx_trace[-5:]}"
    )

    # --- Check 6: seq_done pulsed exactly once ---
    assert seq_done_count == 1, (
        f"expected exactly 1 seq_done pulse, saw {seq_done_count}"
    )

    dut._log.info("Full CPMG sequence test passed: pulse widths, "
                   "sine_en lockstep, TX/RX safety, echo looping, "
                   "and seq_done all verified.")
