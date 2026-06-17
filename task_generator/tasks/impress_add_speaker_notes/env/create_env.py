#!/usr/bin/env python3
"""Create training_deck.pptx: 4-slide employee onboarding presentation."""
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()

# Slide 1: Welcome
slide1 = prs.slides.add_slide(prs.slide_layouts[0])  # Title Slide
slide1.shapes.title.text = "Welcome"
slide1.placeholders[1].text = "New Employee Onboarding Program"

# Slide 2: Company History
slide2 = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
slide2.shapes.title.text = "Company History"
body2 = slide2.placeholders[1].text_frame
body2.text = "Founded in 2010"
body2.add_paragraph().text = "Expanded to 15 countries by 2018"
body2.add_paragraph().text = "Over 5,000 employees worldwide"

# Slide 3: Tools & Systems
slide3 = prs.slides.add_slide(prs.slide_layouts[1])
slide3.shapes.title.text = "Tools & Systems"
body3 = slide3.placeholders[1].text_frame
body3.text = "Email: Microsoft Outlook"
body3.add_paragraph().text = "Chat: Slack"
body3.add_paragraph().text = "Project Management: Jira"
body3.add_paragraph().text = "Documentation: Confluence"

# Slide 4: Q&A
slide4 = prs.slides.add_slide(prs.slide_layouts[1])
slide4.shapes.title.text = "Q&A"
body4 = slide4.placeholders[1].text_frame
body4.text = "Questions?"
body4.add_paragraph().text = "Contact HR at hr@company.com"

prs.save("/home/user/Documents/training_deck.pptx")
print("Created training_deck.pptx")
