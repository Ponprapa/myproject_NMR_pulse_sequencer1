"""
Behaviour characterisation of tt_um_ponprapa_nmr_pulse_sequencer.
  (ไฟล์นี้ศึกษา "พฤติกรรม" ของวงจร tt_um_ponprapa_nmr_pulse_sequencer)

Unlike test.py (pass/fail regression), every experiment here MEASURES
what the circuit does and writes the numbers to CSV files in
test/output/ (uploaded by the GitHub "test" workflow as part of the
`test-results` artifact). Hard assertions are kept only for the safety
rules that must always hold (RF and RX never on together, sine_en ==
rf_gate, phase constant during a pulse, safe state after reset).
  (ต่างจาก test.py ที่ตัดสินแค่ผ่าน/ไม่ผ่าน ทุกการทดลองในไฟล์นี้ "วัดค่า"
   ที่วงจรทำจริง แล้วเขียนตัวเลขลงไฟล์ CSV ในโฟลเดอร์ test/output/
   ซึ่ง GitHub Actions จะอัปโหลดไว้ใน artifact ชื่อ test-results
   จะสั่งให้ test ล้ม (assert) เฉพาะกฎความปลอดภัยที่ต้องจริงเสมอ คือ
   RF กับ RX ห้ามเปิดพร้อมกัน, sine_en ต้องเท่ากับ rf_gate,
   เฟสต้องคงที่ตลอดพัลส์ และขาออกต้องปลอดภัยหลัง reset)

Experiments  (รายการการทดลอง)
  E1  pulse_width sweep        (dly, N fixed)      ไล่ค่า pw โดยตรึง dly กับ N
  E2  delay_time sweep         (pw, N fixed)       ไล่ค่า dly โดยตรึง pw กับ N
  E3  echo_count sweep 1..15   (pw, dly fixed)     ไล่ค่า N ตั้งแต่ 1 ถึง 15
  E4  boundary of the G >= 52 rule and extreme register values
                                                   ขอบของกฎ G ≥ 52 และค่าสุดขั้วของรีจิสเตอร์
  E5  start-control behaviour  (latency, start length, start while busy,
                                ena = 0, back-to-back runs)
                                                   พฤติกรรมของขา start: ความหน่วง, ความยาวการกด,
                                                   กดซ้ำตอนทำงาน, ena = 0, เริ่มรอบใหม่ทันที
  E6  reset injected in every FSM state            กด reset ในทุกสถานะของ FSM
  E7  configuration-interface timing (when may ui_in change?)
                                                   จังหวะเวลาการเขียนค่า (เปลี่ยน ui_in ได้เมื่อไร)
  E8  random regression (many random valid settings)
                                                   สุ่มค่าที่ถูกต้องหลายชุดแล้วตรวจกับสูตร

All times are in clock cycles. Real time = cycles / f_clk
(f_clk = 10 MHz in info.yaml -> 1 cycle = 100 ns).
  (เวลาทุกค่าในไฟล์นี้มีหน่วยเป็น cycle ของนาฬิกา
   เวลาจริง = จำนวน cycle ÷ ความถี่นาฬิกา; ที่ 10 MHz ตาม info.yaml 1 cycle = 100 ns)
"""

import csv                     # โมดูลมาตรฐานของ Python สำหรับเขียนไฟล์ CSV
import os                      # ใช้จัดการ path ของไฟล์/โฟลเดอร์ และอ่านตัวแปรสภาพแวดล้อม (environment variable)
import random                  # ใช้สุ่มค่าในการทดลอง E8

import cocotb                                               # ไลบรารีที่ใช้เขียน testbench ด้วย Python ควบคุม simulator
from cocotb.clock import Clock                              # คลาสสร้างสัญญาณนาฬิกาป้อนให้วงจร
from cocotb.triggers import ClockCycles, FallingEdge, Timer # ClockCycles = รอ n cycle, FallingEdge = รอขอบขาลงของนาฬิกา, Timer = รอตามเวลา (ns)

CLK_PERIOD_NS = 10          # คาบนาฬิกาในการจำลอง = 10 ns (ใช้เฉพาะ simulation ผลที่วัดเป็น cycle จึงไม่ขึ้นกับค่านี้)
READOUT_CYCLES = 50         # ความยาวหน้าต่างรับสัญญาณ R = 50 cycle ต้องตรงกับค่าใน pulse_fsm.v
MIN_GAP_CYCLES = 1          # ช่องว่างขั้นต่ำระหว่างพัลส์ RF กับหน้าต่างรับ = 1 cycle ต้องตรงกับ pulse_fsm.v
GAP_MIN = READOUT_CYCLES + 2 * MIN_GAP_CYCLES   # ค่าต่ำสุดของ G = 2·dly + pw ที่วงจรยอมรับ = 50 + 2·1 = 52
NS_PER_CYCLE_REAL = 100     # 1 cycle ของชิปจริงที่ 10 MHz = 100 ns ใช้แปลงหน่วยในคอลัมน์ที่ลงท้ายด้วย _us

UIO_LOAD_ECHO, UIO_LOAD_WIDTH, UIO_LOAD_DLO, UIO_LOAD_DHI, UIO_START = range(5)   # ตั้งชื่อหมายเลขบิตของ uio_in: 0 = load_echo, 1 = load_width, 2 = delay ไบต์ต่ำ, 3 = delay ไบต์สูง, 4 = start
# gate-level runs are much slower: skip the ~200 000-cycle case there   (การจำลองระดับเกตช้ามาก จึงข้ามกรณีที่ยาวราว 200,000 cycle)
GATE_LEVEL = os.environ.get("GATES", "") == "yes"   # True ถ้า Makefile ตั้ง GATES=yes คือกำลังจำลองแบบ gate-level
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")   # โฟลเดอร์เก็บผล = test/output (อยู่ข้างไฟล์นี้)


# ======================================================================
# helpers (self-contained: test.py is not imported, so its tests are
# not collected a second time)
#   ฟังก์ชันช่วย เขียนไว้ในไฟล์นี้เองทั้งหมด ไม่ import จาก test.py
#   เพื่อไม่ให้ cocotb เก็บ test ใน test.py มารันซ้ำอีกรอบ
# ======================================================================
def sample(dut):                                                    # อ่านขาออกทุกขาของวงจรใน cycle ปัจจุบัน คืนค่าเป็น dictionary
    uo = int(dut.uo_out.value)                                      # อ่านขาออกหลัก uo_out (8 บิต) แปลงเป็นจำนวนเต็ม
    uio = int(dut.uio_out.value)                                    # อ่านขาสองทิศทาง uio_out (8 บิต) แปลงเป็นจำนวนเต็ม
    return {                                                        # แยกแต่ละบิตออกมาเป็นชื่อที่อ่านง่าย (>> คือเลื่อนบิต, & 1 คือเอาบิตเดียว)
        "rf": uo & 1, "sine": (uo >> 1) & 1, "tr": (uo >> 2) & 1,   # บิต 0 = rf_gate, บิต 1 = sine_en, บิต 2 = tr_switch (หน้าต่างรับ)
        "busy": (uo >> 3) & 1, "done": (uo >> 4) & 1, "eidx": (uo >> 5) & 7,   # บิต 3 = seq_busy, บิต 4 = seq_done, บิต 7..5 = echo_index (& 7 คือเอา 3 บิต)
        "phase": (uio >> 5) & 1, "err": (uio >> 6) & 1,             # uio บิต 5 = rf_phase (0 = x, 1 = y), uio บิต 6 = cfg_err
    }                                                               # ปิด dictionary


def runs(trace, key):                                   # หาช่วงที่สัญญาณ key เป็น 1 ต่อเนื่อง เช่น หาพัลส์ RF แต่ละตัว
    """[(start_index, length), ...] of the 1-runs of trace[i][key]."""   # คืนรายการ (cycle ที่เริ่ม, ความยาว) ของแต่ละช่วงที่เป็น 1
    out, s = [], None                                   # out = ผลลัพธ์, s = จุดเริ่มของช่วงที่กำลังนับ (None = ยังไม่อยู่ในช่วง)
    for i, d in enumerate(trace):                       # ไล่ทุก cycle; i = หมายเลข cycle, d = ค่าขาออกใน cycle นั้น
        if d[key] and s is None:                        # สัญญาณเพิ่งเปลี่ยนเป็น 1 (ขอบขาขึ้น)
            s = i                                       # จำจุดเริ่มต้นของช่วง
        if not d[key] and s is not None:                # สัญญาณเพิ่งกลับเป็น 0 (ขอบขาลง)
            out.append((s, i - s))                      # บันทึก (จุดเริ่ม, ความยาว = i − s)
            s = None                                    # ออกจากช่วง รอช่วงถัดไป
    if s is not None:                                   # ถ้าจบ trace ทั้งที่สัญญาณยังเป็น 1 อยู่
        out.append((s, len(trace) - s))                 # ปิดช่วงสุดท้ายที่ปลาย trace
    return out                                          # คืนรายการช่วงทั้งหมด


def expected_cycles(n, pw, dly):                        # ความยาวทั้งลำดับพัลส์ตามสูตร (จำนวน cycle ที่ seq_busy เป็น 1)
    return pw + dly + n * (2 * pw + 2 * dly + pw)       # = พัลส์ 90° (pw) + ช่วงรอ A (dly) + N × [พัลส์ 180° (2pw) + ช่วงรอรวม G (2dly + pw)]


def write_csv(name, rows):                              # เขียนรายการผล (แถวละ dictionary) ลงไฟล์ CSV ชื่อ name
    if not rows:                                        # ถ้าไม่มีแถวเลย
        return                                          # ไม่ต้องเขียนไฟล์
    cols = []                                           # รายชื่อคอลัมน์
    for r in rows:                       # union of keys, first-seen order   (รวมชื่อคีย์จากทุกแถว เรียงตามลำดับที่พบครั้งแรก)
        cols += [k for k in r if k not in cols]         # เพิ่มเฉพาะคีย์ที่ยังไม่มี เพราะบางแถวมีคอลัมน์มากกว่าแถวอื่น
    os.makedirs(OUT_DIR, exist_ok=True)                 # สร้างโฟลเดอร์ output ถ้ายังไม่มี (exist_ok = มีอยู่แล้วก็ไม่ error)
    path = os.path.join(OUT_DIR, name)                  # path เต็มของไฟล์ที่จะเขียน
    with open(path, "w", newline="") as f:              # เปิดไฟล์เพื่อเขียน (newline="" กันบรรทัดว่างแทรกบน Windows)
        w = csv.DictWriter(f, fieldnames=cols, restval="")   # ตัวเขียน CSV จาก dictionary; restval="" = เว้นว่างถ้าแถวไม่มีคอลัมน์นั้น
        w.writeheader()                                 # เขียนแถวหัวตาราง (ชื่อคอลัมน์)
        w.writerows(rows)                               # เขียนข้อมูลทุกแถว


def log_table(dut, title, rows, cols):                  # พิมพ์ตารางผลลง log ของ simulator (เห็นได้ใน GitHub Actions)
    dut._log.info(title)                                # พิมพ์หัวเรื่องของตาราง
    dut._log.info("  " + " | ".join(f"{c:>12}" for c in cols))   # พิมพ์ชื่อคอลัมน์ ชิดขวา กว้าง 12 ตัวอักษร คั่นด้วย |
    for r in rows:                                      # วนทุกแถวของผล
        dut._log.info("  " + " | ".join(f"{str(r.get(c, '')):>12}" for c in cols))   # พิมพ์ค่าแต่ละคอลัมน์; r.get(c, '') = ถ้าไม่มีค่าให้เว้นว่าง ไม่ error


async def start_clock(dut):                                                 # เริ่มสร้างสัญญาณนาฬิกา
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())     # นาฬิกาคาบ 10 ns ที่ขา clk รันอยู่เบื้องหลังตลอด test


async def reset_dut(dut):                       # reset วงจรให้อยู่ในสภาพเริ่มต้น
    dut.ena.value = 1                           # เปิดใช้งานวงจร (ขา ena ของ Tiny Tapeout)
    dut.ui_in.value = 0                         # ล้างขาข้อมูลเข้า
    dut.uio_in.value = 0                        # ล้างขาควบคุม (load/start) ทั้งหมด
    dut.rst_n.value = 0                         # กด reset (active-low คือ 0 = reset)
    await ClockCycles(dut.clk, 5)               # ค้าง reset ไว้ 5 cycle
    dut.rst_n.value = 1                         # ปล่อย reset
    await ClockCycles(dut.clk, 5)               # รออีก 5 cycle ให้ synchronizer และ FSM นิ่ง


async def strobe(dut, bit):                     # ส่งพัลส์ควบคุมกว้าง 1 cycle ที่บิต bit ของ uio_in
    dut.uio_in.value = 1 << bit                 # ตั้งบิตนั้นเป็น 1 (1 << bit = เลข 1 เลื่อนไปตำแหน่ง bit)
    await ClockCycles(dut.clk, 1)               # ค้าง 1 cycle
    dut.uio_in.value = 0                        # ปล่อยกลับเป็น 0
    await ClockCycles(dut.clk, 1)               # พัก 1 cycle ก่อนคำสั่งถัดไป


async def configure(dut, n, pw, dly):                                           # เขียนค่า N, pw, dly ลงรีจิสเตอร์ของวงจร
    for bit, val in ((UIO_LOAD_ECHO, n & 0xF), (UIO_LOAD_WIDTH, pw & 0xFF),     # คู่ (บิต strobe, ข้อมูล): N ใช้ 4 บิต (& 0xF), pw ใช้ 8 บิต (& 0xFF)
                     (UIO_LOAD_DLO, dly & 0xFF), (UIO_LOAD_DHI, (dly >> 8) & 0xFF)):   # dly 16 บิตแบ่งสองไบต์: ไบต์ต่ำ (& 0xFF) และไบต์สูง (>> 8)
        dut.ui_in.value = val                                                   # วางข้อมูลบน ui_in
        await strobe(dut, bit)                                                  # ยก strobe ของรีจิสเตอร์นั้น 1 cycle เพื่อให้วงจรเก็บค่า
    dut.ui_in.value = 0                                                         # ล้างขาข้อมูลหลังเขียนครบ
    await ClockCycles(dut.clk, 4)                                               # รอ 4 cycle ให้ strobe ตัวสุดท้ายผ่าน synchronizer ครบ


async def pulse_start(dut, hold=1):             # สั่งเริ่มลำดับพัลส์ โดยกด start ค้างไว้ hold cycle (ค่าเริ่มต้น 1)
    dut.uio_in.value = 1 << UIO_START           # ยก start (บิต 4) เป็น 1
    await ClockCycles(dut.clk, hold)            # ค้างไว้ hold cycle
    dut.uio_in.value = 0                        # ปล่อย start


async def capture(dut, max_cycles, stop_when_idle=True):    # จับสัญญาณขาออกทีละ cycle เก็บเป็นรายการ (trace)
    """One sample per clock on the falling edge (settled values)."""   # อ่านค่าที่ขอบขาลง ซึ่งเป็นกลาง cycle ค่าจึงนิ่งแล้ว
    trace, seen_busy, tail = [], False, None                # trace = ผล, seen_busy = เคยเห็น busy แล้วหรือยัง, tail = นับถอยหลังก่อนหยุด
    for _ in range(max_cycles):                             # จับไม่เกิน max_cycles cycle
        await FallingEdge(dut.clk)                          # รอขอบขาลงของนาฬิกา
        d = sample(dut)                                     # อ่านขาออกทุกขา
        trace.append(d)                                     # เก็บลง trace
        seen_busy |= bool(d["busy"])                        # จำไว้ถ้าเคยเห็น seq_busy = 1 (|= คือ OR สะสม)
        if stop_when_idle and seen_busy and not d["busy"] and tail is None:   # ถ้าเคย busy แล้วตอนนี้กลับเป็นว่าง (ลำดับจบ)
            tail = 5                                        # จับต่ออีก 5 cycle เพื่อให้เห็นช่วงหลังจบ (เช่น seq_done)
        if tail is not None:                                # ถ้ากำลังนับถอยหลังอยู่
            tail -= 1                                       # ลดลง 1
            if tail == 0:                                   # ครบแล้ว
                break                                       # หยุดจับ ประหยัดเวลาจำลอง
    return trace                                            # คืนรายการค่าทุก cycle


def check_safety(trace):                                                            # ตรวจกฎความปลอดภัยที่ต้องจริงทุกการทดลอง
    """Rules that must hold in every experiment."""                                 # (กฎที่ต้องเป็นจริงเสมอ)
    for i, d in enumerate(trace):                                                   # ตรวจทุก cycle
        assert not (d["rf"] and d["tr"]), f"RF and RX on together at sample {i}"    # rf_gate กับ tr_switch ห้ามเป็น 1 พร้อมกัน ไม่งั้นพลังงาน RF เข้าภาครับ
        assert d["sine"] == d["rf"], f"sine_en != rf_gate at sample {i}"            # sine_en ต้องเท่ากับ rf_gate ทุก cycle
    for s, l in runs(trace, "rf"):                                                  # วนทุกพัลส์ RF; s = จุดเริ่ม, l = ความกว้าง
        ph = {trace[j]["phase"] for j in range(s, s + l)}                           # รวมค่าเฟสทุก cycle ในพัลส์เป็น set (เก็บค่าไม่ซ้ำ)
        assert len(ph) == 1, f"rf_phase changed inside the pulse at {s}"            # ต้องมีค่าเดียว ถ้ามี 2 ค่าแปลว่าเฟสเปลี่ยนกลางพัลส์ มุมพลิกจะผิด


def analyse(trace, n, pw, dly):                                         # วัดค่าเวลาจาก trace แล้ววางคู่กับค่าที่สูตรทำนาย
    """Measure a CPMG train. Returns a dict of measured values
    (cycles) next to the values the timing formulas predict."""         # (คืน dictionary ค่าที่วัดได้คู่กับค่าตามสูตร หน่วย cycle; แต่ละคีย์ = หนึ่งคอลัมน์ใน CSV)
    rf, tr = runs(trace, "rf"), runs(trace, "tr")                       # ช่วงพัลส์ RF ทุกตัว และช่วงหน้าต่างรับทุกอัน
    busy = runs(trace, "busy")                                          # ช่วงที่ seq_busy = 1
    m = {                                                               # ค่าพื้นฐานที่วัดได้เสมอ
        "N": n, "pw": pw, "dly": dly,                                   # ค่าที่ตั้งให้วงจร บันทึกไว้คู่กับผล
        "rf_pulses": len(rf), "rx_windows": len(tr),                    # จำนวนพัลส์ RF (ควร = N + 1) และจำนวนหน้าต่างรับ (ควร = N)
        "w90": rf[0][1] if rf else 0,                                   # ความกว้างพัลส์แรก (90°) ควร = pw; ถ้าไม่มีพัลส์ให้เป็น 0
        "w180": rf[1][1] if len(rf) > 1 else 0,                         # ความกว้างพัลส์ที่สอง (180° ตัวแรก) ควร = 2·pw
        "rx_len": tr[0][1] if tr else 0,                                # ความยาวหน้าต่างรับอันแรก ควร = 50
        "phase_90": trace[rf[0][0]]["phase"] if rf else -1,             # เฟสของพัลส์ 90° ควร = 0 (แกน x); −1 = ไม่มีพัลส์
        "phase_180": trace[rf[1][0]]["phase"] if len(rf) > 1 else -1,   # เฟสของพัลส์ 180° ควร = 1 (แกน y)
        "busy_len": busy[0][1] if busy else 0,                          # ความยาวลำดับที่วัดได้ (จำนวน cycle ที่ busy = 1)
        "busy_len_expected": expected_cycles(n, pw, dly),               # ความยาวลำดับตามสูตร
        "done_pulses": sum(d["done"] for d in trace),                   # จำนวน cycle ที่ seq_done = 1 ควร = 1
        "cfg_err_while_busy": int(any(d["err"] for d in trace if d["busy"])),   # 1 ถ้า cfg_err เคยเป็น 1 ระหว่างทำงาน ควร = 0
    }                                                                   # ปิด dictionary
    if len(rf) >= 2:                                                    # ค่าเชิงเวลาของ CPMG คำนวณได้เมื่อมีพัลส์อย่างน้อย 2 ตัว
        s90 = rf[0][0]                                                  # cycle ที่พัลส์ 90° เริ่ม
        s180 = [s for s, _ in rf[1:]]                                   # cycle ที่พัลส์ 180° แต่ละตัวเริ่ม (ทุกพัลส์ยกเว้นตัวแรก)
        m["gap_90_180"] = s180[0] - (s90 + pw)                          # ช่องว่างจากปลายพัลส์ 90° ถึงต้นพัลส์ 180° แรก ควร = dly
        sp = [s180[k + 1] - s180[k] for k in range(len(s180) - 1)]      # ระยะห่างระหว่างพัลส์ 180° ที่ติดกันทุกคู่
        m["spacing_180_min"] = min(sp) if sp else ""                    # ระยะห่างที่น้อยที่สุด (เว้นว่างถ้ามี 180° ตัวเดียว)
        m["spacing_180_max"] = max(sp) if sp else ""                    # ระยะห่างที่มากที่สุด; ถ้า min = max แปลว่าสม่ำเสมอ
        m["spacing_180_expected"] = 2 * dly + 3 * pw                    # ระยะห่างตามสูตร CPMG = 2τ = 2·dly + 3·pw
        m["tau_c_measured"] = (2 * s180[0] + 2 * pw - (2 * s90 + pw)) / 2   # τ ที่วัดได้ = กึ่งกลางพัลส์ 180° แรก (s180+pw) − กึ่งกลางพัลส์ 90° (s90+pw/2); คูณ 2 ก่อนเพื่อเลี่ยงเศษ
        m["tau_c_expected"] = dly + 1.5 * pw                            # τ ตามสูตร = dly + 1.5·pw
        offs = []                                                       # ระยะเยื้องระหว่างยอด echo กับกึ่งกลางหน้าต่างรับ
        for k in range(min(len(tr), len(s180))):                        # วนทุก echo ที่มีทั้งพัลส์ 180° และหน้าต่างรับ
            echo2 = 2 * s180[k] + 2 * pw + (2 * dly + 3 * pw)   # 2 x echo peak   (2 × ตำแหน่งยอด echo = 2 × (กึ่งกลางพัลส์ 180° + τ))
            win2 = 2 * tr[k][0] + READOUT_CYCLES                # 2 x window centre   (2 × กึ่งกลางหน้าต่างรับ = 2 × (จุดเริ่ม + 25))
            offs.append((echo2 - win2) / 2)                             # ระยะเยื้อง (cycle) ควรอยู่ระหว่าง 0 ถึง 0.5
        m["rx_offset_min"] = min(offs) if offs else ""                  # ระยะเยื้องที่น้อยที่สุด
        m["rx_offset_max"] = max(offs) if offs else ""                  # ระยะเยื้องที่มากที่สุด
        if tr:                                                          # ถ้ามีหน้าต่างรับ
            m["pre_measured"] = tr[0][0] - (s180[0] + 2 * pw)           # ช่วงรอจากปลายพัลส์ 180° ถึงต้นหน้าต่างรับที่วัดได้
            m["pre_expected"] = (2 * dly + pw - READOUT_CYCLES) // 2    # ตามสูตร pre = ⌊(G − R)/2⌋ (// = หารปัดลง)
        # echo times measured from the centre of the 90 deg pulse   (เวลาของ echo แต่ละตัว นับจากกึ่งกลางพัลส์ 90°)
        c90x2 = 2 * s90 + pw                                            # 2 × กึ่งกลางพัลส์ 90°
        m["echo_times"] = " ".join(str((2 * t + READOUT_CYCLES - c90x2) / 2) for t, _ in tr)   # กึ่งกลางหน้าต่างรับแต่ละอัน − กึ่งกลาง 90° คั่นด้วยช่องว่าง เทียบกับ tₙ = n·2τ
    m["spacing_us"] = round(m.get("spacing_180_expected", 0) * NS_PER_CYCLE_REAL / 1000, 3)   # ระยะห่าง 180° ตามสูตรแปลงเป็น µs ที่ 10 MHz ปัด 3 ตำแหน่ง
    return m                                                            # คืน dictionary ทั้งหมด


async def run_train(dut, n, pw, dly):                                   # รันลำดับพัลส์หนึ่งชุดตั้งแต่เขียนค่าจนจับสัญญาณเสร็จ
    await configure(dut, n, pw, dly)                                    # เขียนค่า N, pw, dly
    await pulse_start(dut)                                              # สั่งเริ่ม
    trace = await capture(dut, expected_cycles(n, pw, dly) + 60)        # จับสัญญาณนานกว่าลำดับที่คาด 60 cycle เผื่อความหน่วง
    check_safety(trace)                                                 # ตรวจกฎความปลอดภัย
    await ClockCycles(dut.clk, 3)                                       # พัก 3 cycle ก่อนรอบถัดไป
    return trace                                                        # คืน trace ให้นำไปวิเคราะห์


# ======================================================================
# E1  pulse_width sweep   (ไล่ค่าความกว้างพัลส์ pw)
# ======================================================================
@cocotb.test()                                          # บอก cocotb ว่าฟังก์ชันถัดไปคือ test หนึ่งตัว
async def e1_pulse_width_sweep(dut):                    # ชื่อ test ขึ้นต้นด้วย e1_ จึงเรียงตามลำดับใน log
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset ทุก test จึงไม่ขึ้นกับ test ก่อนหน้า
    rows = []                                           # เก็บผลแต่ละแถว
    for pw in [1, 2, 5, 10, 20, 50, 100, 200, 255]:     # ค่า pw 9 ค่า ตั้งแต่ต่ำสุด (1) ถึงสูงสุดของรีจิสเตอร์ 8 บิต (255)
        tr = await run_train(dut, 3, pw, 100)           # รันด้วย N = 3, dly = 100 คงที่ เปลี่ยนเฉพาะ pw
        rows.append(analyse(tr, 3, pw, 100))            # วัดค่าแล้วเก็บเป็นหนึ่งแถว
    write_csv("E1_pulse_width_sweep.csv", rows)         # เขียนผลลง CSV
    log_table(dut, "E1 pulse_width sweep (N=3, dly=100)", rows,                     # พิมพ์ตารางสรุปลง log
              ["pw", "w90", "w180", "spacing_180_min", "spacing_180_expected",      # คอลัมน์: pw, ความกว้าง 90°/180°, ระยะห่าง 180° ที่วัด/ตามสูตร
               "rx_offset_max", "busy_len", "busy_len_expected"])                   # ระยะเยื้องหน้าต่างรับ, ความยาวลำดับที่วัด/ตามสูตร


# ======================================================================
# E2  delay_time sweep   (ไล่ค่าช่วงรอ dly)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e2_delay_time_sweep(dut):                     # ชื่อ test E2
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    rows = []                                           # เก็บผล
    for dly in [21, 22, 25, 30, 50, 100, 300, 1000, 5000]:   # เริ่มที่ 21 เพราะ pw = 10 ต้องได้ 2·dly + 10 ≥ 52; ค่าเล็กดูขอบล่าง ค่าใหญ่ดูความเป็นเส้นตรง
        tr = await run_train(dut, 3, 10, dly)           # รันด้วย N = 3, pw = 10 คงที่ เปลี่ยนเฉพาะ dly
        rows.append(analyse(tr, 3, 10, dly))            # วัดค่าแล้วเก็บ
    write_csv("E2_delay_time_sweep.csv", rows)          # เขียนผลลง CSV
    log_table(dut, "E2 delay_time sweep (N=3, pw=10)", rows,                        # พิมพ์ตารางสรุป
              ["dly", "gap_90_180", "pre_measured", "pre_expected",                 # คอลัมน์: dly, ช่องว่าง 90→180, pre ที่วัด/ตามสูตร
               "spacing_180_min", "spacing_180_expected", "rx_offset_max"])         # ระยะห่าง 180° ที่วัด/ตามสูตร, ระยะเยื้องหน้าต่างรับ


# ======================================================================
# E3  echo_count sweep   (ไล่จำนวน echo N)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e3_echo_count_sweep(dut):                     # ชื่อ test E3
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    rows = []                                           # เก็บผล
    for n in range(1, 16):                              # N = 1 ถึง 15 ครบทุกค่าของรีจิสเตอร์ 4 บิต (range หยุดก่อน 16)
        tr = await run_train(dut, n, 5, 40)             # รันด้วย pw = 5, dly = 40 คงที่ เปลี่ยนเฉพาะ N
        rows.append(analyse(tr, n, 5, 40))              # วัดค่าแล้วเก็บ
    write_csv("E3_echo_count_sweep.csv", rows)          # เขียนผลลง CSV
    log_table(dut, "E3 echo_count sweep (pw=5, dly=40)", rows,                      # พิมพ์ตารางสรุป
              ["N", "rf_pulses", "rx_windows", "busy_len", "busy_len_expected",     # คอลัมน์: N, จำนวนพัลส์, จำนวนหน้าต่างรับ, ความยาวลำดับที่วัด/ตามสูตร
               "done_pulses"])                                                      # จำนวนครั้งที่ seq_done เป็น 1


# ======================================================================
# E4  validity boundary and extreme register values
#     (ขอบเขตของค่าที่ใช้ได้ และค่าสุดขั้วของรีจิสเตอร์)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e4_boundaries(dut):                           # ชื่อ test E4
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    cases = [                                           # รายการกรณี: (ชื่อ, N, pw, dly)
        ("G = 50 (below limit)", 1, 2, 24),             # G = 2·24 + 2 = 50 ต่ำกว่าขีด 52 → ควรถูกปฏิเสธ
        ("G = 51 (below limit)", 1, 1, 25),             # G = 51 ต่ำกว่าขีด 1 (ค่าที่ใกล้ที่สุดที่ยังผิด) → ควรถูกปฏิเสธ
        ("G = 52 (limit, even)", 1, 2, 25),             # G = 52 พอดีขีด; G − R = 2 เป็นเลขคู่ → pre = post = 1 → ควรถูกรับ
        ("G = 53 (limit+1, odd)", 1, 1, 26),            # G = 53; G − R = 3 เป็นเลขคี่ → pre = 1, post = 2 → ควรถูกรับ
        ("N = 0", 0, 5, 40),                            # ไม่มี echo ให้ทำ → ควรถูกปฏิเสธ
        ("pw = 0", 2, 0, 40),                           # พัลส์กว้างศูนย์ → ควรถูกปฏิเสธ
        ("dly = 0", 2, 5, 0),                           # ไม่มีช่วงรอ → ควรถูกปฏิเสธ
        ("pw max", 2, 255, 100),                        # pw สูงสุด 255 (พัลส์ 180° กว้าง 510 cycle) → ควรถูกรับ
        ("dly max", 1, 10, 65535),                      # dly สูงสุดของรีจิสเตอร์ 16 บิต ทดสอบว่าตัวนับ 18 บิตไม่ล้น → ควรถูกรับ
        ("N max", 15, 5, 40),                           # N สูงสุด 15 → ควรถูกรับ
    ]                                                   # ปิดรายการ
    rows = []                                           # เก็บผล
    for label, n, pw, dly in cases:                     # วนทุกกรณี แยก tuple เป็นตัวแปร 4 ตัว
        if GATE_LEVEL and dly > 10000:                  # ถ้าจำลองแบบ gate-level และ dly ใหญ่มาก
            rows.append({"case": label, "accepted": "skipped in gate-level run"})   # บันทึกว่าข้ามไป เพราะจำลองระดับเกตช้าเกิน
            continue                                    # ไปกรณีถัดไป
        await configure(dut, n, pw, dly)                # เขียนค่า (ไม่ใช้ run_train เพราะกรณีที่ถูกปฏิเสธต้องจับสัญญาณต่างออกไป)
        await pulse_start(dut)                          # สั่งเริ่ม
        valid = n and pw and dly and 2 * dly + pw >= GAP_MIN   # คำนวณว่ากรณีนี้ "ควร" ถูกรับไหม ตามกฎเดียวกับ config_regs.v
        limit = expected_cycles(n, pw, dly) + 60 if valid else 60   # ถ้าควรรับ จับยาวเท่าลำดับ + 60; ถ้าควรปฏิเสธ จับแค่ 60 cycle
        tr = await capture(dut, limit, stop_when_idle=bool(valid))   # ถ้าควรรับ หยุดเมื่อกลับสู่ IDLE; ถ้าควรปฏิเสธ จับครบ 60 cycle เพื่อยืนยันว่าไม่มีพัลส์หลุด
        check_safety(tr)                                # ตรวจความปลอดภัยทุกกรณี แม้กรณีที่ถูกปฏิเสธ
        r = {"case": label, "accepted": int(any(d["busy"] for d in tr)),   # accepted = 1 ถ้ามี cycle ใดที่ busy = 1 (วงจรรับคำสั่งและทำงาน)
             "cfg_err_after": tr[-1]["err"], "rf_pulses": len(runs(tr, "rf"))}   # cfg_err ใน cycle สุดท้าย (ควร = 1 เมื่อปฏิเสธ) และจำนวนพัลส์ RF (ควร = 0 เมื่อปฏิเสธ)
        if r["accepted"]:                               # ถ้าวงจรรับค่า
            a = analyse(tr, n, pw, dly)                 # วัดค่าเวลาเพิ่ม
            r.update({k: a.get(k, "") for k in          # คัดเฉพาะคอลัมน์ที่สนใจมาใส่ในแถว (a.get(k, "") = เว้นว่างถ้าไม่มีคีย์ เช่น N = 1 ไม่มีระยะห่าง 180°)
                      ("w90", "w180", "pre_measured", "spacing_180_min",
                       "spacing_180_expected", "rx_offset_max", "busy_len")})
        rows.append(r)                                  # เก็บแถว
        await ClockCycles(dut.clk, 3)                   # พัก 3 cycle
    write_csv("E4_boundaries_gl.csv" if GATE_LEVEL else "E4_boundaries.csv", rows)   # แยกชื่อไฟล์ระหว่าง gate-level กับ RTL เพื่อไม่ให้ทับกันและนำมาเทียบได้
    log_table(dut, "E4 boundaries", rows,               # พิมพ์ตารางสรุป
              ["case", "accepted", "cfg_err_after", "rf_pulses"])   # คอลัมน์: กรณี, ถูกรับไหม, cfg_err, จำนวนพัลส์


# ======================================================================
# E5  start-control behaviour   (พฤติกรรมของขา start)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e5_start_control(dut):                        # ชื่อ test E5
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    await configure(dut, 2, 5, 40)                      # ทุกส่วนย่อยใช้ N = 2, pw = 5, dly = 40
    rows = []                                           # เก็บผล

    # (a) latency: cycles from start pin rising to first rf_gate sample
    #     and start length 1, 2, 10, 300 cycles (held)
    #     (ความหน่วงจาก start ขึ้นถึงพัลส์ RF แรก และผลของความยาวการกด start)
    for hold in [1, 2, 10, 300]:                        # กด start ค้าง 1, 2, 10, 300 cycle (300 ยาวกว่าลำดับทั้งชุด)
        dut.uio_in.value = 1 << UIO_START               # ยก start
        tr, first_rf = [], None                         # first_rf = None คือยังไม่เจอพัลส์ RF
        for i in range(expected_cycles(2, 5, 40) + 400):   # จับนานกว่าลำดับ 400 cycle เผื่อกรณีกดค้าง 300
            if i == hold:                               # ครบ hold cycle แล้ว
                dut.uio_in.value = 0                    # ปล่อย start
            await FallingEdge(dut.clk)                  # รอขอบขาลง (อ่านค่ากลาง cycle)
            d = sample(dut)                             # อ่านขาออก
            tr.append(d)                                # เก็บลง trace
            if d["rf"] and first_rf is None:            # เห็น rf_gate = 1 ครั้งแรก
                first_rf = i                            # บันทึก cycle นั้น = latency (รวม synchronizer 2 ชั้น + edge-detect + FSM)
        dut.uio_in.value = 0                            # ปล่อย start (กันกรณีที่ยังค้าง)
        check_safety(tr)                                # ตรวจความปลอดภัย
        rows.append({"experiment": f"start held {hold} cycles",   # ชื่อการทดลองย่อย
                     "latency_start_to_rf": first_rf,   # latency ควรเท่ากันทุกค่า hold
                     "sequences_started": len([1 for s, l in runs(tr, "rf") if l == 5]),   # นับพัลส์กว้าง 5 = พัลส์ 90° = จำนวนลำดับที่เริ่ม ควร = 1 (วงจรจับเฉพาะขอบขาขึ้น)
                     "rf_pulses": len(runs(tr, "rf"))})  # จำนวนพัลส์ RF ทั้งหมด ควร = N + 1 = 3
        await ClockCycles(dut.clk, 5)                   # พัก 5 cycle

    # (b) start again while busy, at several points of the train
    #     (กด start ซ้ำระหว่างที่วงจรกำลังทำงาน ที่หลายจุดในลำดับ)
    for at in [5, 30, 60, 120]:                         # กด start ซ้ำที่ cycle 5, 30, 60, 120 หลังเริ่ม (กระจายไปตามช่วงต่างๆ ของลำดับ)
        await pulse_start(dut)                          # เริ่มลำดับตามปกติ
        tr = []                                         # trace ใหม่
        for i in range(expected_cycles(2, 5, 40) + 60): # จับนานกว่าลำดับ 60 cycle
            dut.uio_in.value = (1 << UIO_START) if i == at else 0   # start = 1 เฉพาะ cycle ที่ i == at (พัลส์ 1 cycle ตอน busy)
            await FallingEdge(dut.clk)                  # รอขอบขาลง
            tr.append(sample(dut))                      # อ่านและเก็บ
        dut.uio_in.value = 0                            # ปล่อย start
        check_safety(tr)                                # ตรวจความปลอดภัย
        rows.append({"experiment": f"extra start at cycle {at} (busy)",   # ชื่อการทดลองย่อย
                     "latency_start_to_rf": "",         # ไม่วัด latency ในส่วนนี้
                     "sequences_started": len([1 for s, l in runs(tr, "rf") if l == 5]),   # ควร = 1: start ระหว่างทำงานต้องถูกเพิกเฉย
                     "rf_pulses": len(runs(tr, "rf"))})  # ควร = 3
        await ClockCycles(dut.clk, 5)                   # พัก 5 cycle

    # (c) ena = 0 blocks start   (ena = 0 ต้องกันไม่ให้เริ่ม)
    dut.ena.value = 0                                   # ปิดขา ena ของ Tiny Tapeout
    await pulse_start(dut)                              # ส่ง start
    tr = await capture(dut, 60, stop_when_idle=False)   # จับครบ 60 cycle โดยไม่หยุดเอง
    rows.append({"experiment": "start with ena = 0", "latency_start_to_rf": "",   # ชื่อการทดลองย่อย
                 "sequences_started": len(runs(tr, "busy")),   # นับช่วงที่ busy = 1 ควร = 0
                 "rf_pulses": len(runs(tr, "rf"))})      # ควร = 0
    dut.ena.value = 1                                   # เปิด ena กลับ
    await ClockCycles(dut.clk, 5)                       # พัก 5 cycle

    # (d) back-to-back: re-start as soon as seq_done is seen
    #     (เริ่มรอบใหม่ทันทีที่เห็น seq_done)
    await pulse_start(dut)                              # เริ่มรอบแรก
    tr, restarted, done_at = [], False, None            # restarted = สั่งรอบสองแล้วหรือยัง, done_at = cycle ที่เห็น done
    for i in range(2 * expected_cycles(2, 5, 40) + 100):   # จับนานพอสำหรับสองรอบ + 100
        await FallingEdge(dut.clk)                      # รอขอบขาลง
        d = sample(dut)                                 # อ่านขาออก
        tr.append(d)                                    # เก็บ
        if d["done"] and not restarted:                 # เห็น seq_done = 1 ครั้งแรก
            done_at = i                                 # บันทึกเวลา
            restarted = True                            # จำว่าสั่งรอบสองแล้ว
            dut.uio_in.value = 1 << UIO_START           # ยก start ทันที เหมือนผู้ใช้ที่รอ done แล้วสั่งต่อ
        elif restarted:                                 # cycle ถัดไปหลังสั่ง
            dut.uio_in.value = 0                        # ปล่อย start (พัลส์ยาว 1 cycle)
    check_safety(tr)                                    # ตรวจความปลอดภัย
    b = runs(tr, "busy")                                # ช่วง busy ทั้งหมด ควรมี 2 ช่วง
    rows.append({"experiment": "restart right after seq_done",   # ชื่อการทดลองย่อย
                 "latency_start_to_rf": "",             # ไม่วัดในส่วนนี้
                 "sequences_started": len(b),           # ควร = 2
                 "rf_pulses": len(runs(tr, "rf")),      # ควร = 6 (สองรอบ รอบละ 3)
                 "idle_gap_between_runs": (b[1][0] - (b[0][0] + b[0][1])) if len(b) > 1 else "",   # เวลาว่างจากปลาย busy แรกถึงต้น busy ที่สอง = เวลาตายขั้นต่ำระหว่างการวัดสองครั้ง (สำคัญเมื่อเฉลี่ยสัญญาณหลายรอบ)
                 "done_at": done_at})                   # cycle ที่เห็น seq_done
    write_csv("E5_start_control.csv", rows)             # เขียน CSV (write_csv รวมคอลัมน์ทุกแถว แถวที่ไม่มีคอลัมน์นั้นเว้นว่าง)
    log_table(dut, "E5 start control", rows,            # พิมพ์ตารางสรุป
              ["experiment", "latency_start_to_rf", "sequences_started", "rf_pulses"])   # คอลัมน์ที่แสดงใน log


# ======================================================================
# E6  reset injected in every FSM state   (กด reset ในทุกสถานะของ FSM)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e6_reset_in_each_state(dut):                  # ชื่อ test E6
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    n, pw, dly = 3, 8, 60          # pre = post = 39 cycles: every state is long   (G = 128, G − 50 = 78 → pre = post = 39 ทุกสถานะยาวพอให้จับได้)

    def reached(state, d, hist):                        # ตัดสินว่าตอนนี้วงจรอยู่ในสถานะ state หรือยัง โดยดูจากขาออกและประวัติ (ชิปไม่มีขาบอกสถานะ)
        rf_runs = runs(hist, "rf")                      # พัลส์ RF ที่ผ่านมาแล้ว
        tr_runs = runs(hist, "tr")                      # หน้าต่างรับที่ผ่านมาแล้ว
        if state == "PULSE_90":                         # สถานะพัลส์ 90°
            return d["rf"] and d["phase"] == 0          # RF เปิดและเฟส = x (0)
        if state == "DELAY_A":                          # ช่วงรอหลัง 90°
            return len(rf_runs) == 1 and not d["rf"] and rf_runs[0][0] + rf_runs[0][1] + 3 <= len(hist)   # ผ่านพัลส์มา 1 ตัว, RF ปิด, และพ้นปลายพัลส์มาแล้ว ≥ 3 cycle (อยู่กลางสถานะจริง)
        if state == "PULSE_180":                        # สถานะพัลส์ 180°
            return d["rf"] and d["phase"] == 1          # RF เปิดและเฟส = y (1)
        if state == "DELAY_B":                          # ช่วงรอหลัง 180° ก่อนหน้าต่างรับ
            return len(rf_runs) == 2 and not d["rf"] and not tr_runs and rf_runs[1][0] + rf_runs[1][1] + 3 <= len(hist)   # ผ่านพัลส์ 2 ตัว, RF ปิด, ยังไม่มีหน้าต่างรับ, พ้นปลายพัลส์ ≥ 3 cycle
        if state == "READOUT":                          # สถานะหน้าต่างรับ
            return d["tr"] and tr_runs and tr_runs[-1][1] >= 5   # tr_switch เปิดมาแล้วอย่างน้อย 5 cycle
        if state == "DELAY_C":                          # ช่วงรอหลังหน้าต่างรับ
            return len(tr_runs) == 1 and not d["tr"] and not d["rf"] and tr_runs[0][0] + tr_runs[0][1] + 3 <= len(hist)   # ผ่านหน้าต่างรับ 1 อัน, RF และ RX ปิด, พ้นปลายหน้าต่าง ≥ 3 cycle
        return False                                    # ชื่อสถานะอื่นคืน False

    rows = []                                           # เก็บผล
    for state in ["PULSE_90", "DELAY_A", "PULSE_180", "DELAY_B", "READOUT", "DELAY_C"]:   # วน 6 สถานะ (ไม่ทดสอบ IDLE เพราะ reset_dut ทำอยู่แล้วทุก test)
        await configure(dut, n, pw, dly)                # เขียนค่าใหม่ทุกรอบ เพราะ reset รอบก่อนล้างรีจิสเตอร์เป็นค่าเริ่มต้นแล้ว
        await pulse_start(dut)                          # สั่งเริ่ม
        hist, hit = [], False                           # hist = ประวัติขาออก, hit = ถึงสถานะเป้าหมายแล้วหรือยัง
        for _ in range(expected_cycles(n, pw, dly) + 60):   # อ่านไม่เกินความยาวลำดับ + 60
            await FallingEdge(dut.clk)                  # รอขอบขาลง
            d = sample(dut)                             # อ่านขาออก
            hist.append(d)                              # เก็บประวัติ
            if reached(state, d, hist):                 # ถึงสถานะเป้าหมาย
                hit = True                              # จำไว้
                break                                   # ออกจากลูปทันทีเพื่อกด reset ตรงนี้
        dut.rst_n.value = 0                             # กด reset ทันที (active-low)
        await Timer(1, unit="ns")                       # รอแค่ 1 ns ไม่ถึงขอบนาฬิกา เพื่อตรวจว่า reset เป็นแบบ asynchronous (ขาออกดับทันที)
        after = sample(dut)                             # อ่านขาออกหลัง reset
        safe = int(not any(after[k] for k in ("rf", "tr", "busy", "phase", "err")))   # safe = 1 ถ้า rf, tr, busy, phase, err เป็น 0 ทั้งหมด
        assert hit, f"state {state} was never reached"  # ถ้าไม่เคยถึงสถานะนั้น test ล้ม (กันกรณีเงื่อนไข reached เขียนผิดแล้วไม่ได้ทดสอบจริง)
        assert safe, f"outputs not safe right after reset in {state}: {after}"   # ถ้าขาออกไม่ปลอดภัย test ล้มพร้อมบอกค่าขาทั้งหมด
        await ClockCycles(dut.clk, 3)                   # ค้าง reset 3 cycle
        dut.rst_n.value = 1                             # ปล่อย reset
        await ClockCycles(dut.clk, 3)                   # รอ 3 cycle
        # after reset the registers are back to defaults (N=1, pw=10, dly=100)   (หลัง reset รีจิสเตอร์กลับเป็นค่าเริ่มต้น)
        await pulse_start(dut)                          # สั่งเริ่มโดยไม่เขียนค่าใหม่
        tr = await capture(dut, expected_cycles(1, 10, 100) + 60)   # จับสัญญาณตามความยาวของค่าเริ่มต้น
        check_safety(tr)                                # ตรวจความปลอดภัย
        a = analyse(tr, 1, 10, 100)                     # วัดค่า เพื่อยืนยันว่าวงจรฟื้นตัวครบทั้ง FSM และรีจิสเตอร์
        rows.append({"reset_in_state": state, "reset_at_sample": len(hist),   # สถานะที่กด reset และ cycle ที่กด
                     "outputs_safe_after_reset": safe,  # ขาออกปลอดภัยไหม (ควร = 1)
                     "next_run_w90": a["w90"], "next_run_w180": a["w180"],   # ความกว้างพัลส์รอบถัดไป ควร = 10 และ 20
                     "next_run_rx_windows": a["rx_windows"]})   # จำนวนหน้าต่างรับรอบถัดไป ควร = 1
        await ClockCycles(dut.clk, 3)                   # พัก 3 cycle
    write_csv("E6_reset_in_each_state.csv", rows)       # เขียน CSV
    log_table(dut, "E6 reset in each state", rows,      # พิมพ์ตารางสรุป
              ["reset_in_state", "outputs_safe_after_reset", "next_run_w90",
               "next_run_rx_windows"])


# ======================================================================
# E7  configuration-interface timing
#     ui_in is changed k cycles after the strobe edge: which byte is
#     stored?  (measured through the 90 deg pulse width)
#     (เปลี่ยน ui_in หลังขอบ strobe ไป k cycle แล้ววงจรเก็บค่าไหน
#      วัดผ่านความกว้างพัลส์ 90° เพราะชิปไม่มีขาอ่านค่ารีจิสเตอร์กลับ)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e7_config_interface_timing(dut):              # ชื่อ test E7
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    await configure(dut, 1, 5, 60)                      # ค่าพื้นฐาน N = 1, pw = 5, dly = 60
    rows = []                                           # เก็บผล
    for k in [0, 1, 2, 3, 4]:                           # เปลี่ยนข้อมูลหลัง strobe 0 ถึง 4 cycle
        # data = 9 together with the strobe, replaced by 30 after k cycles   (วางข้อมูล 9 พร้อม strobe แล้วเปลี่ยนเป็น 30 หลัง k cycle)
        dut.ui_in.value = 9                             # ข้อมูลตัวแรก = 9
        dut.uio_in.value = 1 << UIO_LOAD_WIDTH          # ยก strobe load_width
        for c in range(6):                              # เดิน 6 cycle
            if c == k:                                  # ถึง cycle ที่ k
                dut.ui_in.value = 30                    # เปลี่ยนข้อมูลเป็น 30
            if c == 1:                                  # ที่ cycle 1
                dut.uio_in.value = 0                    # ปล่อย strobe (strobe กว้าง 1 cycle)
            await ClockCycles(dut.clk, 1)               # เดิน 1 cycle
        dut.ui_in.value = 0                             # ล้างข้อมูล
        await ClockCycles(dut.clk, 4)                   # รอ 4 cycle
        await pulse_start(dut)                          # สั่งเริ่ม
        tr = await capture(dut, expected_cycles(1, 30, 60) + 60)   # จับสัญญาณเผื่อกรณีที่ยาวกว่า (pw = 30)
        check_safety(tr)                                # ตรวจความปลอดภัย
        w = runs(tr, "rf")[0][1] if runs(tr, "rf") else 0   # ความกว้างพัลส์แรก = ค่า pw ที่ถูกเก็บจริง
        rows.append({"data_changed_after_cycles": k, "stored_pulse_width": w,   # บันทึก k และค่าที่ถูกเก็บ
                     "byte_kept": "first (9)" if w == 9 else ("second (30)" if w == 30 else "other")})   # ได้ค่าแรก ค่าที่สอง หรือค่าอื่น ("other" = ข้อมูลผสมกัน ไม่ควรเกิด)
        await ClockCycles(dut.clk, 3)                   # พัก 3 cycle
    # order of the two delay bytes: high byte written before low byte   (ลำดับการเขียน delay สองไบต์: เขียนไบต์สูงก่อนไบต์ต่ำ)
    dut.ui_in.value = 0x01                              # ไบต์สูง = 0x01
    await strobe(dut, UIO_LOAD_DHI)                     # เขียนไบต์สูงก่อน (กลับลำดับจาก configure ที่เขียนไบต์ต่ำก่อน)
    dut.ui_in.value = 0x2C                              # ไบต์ต่ำ = 0x2C (= 44)
    await strobe(dut, UIO_LOAD_DLO)                     # เขียนไบต์ต่ำ; รวม 0x012C = 1×256 + 44 = 300
    dut.ui_in.value = 0                                 # ล้างข้อมูล
    await ClockCycles(dut.clk, 4)                       # รอ 4 cycle
    await pulse_start(dut)                              # สั่งเริ่ม
    tr = await capture(dut, expected_cycles(1, 30, 300) + 60)   # จับสัญญาณ
    rf = runs(tr, "rf")                                 # พัลส์ RF ทั้งหมด
    gap = rf[1][0] - (rf[0][0] + rf[0][1]) if len(rf) > 1 else ""   # ช่องว่างจากปลาย 90° ถึงต้น 180° = dly ที่ถูกเก็บจริง ควร = 300
    rows.append({"data_changed_after_cycles": "delay hi then lo (0x012C = 300)",   # แถวพิเศษสำหรับการทดลองนี้
                 "stored_pulse_width": rf[0][1] if rf else "", "byte_kept": f"dly measured {gap}"})   # ความกว้างพัลส์ และค่า dly ที่วัดได้
    write_csv("E7_config_interface_timing.csv", rows)   # เขียน CSV
    log_table(dut, "E7 config interface timing", rows,  # พิมพ์ตารางสรุป
              ["data_changed_after_cycles", "stored_pulse_width", "byte_kept"])


# ======================================================================
# E8  random regression   (สุ่มค่าหลายชุดแล้วตรวจกับสูตร)
# ======================================================================
@cocotb.test()                                          # ประกาศ test
async def e8_random_regression(dut):                    # ชื่อ test E8 (test เดียวที่ตัดสิน pass/fail ตามสูตร)
    await start_clock(dut)                              # เริ่มนาฬิกา
    await reset_dut(dut)                                # reset
    rnd = random.Random(2026)                           # ตัวสุ่มที่มี seed คงที่ 2026 → ได้ค่าชุดเดิมทุกครั้ง ทำซ้ำได้เมื่อหาบั๊ก
    rows, bad = [], 0                                   # rows = ผล, bad = จำนวนชุดที่ไม่ตรงสูตร
    for _ in range(40):                                 # สุ่ม 40 ชุด
        n = rnd.randint(1, 15)                          # N สุ่ม 1–15
        pw = rnd.randint(1, 80)                         # pw สุ่ม 1–80 (ไม่ถึง 255 เพื่อให้จำลองเร็ว ค่าสูงสุดทดสอบแล้วใน E1, E4)
        dly = rnd.randint(max(1, (GAP_MIN - pw + 1) // 2), 400)   # dly สุ่มตั้งแต่ค่าต่ำสุดที่ทำให้ 2·dly + pw ≥ 52 (หารปัดขึ้น) ถึง 400; max(1, …) กัน dly = 0
        tr = await run_train(dut, n, pw, dly)           # รันลำดับ
        a = analyse(tr, n, pw, dly)                     # วัดค่า
        ok = (a["rf_pulses"] == n + 1 and a["rx_windows"] == n            # จำนวนพัลส์ = N + 1 และหน้าต่างรับ = N
              and a["w90"] == pw and a["w180"] == 2 * pw                  # พัลส์ 90° กว้าง pw และ 180° กว้าง 2·pw
              and (n == 1 or a["spacing_180_min"] == a["spacing_180_max"] == 2 * dly + 3 * pw)   # ระยะห่าง 180° สม่ำเสมอและ = 2·dly + 3·pw (N = 1 ไม่มีให้วัดจึงข้าม)
              and 0 <= a["rx_offset_max"] <= 0.5                          # หน้าต่างรับเยื้องจากยอด echo ไม่เกินครึ่ง cycle
              and a["busy_len"] == a["busy_len_expected"]                 # ความยาวลำดับตรงสูตร
              and a["done_pulses"] == 1 and a["cfg_err_while_busy"] == 0)  # seq_done ครั้งเดียว และไม่มี cfg_err ระหว่างทำงาน
        a["matches_formulas"] = int(ok)                 # เพิ่มคอลัมน์ 1 = ตรงสูตร, 0 = ไม่ตรง (กรองใน CSV ได้ง่าย)
        bad += 0 if ok else 1                           # ถ้าไม่ตรง เพิ่มตัวนับ bad
        rows.append(a)                                  # เก็บแถวทุกชุดไม่ว่าตรงหรือไม่
    write_csv("E8_random_regression.csv", rows)         # เขียน CSV (plot_behavior.py ใช้วาดกราฟ E8_measured_vs_predicted.png)
    dut._log.info(f"E8 random regression: {len(rows) - bad}/{len(rows)} runs match the timing formulas")   # พิมพ์สรุป เช่น 40/40 ตรงสูตร
    assert bad == 0, f"{bad} random runs did not match the timing formulas (see E8 CSV)"   # ถ้ามีชุดใดไม่ตรง test ล้ม แต่ CSV ถูกเขียนไว้ก่อนแล้วจึงเปิดดูได้ว่าชุดไหนผิด
