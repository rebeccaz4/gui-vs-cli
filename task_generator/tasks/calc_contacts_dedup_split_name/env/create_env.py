#!/usr/bin/env python3
"""Create contacts.xlsx with 25 rows where several emails need cleanup and some are duplicates."""
import os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "contacts.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Contacts"

bold = Font(bold=True)
headers = ["Full Name", "Email", "Phone"]
for col, h in enumerate(headers, start=1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = bold

# (Full Name, Email (raw, possibly with case/whitespace issues), Phone)
# Rows are indexed 2..26.
rows = [
    ("John Smith",      "JOHN@example.com",   "555-0101"),  # 2 - unique
    ("Jane Doe",        "jane@example.com",   "555-0102"),  # 3 - DUP cluster (rows 3, 22, 26)
    ("Bob Smith",       "bob@example.com  ",  "555-0103"),  # 4 - DUP cluster (rows 4, 23)
    ("Alice Brown",     "alice@Example.com",  "555-0104"),
    ("Mark Lee",        "mark@example.com",   "555-0105"),
    ("Sarah Miller",    "SARAH@example.com",  "555-0106"),
    ("Tom Johnson",     "tom@example.com",    "555-0107"),
    ("Lisa Wilson",     "lisa@example.com   ","555-0108"),
    ("Ryan Davis",      "ryan@example.com",   "555-0109"),
    ("Emma Garcia",     "emma@example.com",   "555-0110"),
    ("Luke Martinez",   "luke@example.com",   "555-0111"),
    ("Nora Rodriguez",  "NORA@example.com",   "555-0112"),
    ("Evan Hernandez",  "evan@example.com",   "555-0113"),
    ("Carla Lopez",     "carla@example.com",  "555-0114"),
    ("Owen Gonzalez",   "OWEN@example.com",   "555-0115"),  # 16
    ("Ruby Perez",      "ruby@example.com",   "555-0116"),
    ("Max Sanchez",     "max@example.com",    "555-0117"),
    ("Mia Torres",      "mia@example.com",    "555-0118"),
    ("Noah Ramirez",    "noah@example.com",   "555-0119"),
    ("Ella Hill",       "ella@example.com ",  "555-0120"),
    ("Jane Doe",        "jane@example.com",   "555-0121"),  # 22 - duplicate email (Jane)
    ("Bob Smith",       "BOB@example.com",    "555-0122"),  # 23 - duplicate (Bob), raw uppercase
    ("Sam King",        "sam@example.com",    "555-0123"),  # 24 - unique
    ("Iris Wright",     "iris@example.com",   "555-0124"),  # 25 - unique
    ("Jane Doe",        "JANE@Example.com",   "555-0125"),  # 26 - third Jane
]

assert len(rows) == 25

for i, (full, email, phone) in enumerate(rows, start=2):
    ws.cell(row=i, column=1, value=full)
    ws.cell(row=i, column=2, value=email)
    ws.cell(row=i, column=3, value=phone)

for col, w in zip("ABC", [22, 28, 14]):
    ws.column_dimensions[col].width = w

wb.save(OUTPUT)
print(f"Created {OUTPUT}")

# --- Sanity checks ---
wb2 = load_workbook(OUTPUT)
ws2 = wb2["Contacts"]
assert ws2["A1"].value == "Full Name" and ws2["A1"].font.bold
# Confirm known rows
assert ws2.cell(row=2, column=1).value == "John Smith"
assert ws2.cell(row=3, column=1).value == "Jane Doe"
assert ws2.cell(row=22, column=1).value == "Jane Doe"
assert ws2.cell(row=23, column=1).value == "Bob Smith"
# Count clean-email duplicates exactly as the verification expects
clean = [(ws2.cell(row=r, column=2).value or "").strip().lower() for r in range(2, 27)]
from collections import Counter
cnt = Counter(clean)
# jane appears 3 times, bob appears 2 times
assert cnt["jane@example.com"] == 3, cnt
assert cnt["bob@example.com"] == 2, cnt
print("Sanity checks passed.")
