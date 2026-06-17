#!/usr/bin/env python3
"""Create expenses.xlsx with a 30-row personal expenses log."""
import os
import datetime
from openpyxl import Workbook
from openpyxl.styles import Font

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "expenses.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Expenses"

bold = Font(bold=True)
headers = ["Date", "Category", "Description", "Amount"]
for col, h in enumerate(headers, start=1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = bold

rows = [
    ("2025-01-02", "Food",          "Coffee shop",   45),
    ("2025-01-03", "Transport",     "Metro pass",    80),
    ("2025-01-04", "Utilities",     "Electricity",   120),
    ("2025-01-05", "Entertainment", "Movie",         50),
    ("2025-01-06", "Health",        "Prescription",  100),
    ("2025-01-07", "Food",          "Groceries",     60),
    ("2025-01-08", "Transport",     "Taxi",          60),
    ("2025-01-09", "Utilities",     "Internet",      90),
    ("2025-01-10", "Entertainment", "Concert",       35),
    ("2025-01-11", "Health",        "Doctor visit",  85),
    ("2025-01-12", "Food",          "Restaurant",    35),
    ("2025-01-13", "Transport",     "Uber",          40),
    ("2025-01-14", "Utilities",     "Water bill",    75),
    ("2025-01-15", "Entertainment", "Books",         20),
    ("2025-01-16", "Health",        "Gym",           120),
    ("2025-01-17", "Food",          "Snacks",        25),
    ("2025-01-18", "Transport",     "Gas",           30),
    ("2025-01-19", "Utilities",     "Gas bill",      60),
    ("2025-01-20", "Entertainment", "Streaming",     25),
    ("2025-01-21", "Health",        "Pharmacy",      65),
    ("2025-01-22", "Food",          "Bakery",        55),
    ("2025-01-23", "Entertainment", "Theater",       15),
    ("2025-01-24", "Health",        "Dentist",       55),
    ("2025-01-25", "Food",          "Dinner",        40),
    ("2025-01-26", "Entertainment", "Board games",   30),
    ("2025-01-27", "Health",        "Blood test",    85),
    ("2025-01-28", "Entertainment", "Spa",           55),
    ("2025-01-29", "Health",        "Chiropractor",  40),
    ("2025-01-30", "Entertainment", "Gym class",     40),
    ("2025-01-31", "Health",        "Supplements",   80),
]

for i, (date_str, cat, desc, amount) in enumerate(rows, start=2):
    d = datetime.date.fromisoformat(date_str)
    ws.cell(row=i, column=1, value=d)
    ws.cell(row=i, column=2, value=cat)
    ws.cell(row=i, column=3, value=desc)
    ws.cell(row=i, column=4, value=amount)

ws.column_dimensions["A"].width = 12
ws.column_dimensions["B"].width = 14
ws.column_dimensions["C"].width = 18
ws.column_dimensions["D"].width = 10

wb.save(OUTPUT)
print(f"Created {OUTPUT}")

# Sanity checks
from openpyxl import load_workbook
wb2 = load_workbook(OUTPUT)
ws2 = wb2["Expenses"]
assert ws2["A1"].value == "Date"
assert ws2["A1"].font.bold is True
cat_totals = {}
for r in range(2, 32):
    cat = ws2.cell(row=r, column=2).value
    amt = ws2.cell(row=r, column=4).value
    cat_totals[cat] = cat_totals.get(cat, 0) + amt
assert cat_totals == {"Food": 260, "Transport": 210, "Utilities": 345, "Entertainment": 270, "Health": 630}, cat_totals
assert sum(cat_totals.values()) == 1715
print("Sanity checks passed.")
