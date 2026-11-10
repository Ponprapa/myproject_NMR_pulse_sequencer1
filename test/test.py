"""
Cocotb testbench for tt_um_ponprapa_nmr_pulse_sequencer
(CPMG revision with shadow registers, input synchronisers, rf_phase, cfg_err)

All timing checks are latency-independent: they compare edges
of rf_gate / tr_switch against each other, so the extra 2-cycle
synchroniser latency in project.v does not affect them.

uo_out : [0] rf_gate [1] sine_en [2] tr_switch [3] seq_busy
         [4] seq_done [7:5] echo_index[2:0]
uio_out: [5] rf_phase [6] cfg_err
uio_in : [0] load_echo [1] load_width [2] load_dlo [3] load_dhi [4] start
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

CLK_PERIOD_NS = 10      # sim only; real clock is defined in info.yaml
READOUT_CYCLES = 50     # must match pulse_fsm READOUT_CYCLES
MIN_GAP_CYCLES = 1      # must match pulse_fsm MIN_GAP_CYCLES

UIO_LOAD_ECHO, UIO_LOAD_WIDTH, UIO_LOAD_DLO, UIO_LOAD_DHI, UIO_START = range(5)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def sample(dut):
    uo = int(dut.uo_out.value)
    uio = int(dut.uio_out.value)
    return {
        "rf": uo & 1, "sine": (uo >> 1) & 1, "tr": (uo >> 2) & 1,
        "busy": (uo >> 3) & 1, "done": (uo >> 4) & 1, "eidx": (uo >> 5) & 7,
        "phase": (uio >> 5) & 1, "err": (uio >> 6) & 1,
    }


def runs(trace, key):
    """[(start_index, length), ...] of 1-runs of trace[i][key]."""
    out, s = [], None
    for i, d in enumerate(trace):
        if d[key] and s is None:
            s = i
        if not d[key] and s is not None:
            out.append((s, i - s))
            s = None
    if s is not None:
        out.append((s, len(trace) - s))
    return out


def gap_total(pw, dly):
    return 2 * dly + pw


def is_valid(n, pw, dly):
    return n != 0 and pw != 0 and dly != 0 and \
        gap_total(pw, dly) >= READOUT_CYCLES + 2 * MIN_GAP_CYCLES


def expected_cycles(n, pw, dly):
    return pw + dly + n * (2 * pw + gap_total(pw, dly))


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def reset_dut(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


async def strobe(dut, bit, hold=1):
    dut.uio_in.value = 1 << bit
    await ClockCycles(dut.clk, hold)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 1)


async def configure(dut, echo_count, pulse_width, delay_time):
    for bit, val in ((UIO_LOAD_ECHO, echo_count & 0xF),
                     (UIO_LOAD_WIDTH, pulse_width & 0xFF),
                     (UIO_LOAD_DLO, delay_time & 0xFF),
                     (UIO_LOAD_DHI, (delay_time >> 8) & 0xFF)):
        dut.ui_in.value = val
        await strobe(dut, bit)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 4)       # let synchronisers/shadows settle


async def pulse_start(dut, hold=1):
    dut.uio_in.value = 1 << UIO_START
    await ClockCycles(dut.clk, hold)
    dut.uio_in.value = 0


async def capture(dut, max_cycles, stop_when_idle=True):
    """Sample once per cycle on the falling edge (settled values)."""
    trace, seen_busy, tail = [], False, None
    for _ in range(max_cycles):
        await FallingEdge(dut.clk)
        d = sample(dut)
        trace.append(d)
        seen_busy |= bool(d["busy"])
        if stop_when_idle and seen_busy and not d["busy"] and tail is None:
            tail = 5
        if tail is not None:
            tail -= 1
            if tail == 0:
                break
    return trace


def check_cpmg(trace, n, pw, dly):
    """Full CPMG property check (latency independent)."""
    R, G = READOUT_CYCLES, gap_total(pw, dly)
    rf, tr = runs(trace, "rf"), runs(trace, "tr")

    # widths
    assert [l for _, l in rf] == [pw] + [2 * pw] * n, f"rf widths {rf}"
    assert [l for _, l in tr] == [R] * n, f"readout widths {tr}"

    s90 = rf[0][0]
    s180 = [s for s, _ in rf[1:]]

    # delay 90 -> first 180 (edge to edge)
    assert s180[0] - (s90 + pw) == dly, "DELAY_A length wrong"

    # CPMG condition: 180-to-180 spacing = 2*tau_c = 2*dly + 3*pw
    for k in range(n - 1):
        assert s180[k + 1] - s180[k] == 2 * dly + 3 * pw, \
            f"180 spacing #{k}: {s180[k + 1] - s180[k]} != {2 * dly + 3 * pw}"

    # echo centring (work in 2x units to stay integer)
    for k in range(n):
        echo2 = 2 * s180[k] + 2 * pw + (2 * dly + 3 * pw)   # 2*(c180 + tau_c)
        win2 = 2 * tr[k][0] + R                             # 2*window centre
        assert 0 <= echo2 - win2 <= 1, \
            f"echo {k}: peak {echo2 / 2} vs window centre {win2 / 2}"
        # guard gaps around the receive window
        assert tr[k][0] >= s180[k] + 2 * pw + MIN_GAP_CYCLES
        if k < n - 1:
            assert tr[k][0] + R + MIN_GAP_CYCLES <= s180[k + 1]

    # per-sample safety
    for i, d in enumerate(trace):
        assert d["sine"] == d["rf"], f"sine_en != rf_gate at {i}"
        assert not (d["rf"] and d["tr"]), f"TX/RX overlap at {i}"
        if d["rf"]:
            want = 0 if i < s90 + pw else 1
            assert d["phase"] == want, f"rf_phase wrong at {i}"

    # end of sequence
    assert sum(d["done"] for d in trace) == 1, "seq_done must pulse once"
    assert trace[-1]["busy"] == 0 and trace[-1]["eidx"] == 0
    assert not any(d["err"] for d in trace)
    assert G >= READOUT_CYCLES + 2 * MIN_GAP_CYCLES


async def run_and_check(dut, n, pw, dly):
    await configure(dut, n, pw, dly)
    await pulse_start(dut)
    trace = await capture(dut, expected_cycles(n, pw, dly) + 50)
    check_cpmg(trace, n, pw, dly)
    return trace


# 1. reset / safe state
@cocotb.test()
async def test_01_reset_safe_state(dut):
    await start_clock(dut)
    await reset_dut(dut)
    d = sample(dut)
    for k in ("rf", "sine", "tr", "busy", "done", "eidx", "phase", "err"):
        assert d[k] == 0, f"{k} must be 0 after reset"
    assert int(dut.uio_oe.value) == 0b0110_0000


# 2. config write (verified through timing - no readback port exists)
#    + strobe held high writes only once
@cocotb.test()
async def test_02_config_write_and_edge_detect(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await configure(dut, 2, 7, 40)
    await ClockCycles(dut.clk, 10)
    assert sample(dut)["busy"] == 0, "config must not auto-start"

    # hold load_width high while data changes: only first byte (9) is taken
    dut.ui_in.value = 9
    dut.uio_in.value = 1 << UIO_LOAD_WIDTH
    await ClockCycles(dut.clk, 4)
    dut.ui_in.value = 3
    await ClockCycles(dut.clk, 4)
    dut.uio_in.value = 0
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 4)

    await pulse_start(dut)
    trace = await capture(dut, expected_cycles(2, 9, 40) + 50)
    check_cpmg(trace, 2, 9, 40)


# 3-8. start, 90/180 pulses, delay, echo count, stop
@cocotb.test()
async def test_03_nominal_cpmg(dut):
    await start_clock(dut)
    await reset_dut(dut)
    trace = await run_and_check(dut, n=2, pw=5, dly=40)
    dut._log.info(f"rf runs {runs(trace, 'rf')}  tr runs {runs(trace, 'tr')}")


# 9. parameter sweep (incl. odd/even pw, gap exactly at minimum)
@cocotb.test()
async def test_04_parameter_sweep(dut):
    await start_clock(dut)
    await reset_dut(dut)
    cases = [(1, 1, 26), (1, 2, 25), (3, 5, 24), (4, 20, 200),
             (15, 3, 30), (2, 255, 300), (7, 8, 1000)]
    rnd = random.Random(1234)
    for _ in range(6):
        n, pw = rnd.randint(1, 15), rnd.randint(1, 60)
        dly = rnd.randint(max(1, (52 - pw + 1) // 2), 400)
        cases.append((n, pw, dly))
    for n, pw, dly in cases:
        assert is_valid(n, pw, dly)
        dut._log.info(f"case N={n} pw={pw} dly={dly}")
        await run_and_check(dut, n, pw, dly)
        await ClockCycles(dut.clk, 3)


# 10. invalid parameters -> no RF, cfg_err = 1; valid start clears it
@cocotb.test()
async def test_05_invalid_parameters(dut):
    await start_clock(dut)
    await reset_dut(dut)
    for n, pw, dly in [(0, 5, 40), (2, 0, 40), (2, 5, 0), (2, 5, 20)]:
        assert not is_valid(n, pw, dly)
        await configure(dut, n, pw, dly)
        await pulse_start(dut)
        trace = await capture(dut, 40, stop_when_idle=False)
        assert not any(d["rf"] or d["tr"] or d["busy"] for d in trace), \
            f"invalid {n, pw, dly} must not start"
        assert trace[-1]["err"] == 1, f"cfg_err must be set for {n, pw, dly}"
    await run_and_check(dut, 1, 5, 40)
    assert sample(dut)["err"] == 0, "valid start must clear cfg_err"


# 11. reset in the middle of a sequence
@cocotb.test()
async def test_06_reset_during_run(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await configure(dut, 3, 5, 40)
    await pulse_start(dut)
    await ClockCycles(dut.clk, 60)          # somewhere inside the train
    dut.rst_n.value = 0
    await Timer(1, units="ns")               # async reset: outputs drop at once
    d = sample(dut)
    assert d["rf"] == 0 and d["tr"] == 0 and d["busy"] == 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 3)
    # registers back to defaults (pw=10, dly=100, n=1) -> must run cleanly
    await pulse_start(dut)
    trace = await capture(dut, expected_cycles(1, 10, 100) + 50)
    check_cpmg(trace, 1, 10, 100)


# 12. restart, start during busy, start held high, config during busy
@cocotb.test()
async def test_07_restart_and_busy_protection(dut):
    await start_clock(dut)
    await reset_dut(dut)
    t1 = await run_and_check(dut, 2, 5, 40)
    await ClockCycles(dut.clk, 3)
    await pulse_start(dut)                    # same config again
    t2 = await capture(dut, expected_cycles(2, 5, 40) + 50)
    assert [l for _, l in runs(t1, "rf")] == [l for _, l in runs(t2, "rf")]

    # start pulses and config writes while busy must be ignored
    await pulse_start(dut)
    trace = []
    for i in range(expected_cycles(2, 5, 40) + 50):
        if i in (20, 60):
            dut.uio_in.value = 1 << UIO_START
        elif i in (21, 61):
            dut.uio_in.value = 0
        if i == 30:
            dut.ui_in.value = 200               # try to change delay_low
            dut.uio_in.value = 1 << UIO_LOAD_DLO
        if i == 31:
            dut.uio_in.value = 0
        await FallingEdge(dut.clk)
        trace.append(sample(dut))
    trace = trace[: max(i for i, d in enumerate(trace) if d["busy"]) + 3]
    check_cpmg(trace, 2, 5, 40)

    # the delay written during the run applies to the NEXT run (dly=200)
    await ClockCycles(dut.clk, 5)
    await pulse_start(dut)
    trace = await capture(dut, expected_cycles(2, 5, 200) + 50)
    check_cpmg(trace, 2, 5, 200)

    # start held high must give exactly one sequence
    await configure(dut, 1, 5, 40)
    dut.uio_in.value = 1 << UIO_START
    trace = await capture(dut, 3 * expected_cycles(1, 5, 40), stop_when_idle=False)
    dut.uio_in.value = 0
    assert len(runs(trace, "rf")) == 2, "held start must not re-trigger"
