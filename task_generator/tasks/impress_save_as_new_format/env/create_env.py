#!/usr/bin/env python3
"""Create annual_review.pptx: 5-slide annual review presentation."""
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()

# Slide 1: Title
slide1 = prs.slides.add_slide(prs.slide_layouts[0])  # Title Slide
slide1.shapes.title.text = "Annual Review 2025"
slide1.placeholders[1].text = "Prepared by Executive Team"

# Slide 2: Financial Summary
slide2 = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
slide2.shapes.title.text = "Financial Summary"
body2 = slide2.placeholders[1].text_frame
body2.text = "Total Revenue: $28.5M"
body2.add_paragraph().text = "Operating Expenses: $19.2M"
body2.add_paragraph().text = "Gross Margin: 33%"

# Slide 3: Team Growth
slide3 = prs.slides.add_slide(prs.slide_layouts[1])
slide3.shapes.title.text = "Team Growth"
body3 = slide3.placeholders[1].text_frame
body3.text = "Headcount increased from 150 to 210"
body3.add_paragraph().text = "New offices in Austin and Berlin"
body3.add_paragraph().text = "Employee satisfaction score: 4.2/5"

# Slide 4: Product Milestones
slide4 = prs.slides.add_slide(prs.slide_layouts[1])
slide4.shapes.title.text = "Product Milestones"
body4 = slide4.placeholders[1].text_frame
body4.text = "Launched v3.0 in March"
body4.add_paragraph().text = "Mobile app reached 100K downloads"
body4.add_paragraph().text = "API integrations grew by 40%"

# Slide 5: Goals for 2026
slide5 = prs.slides.add_slide(prs.slide_layouts[1])
slide5.shapes.title.text = "Goals for 2026"
body5 = slide5.placeholders[1].text_frame
body5.text = "Achieve $40M revenue target"
body5.add_paragraph().text = "Expand to 3 new markets"
body5.add_paragraph().text = "Launch enterprise platform"

prs.save("/home/user/Documents/annual_review.pptx")
print("Created annual_review.pptx")
