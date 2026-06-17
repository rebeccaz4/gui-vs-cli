#!/usr/bin/env python3
"""Create product_launch.pptx: 5-slide product launch presentation for Widget Pro."""
from pptx import Presentation

prs = Presentation()

# Slide 1: Title slide
slide1 = prs.slides.add_slide(prs.slide_layouts[0])  # Title Slide
slide1.shapes.title.text = "Widget Pro"
slide1.placeholders[1].text = "Launch Date: March 2025"

# Slide 2: Features
slide2 = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
slide2.shapes.title.text = "Key Features"
body2 = slide2.placeholders[1].text_frame
body2.text = "Real-time analytics dashboard"
body2.add_paragraph().text = "Cross-platform compatibility"
body2.add_paragraph().text = "Enterprise-grade security"
body2.add_paragraph().text = "24/7 customer support"

# Slide 3: Pricing
slide3 = prs.slides.add_slide(prs.slide_layouts[1])
slide3.shapes.title.text = "Pricing"
body3 = slide3.placeholders[1].text_frame
body3.text = "Starter Plan: $49.99/month"
body3.add_paragraph().text = "Professional Plan: $99.99/month"
body3.add_paragraph().text = "Enterprise: Contact us"

# Slide 4: Go-to-Market Strategy
slide4 = prs.slides.add_slide(prs.slide_layouts[1])
slide4.shapes.title.text = "Go-to-Market Strategy"
body4 = slide4.placeholders[1].text_frame
body4.text = "Phase 1: Beta launch to 500 users"
body4.add_paragraph().text = "Phase 2: Public launch with PR campaign"
body4.add_paragraph().text = "Phase 3: Enterprise sales outreach"

# Slide 5: Thank You
slide5 = prs.slides.add_slide(prs.slide_layouts[1])
slide5.shapes.title.text = "Thank You"
body5 = slide5.placeholders[1].text_frame
body5.text = "We look forward to a successful launch!"

prs.save("/home/user/Documents/product_launch.pptx")
print("Created product_launch.pptx")
