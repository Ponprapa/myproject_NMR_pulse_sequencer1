"""
Plot the CSV files written by test_behavior.py.
  (วาดกราฟจากไฟล์ CSV ที่ test_behavior.py เขียนไว้)

Usage (from the test/ folder, after `make` or after unzipping the
GitHub `test-results` artifact):
    python plot_behavior.py            # reads ./output, writes ./output/*.png
    python plot_behavior.py path/to/output
  (วิธีใช้: เปิด terminal ในโฟลเดอร์ test/ หลังรัน make หรือหลังแตกไฟล์ zip
   ของ artifact test-results ที่ดาวน์โหลดจาก GitHub
     python plot_behavior.py                  → อ่าน CSV จาก ./output แล้วเขียนรูป .png ลงที่เดียวกัน
     python plot_behavior.py path/to/output   → ระบุโฟลเดอร์ที่เก็บ CSV เอง)

Needs matplotlib (pip install matplotlib). Times on the secondary axes
assume the 10 MHz clock from info.yaml (1 cycle = 100 ns).
  (ต้องติดตั้ง matplotlib ก่อน: pip install matplotlib
   แกน y ด้านขวาของกราฟแปลง cycle เป็นเวลาจริง โดยถือว่านาฬิกา 10 MHz ตาม info.yaml คือ 1 cycle = 100 ns)
"""

import csv                      # โมดูลมาตรฐานสำหรับอ่านไฟล์ CSV
import os                       # ใช้จัดการ path ของไฟล์และโฟลเดอร์
import sys                      # ใช้อ่านอาร์กิวเมนต์ที่พิมพ์ต่อท้ายคำสั่ง (sys.argv)

import matplotlib               # ไลบรารีวาดกราฟ
matplotlib.use("Agg")           # เลือก backend "Agg" = วาดลงไฟล์รูปโดยไม่เปิดหน้าต่าง ใช้ได้บนเครื่องที่ไม่มีจอ เช่น GitHub Actions; ต้องเรียกก่อน import pyplot
import matplotlib.pyplot as plt # ส่วนของ matplotlib ที่ใช้สร้างรูปและแกน ตั้งชื่อย่อว่า plt

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")   # โฟลเดอร์ข้อมูล: ถ้าพิมพ์ path ต่อท้ายคำสั่งใช้ path นั้น (sys.argv[1]) ไม่งั้นใช้ output ที่อยู่ข้างไฟล์นี้
US_PER_CYCLE = 0.1              # 1 cycle = 0.1 µs (= 100 ns) ที่ 10 MHz ใช้แปลงหน่วยบนแกนขวา


def load(name):                                     # อ่านไฟล์ CSV ชื่อ name คืนเป็นรายการแถว
    path = os.path.join(OUT, name)                  # path เต็มของไฟล์
    if not os.path.exists(path):                    # ถ้าไม่มีไฟล์ (เช่น การทดลองนั้นยังไม่ได้รัน)
        print(f"skip: {name} not found")            # แจ้งว่าข้าม
        return None                                 # คืน None ให้ส่วนที่เรียกข้ามกราฟนั้นไป ไม่ทำให้โปรแกรมหยุด
    with open(path, newline="") as f:               # เปิดไฟล์อ่าน
        return list(csv.DictReader(f))              # อ่านทุกแถวเป็น dictionary โดยใช้แถวหัวตารางเป็นชื่อคีย์ (ค่าทุกช่องเป็นข้อความ)


def num(rows, key):                                 # ดึงคอลัมน์ key จากทุกแถวแล้วแปลงเป็นตัวเลข
    return [float(r[key]) for r in rows]            # CSV เก็บเป็นข้อความ จึงต้อง float() ก่อนนำไปวาดกราฟ


def add_us_axis(ax):                                # เพิ่มแกน y ด้านขวาที่แสดงเวลาจริงเป็น µs
    sec = ax.secondary_yaxis("right", functions=(lambda c: c * US_PER_CYCLE, lambda u: u / US_PER_CYCLE))   # แกนรองด้านขวา; ฟังก์ชันแรกแปลง cycle → µs (× 0.1) ฟังก์ชันที่สองแปลงกลับ µs → cycle (÷ 0.1)
    sec.set_ylabel("time at 10 MHz (µs)")           # ชื่อแกนขวา: เวลาที่ 10 MHz (µs)


def save(fig, name):                                # บันทึกรูปลงไฟล์
    fig.tight_layout()                              # จัดระยะขอบให้ชื่อแกนและหัวเรื่องไม่ถูกตัด
    path = os.path.join(OUT, name)                  # path ของไฟล์รูป (อยู่โฟลเดอร์เดียวกับ CSV)
    fig.savefig(path, dpi=200)                      # บันทึกเป็น PNG ความละเอียด 200 dpi (คมพอใส่รายงาน)
    plt.close(fig)                                  # ปิดรูปเพื่อคืนหน่วยความจำ
    print("wrote", path)                            # แจ้งว่าเขียนไฟล์ไหนแล้ว


# E1: 180-degree spacing vs pulse width ------------------------------   (E1: ระยะห่างพัลส์ 180° เทียบกับความกว้างพัลส์)
rows = load("E1_pulse_width_sweep.csv")             # อ่านผลการทดลอง E1
if rows:                                            # วาดเฉพาะเมื่อมีไฟล์และมีข้อมูล
    pw = num(rows, "pw")                            # ค่า pw ทุกแถว ใช้เป็นแกน x
    fig, ax = plt.subplots(figsize=(6, 4))          # สร้างรูปขนาด 6 × 4 นิ้ว มีแกนเดียว
    ax.plot(pw, num(rows, "spacing_180_expected"), "-", color="0.6", label="theory: 2·dly + 3·pw")   # เส้นทฤษฎี (เส้นทึบสีเทา "0.6") ระยะห่าง = 2·dly + 3·pw
    ax.plot(pw, num(rows, "spacing_180_min"), "o", label="measured (simulation)")   # จุดวงกลม = ค่าที่วัดได้จากการจำลอง; ถ้าจุดอยู่บนเส้นแปลว่าวงจรตรงสูตร
    ax.set_xlabel("pulse_width, pw (cycles)")       # ชื่อแกน x
    ax.set_ylabel("180° pulse spacing (cycles)")    # ชื่อแกน y
    ax.set_title("E1: 180° spacing vs pulse width (N = 3, dly = 100)")   # หัวเรื่อง ระบุค่าที่ตรึงไว้
    ax.legend()                                     # แสดงคำอธิบายสัญลักษณ์ (จาก label)
    add_us_axis(ax)                                 # เพิ่มแกนขวาเป็น µs
    save(fig, "E1_spacing_vs_pw.png")               # บันทึกรูป

    fig, ax = plt.subplots(figsize=(6, 4))          # รูปที่สองของ E1
    ax.plot(pw, num(rows, "w90"), "o-", label="90° pulse")      # ความกว้างพัลส์ 90° ที่วัดได้ (จุด + เส้น) ควรเป็นเส้นตรงความชัน 1
    ax.plot(pw, num(rows, "w180"), "s-", label="180° pulse")    # ความกว้างพัลส์ 180° (สี่เหลี่ยม + เส้น) ควรเป็นเส้นตรงความชัน 2
    ax.set_xlabel("pulse_width, pw (cycles)")       # ชื่อแกน x
    ax.set_ylabel("measured rf_gate width (cycles)")   # ชื่อแกน y: ความกว้าง rf_gate ที่วัดได้
    ax.set_title("E1: measured pulse widths")       # หัวเรื่อง
    ax.legend()                                     # แสดงคำอธิบายสัญลักษณ์
    add_us_axis(ax)                                 # เพิ่มแกนขวาเป็น µs
    save(fig, "E1_pulse_widths.png")                # บันทึกรูป

# E2: 180-degree spacing and pre-readout wait vs delay time -----------   (E2: ระยะห่างพัลส์ 180° เทียบกับช่วงรอ dly)
rows = load("E2_delay_time_sweep.csv")              # อ่านผลการทดลอง E2
if rows:                                            # วาดเมื่อมีข้อมูล
    dly = num(rows, "dly")                          # ค่า dly ทุกแถว ใช้เป็นแกน x
    fig, ax = plt.subplots(figsize=(6, 4))          # สร้างรูป
    ax.plot(dly, num(rows, "spacing_180_expected"), "-", color="0.6", label="theory: 2·dly + 3·pw")   # เส้นทฤษฎี
    ax.plot(dly, num(rows, "spacing_180_min"), "o", label="measured (simulation)")   # จุดที่วัดได้
    ax.set_xscale("log")                            # แกน x แบบลอการิทึม เพราะ dly กว้างตั้งแต่ 21 ถึง 5000
    ax.set_yscale("log")                            # แกน y แบบลอการิทึมด้วย ค่าเล็กและค่าใหญ่จึงเห็นชัดในรูปเดียว
    ax.set_xlabel("delay_time, dly (cycles)")       # ชื่อแกน x
    ax.set_ylabel("180° pulse spacing (cycles)")    # ชื่อแกน y
    ax.set_title("E2: 180° spacing vs delay time (N = 3, pw = 10)")   # หัวเรื่อง
    ax.legend()                                     # แสดงคำอธิบายสัญลักษณ์ (ไม่เพิ่มแกน µs เพราะแกนลอการิทึม)
    save(fig, "E2_spacing_vs_dly.png")              # บันทึกรูป

# E3: sequence length and echo times vs echo count --------------------   (E3: ความยาวลำดับและเวลา echo เทียบกับจำนวน echo)
rows = load("E3_echo_count_sweep.csv")              # อ่านผลการทดลอง E3
if rows:                                            # วาดเมื่อมีข้อมูล
    n = num(rows, "N")                              # ค่า N ทุกแถว (1 ถึง 15) ใช้เป็นแกน x
    fig, ax = plt.subplots(figsize=(6, 4))          # สร้างรูป
    ax.plot(n, num(rows, "busy_len_expected"), "-", color="0.6", label="theory: pw + dly + N·(3pw + 2dly)")   # เส้นทฤษฎีของความยาวลำดับ เป็นเส้นตรงที่ชัน 3pw + 2dly
    ax.plot(n, num(rows, "busy_len"), "o", label="measured seq_busy length")   # จุด = ความยาวที่ seq_busy เป็น 1 จริง
    ax.set_xlabel("echo_count, N")                  # ชื่อแกน x
    ax.set_ylabel("sequence length (cycles)")       # ชื่อแกน y
    ax.set_title("E3: sequence length vs echo count (pw = 5, dly = 40)")   # หัวเรื่อง
    ax.legend()                                     # แสดงคำอธิบายสัญลักษณ์
    add_us_axis(ax)                                 # เพิ่มแกนขวาเป็น µs
    save(fig, "E3_length_vs_N.png")                 # บันทึกรูป

    last = rows[-1]                                 # ใช้แถวสุดท้าย คือ N = 15 ซึ่งมี echo มากที่สุด
    t = [float(x) for x in last["echo_times"].split()]   # แยกข้อความ echo_times ที่คั่นด้วยช่องว่างออกเป็นตัวเลข = เวลากึ่งกลางหน้าต่างรับแต่ละอัน
    k = list(range(1, len(t) + 1))                  # หมายเลข echo n = 1, 2, …, N ใช้เป็นแกน x
    spacing = float(last["spacing_180_expected"])   # 2τ ตามสูตร (= ระยะห่าง 180°)
    fig, ax = plt.subplots(figsize=(6, 4))          # สร้างรูป
    ax.plot(k, [i * spacing for i in k], "-", color="0.6", label="theory: tₙ = n·2τ")   # เส้นทฤษฎี: echo ตัวที่ n เกิดที่เวลา n·2τ หลังกึ่งกลางพัลส์ 90°
    ax.plot(k, t, "o", label="readout-window centre (simulation)")   # จุด = กึ่งกลางหน้าต่างรับที่วัดได้
    ax.set_xlabel("echo number n")                  # ชื่อแกน x
    ax.set_ylabel("time from centre of 90° pulse (cycles)")   # ชื่อแกน y: เวลานับจากกึ่งกลางพัลส์ 90°
    ax.set_title(f"E3: echo times, N = {int(float(last['N']))}")   # หัวเรื่องระบุ N (แปลง "15" → 15.0 → 15)
    ax.legend()                                     # แสดงคำอธิบายสัญลักษณ์
    add_us_axis(ax)                                 # เพิ่มแกนขวาเป็น µs
    save(fig, "E3_echo_times.png")                  # บันทึกรูป

# E8: random regression, measured vs predicted spacing ---------------   (E8: ค่าสุ่ม เทียบระยะห่างที่วัดได้กับที่ทำนาย)
rows = load("E8_random_regression.csv")             # อ่านผลการทดลอง E8
if rows:                                            # วาดเมื่อมีข้อมูล
    rows = [r for r in rows if r["spacing_180_min"] != ""]   # ตัดแถวที่ N = 1 ออก เพราะมีพัลส์ 180° ตัวเดียว ไม่มีระยะห่างให้วัด (ช่องว่าง)
    fig, ax = plt.subplots(figsize=(5, 5))          # รูปจัตุรัส 5 × 5 นิ้ว ให้เส้นทแยงมุมเอียง 45° จริง
    e = num(rows, "spacing_180_expected")           # ระยะห่างตามสูตรของแต่ละชุด
    ax.plot([0, max(e)], [0, max(e)], "-", color="0.6", label="measured = predicted")   # เส้นทแยง y = x: จุดที่อยู่บนเส้นนี้แปลว่าวัดได้ตรงกับที่ทำนาย
    ax.plot(e, num(rows, "spacing_180_min"), "o", label=f"{len(rows)} random settings")   # จุดของแต่ละชุดสุ่ม (x = ทำนาย, y = วัดได้) label บอกจำนวนชุด
    ax.set_xlabel("predicted spacing 2·dly + 3·pw (cycles)")   # ชื่อแกน x
    ax.set_ylabel("measured spacing (cycles)")      # ชื่อแกน y
    ax.set_title("E8: random settings")             # หัวเรื่อง
    ax.legend()                                     # แสดงคำอธิบายสัญลักษณ์
    save(fig, "E8_measured_vs_predicted.png")       # บันทึกรูป
