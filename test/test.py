"""
Cocotb testbench for tt_um_ponprapa_nmr_pulse_sequencer.

Verifies:
  1. tr_switch stays in the safe TX (0) state through reset.
  2. The FSM visits every expected state, in order, without
     skipping the RINGDOWN safety state.
  3. rf_gate is asserted ONLY while state == PULSE_90 or
     state == PULSE_180.
  4. tr_switch is asserted ONLY while state == READOUT (i.e. it
     stays TX during RINGDOWN even though the pulse has already
     closed - the core safety guarantee).
  5. seq_busy / seq_done behave correctly around the sequence.

Uses the default duration parameters compiled into project.v
(CLK_PERIOD_NS = 100, i.e. a 10 MHz clock, matching the Tiny
Tapeout demo board). Total sequence length is ~20,150 clock
cycles, which is fast enough to simulate directly without
needing to override parameters.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# --- uo_out bit mapping (must match project.v) ---
BIT_RF_GATE   = 0
BIT_TR_SWITCH = 1
BIT_SEQ_BUSY  = 2
BIT_SEQ_DONE  = 3
STATE_LSB     = 4  # uo_out[6:4]

STATE_NAMES = {
    0: "IDLE",
    1: "PULSE_90",
    2: "DELAY_TAU",
    3: "PULSE_180",
    4: "DELAY_ECHO",
    5: "RINGDOWN",
    6: "READOUT",
}

# Default duration parameters from project.v (ns) and the
# assumed clock period, used only to size the simulation run.
CLK_PERIOD_NS   = 100  # 10 MHz
PULSE_90_NS     = 5_000
DELAY_TAU_NS    = 500_000
PULSE_180_NS    = 10_000
DELAY_ECHO_NS   = 500_000
RINGDOWN_NS     = 200
READOUT_NS      = 1_000_000


def _cycles(ns):
    return max(ns // CLK_PERIOD_NS, 1)


TOTAL_CYCLES = (
    _cycles(PULSE_90_NS)
    + _cycles(DELAY_TAU_NS)
    + _cycles(PULSE_180_NS)
    + _cycles(DELAY_ECHO_NS)
    + _cycles(RINGDOWN_NS)
    + _cycles(READOUT_NS)
)
MARGIN_CYCLES = 50


def decode(uo_out_val):
    rf_gate   = (uo_out_val >> BIT_RF_GATE)   & 1
    tr_switch = (uo_out_val >> BIT_TR_SWITCH) & 1
    seq_busy  = (uo_out_val >> BIT_SEQ_BUSY)  & 1
    seq_done  = (uo_out_val >> BIT_SEQ_DONE)  & 1
    state     = (uo_out_val >> STATE_LSB) & 0x7
    return rf_gate, tr_switch, seq_busy, seq_done, state


@cocotb.test()
async def test_reset_safe_state(dut):
    """During and immediately after reset, tr_switch must stay in
    the safe TX (0) state and rf_gate must be off."""
    dut._log.info("Start reset safety test")

    clock = Clock(dut.clk, CLK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0

    await ClockCycles(dut.clk, 10)

    rf_gate, tr_switch, seq_busy, seq_done, state = decode(int(dut.uo_out.value))
    assert tr_switch == 0, "tr_switch must be TX (0) during reset"
    assert rf_gate == 0, "rf_gate must be off during reset"
    assert state == 0, "state must be IDLE during reset"

    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    dut._log.info("Reset safety test passed")


@cocotb.test()
async def test_full_sequence_order_and_safety(dut):
    """Run one full sequence and verify state order, rf_gate gating,
    and the tr_switch ring-down safety guarantee."""
    dut._log.info(
        f"Start full sequence test (expecting ~{TOTAL_CYCLES} cycles)"
    )

    clock = Clock(dut.clk, CLK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    # Fire start_trigger (ui_in[0]) for one clock cycle
    dut.ui_in.value = 0b1
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0b0

    # Sample every cycle until the sequence returns to IDLE with
    # seq_done having been observed, or we exceed the expected
    # length by a safety margin.
    visited_states = []
    last_state = None
    seq_done_seen = False
    seq_busy_seen_high = False

    max_cycles = TOTAL_CYCLES + MARGIN_CYCLES

    for i in range(max_cycles):
        await RisingEdge(dut.clk)
        rf_gate, tr_switch, seq_busy, seq_done, state = decode(int(dut.uo_out.value))

        if state != last_state:
            visited_states.append(state)
            last_state = state

        if seq_busy:
            seq_busy_seen_high = True

        # --- rf_gate must only be high during PULSE_90 (1) or PULSE_180 (3) ---
        if state in (1, 3):
            assert rf_gate == 1, (
                f"cycle {i}: expected rf_gate=1 in state "
                f"{STATE_NAMES.get(state, state)}, got 0"
            )
        else:
            assert rf_gate == 0, (
                f"cycle {i}: expected rf_gate=0 in state "
                f"{STATE_NAMES.get(state, state)}, got 1"
            )

        # --- tr_switch must only be high during READOUT (6) ---
        # Critically, it must stay 0 during RINGDOWN (5), even
        # though rf_gate has already closed by that point.
        if state == 6:
            assert tr_switch == 1, (
                f"cycle {i}: expected tr_switch=1 (RX) in READOUT, got 0"
            )
        else:
            assert tr_switch == 0, (
                f"cycle {i}: expected tr_switch=0 (TX) in state "
                f"{STATE_NAMES.get(state, state)}, got 1 "
                f"(ring-down / LNA safety violation!)"
            )

        if seq_done:
            seq_done_seen = True

        # Stop once we've returned to IDLE after having been busy
        # and having seen seq_done.
        if state == 0 and seq_done_seen and seq_busy_seen_high and i > 10:
            break

    dut._log.info(f"Visited states in order: "
                   f"{[STATE_NAMES.get(s, s) for s in visited_states]}")

    expected_order = [0, 1, 2, 3, 4, 5, 6, 0]
    assert visited_states == expected_order, (
        f"Unexpected state sequence.\n"
        f"  expected: {[STATE_NAMES.get(s, s) for s in expected_order]}\n"
        f"  got:      {[STATE_NAMES.get(s, s) for s in visited_states]}"
    )

    assert seq_done_seen, "seq_done was never asserted"
    assert seq_busy_seen_high, "seq_busy was never asserted"

    dut._log.info(
        "Full sequence test passed: correct order, rf_gate gating "
        "correct, and RINGDOWN safety state enforced tr_switch=TX "
        "throughout DELAY_ECHO and RINGDOWN."
    )
