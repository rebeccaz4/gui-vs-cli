#!/usr/bin/env python3
"""Create roster.xlsx with 25 students and three exam scores each.
Scores are chosen so weighted finals spread across A/B/C/D/F bands cleanly."""
import os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "roster.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Roster"

bold = Font(bold=True)
for col, h in enumerate(["Student ID", "Name", "Exam1", "Exam2", "Exam3"], start=1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = bold

# (sid, name, e1, e2, e3)   final = 0.3*e1+0.3*e2+0.4*e3
rows = [
    ("S01", "Alice",    95, 92, 98),  # 95.3 A
    ("S02", "Bob",      88, 85, 90),  # 87.9 B
    ("S03", "Carol",    75, 80, 72),  # 75.3 C
    ("S04", "Dan",      92, 95, 90),  # 92.1 A
    ("S05", "Eve",      60, 65, 58),  # 60.7 D
    ("S06", "Frank",    72, 68, 75),  # 72.0 C
    ("S07", "Grace",    82, 78, 85),  # 82.0 B
    ("S08", "Henry",    55, 50, 45),  # 49.5 F
    ("S09", "Iris",     90, 88, 92),  # 90.2 A
    ("S10", "Jack",     65, 70, 62),  # 65.3 D
    ("S11", "Kate",     85, 88, 80),  # 83.9 B
    ("S12", "Leo",      75, 72, 78),  # 75.3 C
    ("S13", "Mia",      95, 98, 94),  # 95.5 A
    ("S14", "Nick",     40, 45, 50),  # 45.5 F
    ("S15", "Olivia",   80, 82, 85),  # 82.6 B
    ("S16", "Paul",     62, 65, 68),  # 65.3 D
    ("S17", "Quinn",    77, 75, 72),  # 74.4 C
    ("S18", "Ryan",     85, 88, 82),  # 84.7 B
    ("S19", "Sam",      92, 90, 95),  # 92.6 A
    ("S20", "Tara",     55, 60, 52),  # 55.3 F
    ("S21", "Uma",      78, 75, 80),  # 77.9 C
    ("S22", "Vic",      68, 70, 72),  # 70.2 C
    ("S23", "Will",     85, 82, 78),  # 81.3 B
    ("S24", "Xia",      65, 68, 62),  # 64.7 D
    ("S25", "Yolanda",  88, 85, 80),  # 83.9 B
]

for i, row in enumerate(rows, start=2):
    for col, val in enumerate(row, start=1):
        ws.cell(row=i, column=col, value=val)

for col, w in zip("ABCDE", [12, 14, 8, 8, 8]):
    ws.column_dimensions[col].width = w

wb.save(OUTPUT)
print(f"Created {OUTPUT}")

# --- Sanity checks ---
wb2 = load_workbook(OUTPUT)
ws2 = wb2["Roster"]
finals = []
for r in range(2, 27):
    e1, e2, e3 = (ws2.cell(row=r, column=c).value for c in (3, 4, 5))
    finals.append(round(e1*0.3 + e2*0.3 + e3*0.4, 10))

def band(f):
    if f >= 90: return "A"
    if f >= 80: return "B"
    if f >= 70: return "C"
    if f >= 60: return "D"
    return "F"

from collections import Counter
counts = Counter(band(f) for f in finals)
assert counts["A"] == 5 and counts["B"] == 7 and counts["C"] == 6 and counts["D"] == 4 and counts["F"] == 3, counts
# Spot-check specific values
assert abs(finals[0] - 95.3) < 1e-6        # Alice
assert abs(finals[7] - 49.5) < 1e-6        # Henry
assert abs(finals[12] - 95.5) < 1e-6       # Mia
print("Sanity checks passed.")
