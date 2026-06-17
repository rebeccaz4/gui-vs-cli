#!/usr/bin/env python3
"""Create workshop_slides.pptx: 5-slide workshop presentation."""
from pptx import Presentation

prs = Presentation()

slides_data = [
    ("Workshop Introduction", "Welcome to the DevOps Workshop\nDuration: Full Day\nPrerequisites: Basic Linux knowledge"),
    ("Agenda", "Morning: Theory and concepts\nAfternoon: Hands-on exercises\nEnd of day: Review and wrap up"),
    ("Exercise 1", "Basic Shell Scripting\nCreate a script to automate log rotation"),
    ("Exercise 2", "Docker Fundamentals\nBuild and run a containerized application"),
    ("Wrap Up", "Key takeaways from today\nAdditional resources and reading\nFeedback survey link: workshop.dev/feedback"),
]

for title, content in slides_data:
    slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    lines = content.split("\n")
    body.text = lines[0]
    for line in lines[1:]:
        body.add_paragraph().text = line

prs.save("/home/user/Documents/workshop_slides.pptx")
print("Created workshop_slides.pptx")
