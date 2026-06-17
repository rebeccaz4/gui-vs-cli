#!/usr/bin/env python3
"""Create sales_pitch.pptx: 4-slide sales pitch presentation."""
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()

# Slide 1: Our Solution
slide1 = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
slide1.shapes.title.text = "Our Solution"
body1 = slide1.placeholders[1].text_frame
body1.text = "End-to-end supply chain visibility"
body1.add_paragraph().text = "Real-time tracking across 50+ carriers"
body1.add_paragraph().text = "Predictive analytics for demand forecasting"

# Slide 2: Market Opportunity
slide2 = prs.slides.add_slide(prs.slide_layouts[1])
slide2.shapes.title.text = "Market Opportunity"
body2 = slide2.placeholders[1].text_frame
body2.text = "Global logistics market: $12.3 trillion"
body2.add_paragraph().text = "Only 15% digitized today"
body2.add_paragraph().text = "Growing at 6.5% CAGR"

# Slide 3: Business Model
slide3 = prs.slides.add_slide(prs.slide_layouts[1])
slide3.shapes.title.text = "Business Model"
body3 = slide3.placeholders[1].text_frame
body3.text = "SaaS subscription: $500/month per hub"
body3.add_paragraph().text = "Enterprise tier: custom pricing"
body3.add_paragraph().text = "Implementation fee: one-time $5,000"

# Slide 4: Call to Action
slide4 = prs.slides.add_slide(prs.slide_layouts[1])
slide4.shapes.title.text = "Call to Action"
body4 = slide4.placeholders[1].text_frame
body4.text = "Schedule a demo today"
body4.add_paragraph().text = "Pilot program available for Q2 2026"
body4.add_paragraph().text = "Contact: sales@logistics.io"

prs.save("/home/user/Documents/sales_pitch.pptx")
print("Created sales_pitch.pptx")
