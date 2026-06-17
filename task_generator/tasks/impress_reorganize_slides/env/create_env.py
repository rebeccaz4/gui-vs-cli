#!/usr/bin/env python3
"""Create project_plan.pptx: 6-slide presentation in order Cover, Timeline, Budget, Team, Risks, Summary."""
from pptx import Presentation

prs = Presentation()

slides_data = [
    ("Cover", "Project Phoenix - Strategic Plan 2026"),
    ("Timeline", "Key milestones and deadlines for Q1-Q4"),
    ("Budget", "Total budget: $2.5M allocated across departments"),
    ("Team", "Core team of 12 members across engineering and design"),
    ("Risks", "Supply chain disruptions and regulatory changes"),
    ("Summary", "On track for Q3 delivery with current resource allocation"),
]

for title, content in slides_data:
    slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
    slide.shapes.title.text = title
    slide.placeholders[1].text_frame.text = content

prs.save("/home/user/Documents/project_plan.pptx")
print("Created project_plan.pptx")
