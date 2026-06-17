#!/usr/bin/env python3
"""Create timesheet.xlsx with 10 employees and their daily hours + rates."""
import os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "timesheet.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Timesheet"

bold = Font(bold=True)
headers = ["Employee", "Mon", "Tue", "Wed", "Thu", "Fri", "Hourly Rate"]
for col, h in enumerate(headers, start=1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = bold

# (name, mon, tue, wed, thu, fri, rate)
rows = [
    ("Alice",  8,  8,  8,  8,  8, 20),   # 40h total
    ("Bob",   10, 10, 10, 10, 10, 25),   # 50h total (10 OT)
    ("Carol",  6,  8,  8,  8,  8, 22),   # 38h total
    ("Dan",    9,  9,  9,  9,  9, 30),   # 45h total (5 OT)
    ("Eve",    7,  7,  7,  7,  7, 18),   # 35h total
    ("Frank", 12, 12, 12,  8,  8, 24),   # 52h total (12 OT)
    ("Grace",  8,  8,  4,  8,  8, 28),   # 36h total
    ("Henry", 10, 10,  8,  8,  8, 26),   # 44h total (4 OT)
    ("Iris",   8,  8,  8,  8,  8, 32),   # 40h total
    ("Jack",  11, 11, 11,  9,  8, 21),   # 50h total (10 OT)
]

for i, row in enumerate(rows, start=2):
    for col, val in enumerate(row, start=1):
        ws.cell(row=i, column=col, value=val)

# Column widths for readability
for col, w in zip("ABCDEFG", [12, 6, 6, 6, 6, 6, 14]):
    ws.column_dimensions[col].width = w

wb.save(OUTPUT)
print(f"Created {OUTPUT}")

# --- Sanity checks ---
wb2 = load_workbook(OUTPUT)
ws2 = wb2["Timesheet"]
assert ws2["A1"].value == "Employee" and ws2["A1"].font.bold
total_hours = []
for r in range(2, 12):
    h = sum(ws2.cell(row=r, column=c).value for c in range(2, 7))
    total_hours.append(h)
assert total_hours == [40, 50, 38, 45, 35, 52, 36, 44, 40, 50], total_hours
# Regular / OT / Gross
reg = [min(h, 40) for h in total_hours]
ot  = [max(0, h - 40) for h in total_hours]
rates = [20, 25, 22, 30, 18, 24, 28, 26, 32, 21]
gross = [reg[i]*rates[i] + ot[i]*rates[i]*1.5 for i in range(10)]
assert sum(total_hours) == 430
assert sum(reg) == 389
assert sum(ot) == 41
assert sum(gross) == 11097, sum(gross)
print("Sanity checks passed.")
