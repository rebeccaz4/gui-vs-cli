#!/usr/bin/env python3
"""Create main_deck.pptx and appendix_deck.pptx for the consolidation task."""
from pptx import Presentation
from pptx.util import Inches, Pt

# --- main_deck.pptx: 3 slides ---
prs1 = Presentation()

slide1 = prs1.slides.add_slide(prs1.slide_layouts[1])  # Title and Content
slide1.shapes.title.text = "Project Kickoff"
body1 = slide1.placeholders[1].text_frame
body1.text = "Project Orion: Next-gen platform migration"
body1.add_paragraph().text = "Start date: April 1, 2026"
body1.add_paragraph().text = "Sponsor: VP of Engineering"

slide2 = prs1.slides.add_slide(prs1.slide_layouts[1])
slide2.shapes.title.text = "Timeline"
body2 = slide2.placeholders[1].text_frame
body2.text = "Phase 1: Discovery (4 weeks)"
body2.add_paragraph().text = "Phase 2: Development (12 weeks)"
body2.add_paragraph().text = "Phase 3: Testing (4 weeks)"
body2.add_paragraph().text = "Phase 4: Deployment (2 weeks)"

slide3 = prs1.slides.add_slide(prs1.slide_layouts[1])
slide3.shapes.title.text = "Budget"
body3 = slide3.placeholders[1].text_frame
body3.text = "Total allocated: $1.2M"
body3.add_paragraph().text = "Personnel: $800K"
body3.add_paragraph().text = "Infrastructure: $250K"
body3.add_paragraph().text = "Contingency: $150K"

prs1.save("/home/user/Documents/main_deck.pptx")
print("Created main_deck.pptx")

# --- appendix_deck.pptx: 2 slides ---
prs2 = Presentation()

slide_a = prs2.slides.add_slide(prs2.slide_layouts[1])
slide_a.shapes.title.text = "Risk Assessment"
body_a = slide_a.placeholders[1].text_frame
body_a.text = "High: Vendor dependency on CloudCo"
body_a.add_paragraph().text = "Medium: Key engineer availability"
body_a.add_paragraph().text = "Low: Minor scope creep"

slide_b = prs2.slides.add_slide(prs2.slide_layouts[1])
slide_b.shapes.title.text = "Stakeholder List"
body_b = slide_b.placeholders[1].text_frame
body_b.text = "Alice Wong - Product Owner"
body_b.add_paragraph().text = "Bob Martinez - Tech Lead"
body_b.add_paragraph().text = "Carol Nguyen - QA Manager"
body_b.add_paragraph().text = "Dave Smith - DevOps Lead"

prs2.save("/home/user/Documents/appendix_deck.pptx")
print("Created appendix_deck.pptx")
