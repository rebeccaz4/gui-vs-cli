#!/usr/bin/env python3
"""Create annual_draft.pptx: a 5-slide draft that the agent will restructure."""
import os
from pptx import Presentation

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "annual_draft.pptx")

prs = Presentation()

# 1. Title slide
s1 = prs.slides.add_slide(prs.slide_layouts[0])
s1.shapes.title.text = "Annual Report 2025"
s1.placeholders[1].text = "Leadership team debrief"

# 2. Financials
s2 = prs.slides.add_slide(prs.slide_layouts[1])
s2.shapes.title.text = "Financials"
body2 = s2.placeholders[1].text_frame
body2.text = "Revenue up 24% YoY"
body2.add_paragraph().text = "Gross margin at 62%"
body2.add_paragraph().text = "Cash runway 22 months"

# 3. Customers
s3 = prs.slides.add_slide(prs.slide_layouts[1])
s3.shapes.title.text = "Customers"
body3 = s3.placeholders[1].text_frame
body3.text = "42 enterprise logos"
body3.add_paragraph().text = "NPS 58 (up from 49)"
body3.add_paragraph().text = "Churn under 4%"

# 4. Operations
s4 = prs.slides.add_slide(prs.slide_layouts[1])
s4.shapes.title.text = "Operations"
body4 = s4.placeholders[1].text_frame
body4.text = "Moved data lake to on-prem"
body4.add_paragraph().text = "Rolled out incident-response playbook"
body4.add_paragraph().text = "Cut infra costs by 18%"

# 5. Thank You
s5 = prs.slides.add_slide(prs.slide_layouts[1])
s5.shapes.title.text = "Thank You"
body5 = s5.placeholders[1].text_frame
body5.text = "Questions and discussion"

prs.save(OUTPUT)
print(f"Created {OUTPUT}")

# --- Sanity check ---
from pptx import Presentation as P2
p = P2(OUTPUT)
titles = [s.shapes.title.text for s in p.slides]
assert titles == ["Annual Report 2025", "Financials", "Customers", "Operations", "Thank You"], titles
assert len(p.slides) == 5
print("Sanity checks passed.")
