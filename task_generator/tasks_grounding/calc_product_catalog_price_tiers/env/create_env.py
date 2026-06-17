#!/usr/bin/env python3
"""Create catalog.xlsx with two sheets: Catalog (25 products) and Tiers (discount tiers)."""
import os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "catalog.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Catalog"
bold = Font(bold=True)

for col, h in enumerate(["SKU", "Product", "Units Sold", "List Price"], start=1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = bold

# Each row is (SKU, Product, Units, Price). Units chosen to hit every tier.
catalog_rows = [
    ("SKU001", "Widget A",  50,   20.0),
    ("SKU002", "Widget B",  80,   30.0),
    ("SKU003", "Gadget A", 150,   25.0),
    ("SKU004", "Gadget B", 200,   40.0),
    ("SKU005", "Gadget C", 350,   15.0),
    ("SKU006", "Tool A",   550,  100.0),
    ("SKU007", "Tool B",   700,   80.0),
    ("SKU008", "Tool C",   900,   50.0),
    ("SKU009", "Part A",  1200,   10.0),
    ("SKU010", "Part B",  1500,    8.0),
    ("SKU011", "Widget C",  30,   25.0),
    ("SKU012", "Gadget D", 250,   35.0),
    ("SKU013", "Tool D",   600,   90.0),
    ("SKU014", "Part C",  2000,    5.0),
    ("SKU015", "Widget D",  90,   15.0),
    ("SKU016", "Gadget E", 400,   30.0),
    ("SKU017", "Tool E",   800,   70.0),
    ("SKU018", "Part D",  1800,    6.0),
    ("SKU019", "Widget E",  70,   18.0),
    ("SKU020", "Gadget F", 300,   22.0),
    ("SKU021", "Tool F",   650,   85.0),
    ("SKU022", "Part E",  1100,   12.0),
    ("SKU023", "Widget F",  95,   12.0),
    ("SKU024", "Tool G",   750,   75.0),
    ("SKU025", "Gadget G", 450,   28.0),
]

for i, row in enumerate(catalog_rows, start=2):
    for col, val in enumerate(row, start=1):
        ws.cell(row=i, column=col, value=val)

for col, w in zip("ABCD", [10, 12, 12, 12]):
    ws.column_dimensions[col].width = w

# Tiers sheet
ws2 = wb.create_sheet("Tiers")
for col, h in enumerate(["Min Units", "Tier", "Discount"], start=1):
    c = ws2.cell(row=1, column=col, value=h)
    c.font = bold

tiers = [
    (0,    "Bronze",   0.0),
    (100,  "Silver",   0.05),
    (500,  "Gold",     0.10),
    (1000, "Platinum", 0.15),
]
for i, (mn, tier, disc) in enumerate(tiers, start=2):
    ws2.cell(row=i, column=1, value=mn)
    ws2.cell(row=i, column=2, value=tier)
    ws2.cell(row=i, column=3, value=disc)

for col, w in zip("ABC", [12, 12, 12]):
    ws2.column_dimensions[col].width = w

wb.save(OUTPUT)
print(f"Created {OUTPUT}")

# --- Sanity checks ---
wb2 = load_workbook(OUTPUT)
assert "Catalog" in wb2.sheetnames and "Tiers" in wb2.sheetnames
cat = wb2["Catalog"]

def tier_for(units):
    if units >= 1000: return ("Platinum", 0.15)
    if units >= 500:  return ("Gold", 0.10)
    if units >= 100:  return ("Silver", 0.05)
    return ("Bronze", 0.0)

totals = {"Bronze": 0.0, "Silver": 0.0, "Gold": 0.0, "Platinum": 0.0}
for r in range(2, 27):
    units = cat.cell(row=r, column=3).value
    price = cat.cell(row=r, column=4).value
    tier, disc = tier_for(units)
    revenue = units * price * (1 - disc)
    totals[tier] += revenue

assert totals["Bronze"] == 7900.0, totals["Bronze"]
assert totals["Silver"] == 54102.5, totals["Silver"]
assert totals["Gold"] == 339750.0, totals["Gold"]
assert totals["Platinum"] == 49300.0, totals["Platinum"]
# Spot-check specific rows referenced by the task verification
# Row 2: SKU001 (50 units, $20) -> Bronze, disc 0 -> price 20, revenue 1000
# Row 7: SKU006 (550 units, $100) -> Gold, disc 0.1 -> price 90, revenue 49500
# Row 10: SKU009 (1200 units, $10) -> Platinum, disc 0.15 -> price 8.5, revenue 10200
print("Sanity checks passed.")
