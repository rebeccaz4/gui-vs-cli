#!/usr/bin/env python3
"""Create legacy_sales.pptx: 8-slide dated sales deck to be cleaned up and rebranded."""
import os
from pptx import Presentation

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "legacy_sales.pptx")

prs = Presentation()

def add_title(title, subtitle):
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    s.placeholders[1].text = subtitle
    return s

def add_content(title, bullets):
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = title
    tf = s.placeholders[1].text_frame
    tf.text = bullets[0]
    for b in bullets[1:]:
        tf.add_paragraph().text = b
    return s

add_title("Acme CRM 2021 Edition", "Relationship management for 2021")
add_content("Problem Landscape", [
    "Scattered customer data across teams",
    "Manual lead hand-off",
    "No single source of truth for revenue"
])
add_content("Legacy Architecture", [
    "Monolith deployed quarterly",
    "Email integration via polling every 15 minutes",
    "Internal-only reporting"
])
add_content("Features", [
    "Opportunity tracker",
    "Reporting dashboards",
    "Outlook plugin"
])
add_content("Old Pricing", [
    "Starter: $30/user/month",
    "Team: $75/user/month",
    "Enterprise: call us"
])
add_content("Case Study: BrightCorp", [
    "Rolled out to 180 sellers in 2022",
    "Cut cycle time by 22%",
    "Expanded ACV by 14%"
])
add_content("Competitor Comparison", [
    "Vs AlphaCRM: better email integration",
    "Vs BetaSuite: lower TCO",
    "Vs GammaSales: stronger reporting"
])
add_content("Call to Action", [
    "Book a demo this week",
    "Pilot with three teams",
    "Quarterly check-ins"
])

prs.save(OUTPUT)
print(f"Created {OUTPUT}")

# Sanity
from pptx import Presentation as P2
p = P2(OUTPUT)
titles = [s.shapes.title.text for s in p.slides]
expected = ["Acme CRM 2021 Edition", "Problem Landscape", "Legacy Architecture", "Features",
            "Old Pricing", "Case Study: BrightCorp", "Competitor Comparison", "Call to Action"]
assert titles == expected, titles
assert len(p.slides) == 8
print("Sanity checks passed.")
