#!/usr/bin/env python3
"""Create syllabus_draft.odt with plain text course syllabus containing Prof. and TBA occurrences."""
import zipfile
import os

CONTENT_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:body>
    <office:text>
      <text:p text:style-name="Standard">Introduction to Computer Science - CS101</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Course Description</text:p>
      <text:p text:style-name="Standard">This course provides a broad introduction to the field of computer science. Topics include algorithms, data structures, software engineering principles, and computational thinking. The course is taught by Prof. Amanda Richards and meets three times per week.</text:p>
      <text:p text:style-name="Standard">Office hours are held every Tuesday and Thursday from 2:00 PM to 4:00 PM in Room 312. Students may also schedule appointments with Prof. Richards by email.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Prerequisites</text:p>
      <text:p text:style-name="Standard">Students must have completed MATH 101 (Calculus I) or equivalent. Prior programming experience is helpful but not required. All students should have access to a laptop with Python 3.10 or later installed.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Grading Policy</text:p>
      <text:p text:style-name="Standard">Homework assignments: 30 percent. Lab exercises: 20 percent. Midterm exam: 20 percent. Final project: 30 percent. Late submissions will receive a 10 percent penalty per day. The grading scale follows the standard university policy.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Midterm Exam</text:p>
      <text:p text:style-name="Standard">The midterm exam will cover all material from weeks 1 through 7. The exam date is TBA and will be announced at least two weeks in advance. The exam format will include multiple choice, short answer, and one coding problem. Review sessions will be held the week before the exam, schedule TBA.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Final Project</text:p>
      <text:p text:style-name="Standard">Students will work in teams of 3-4 to develop a software application that demonstrates mastery of course concepts. Project proposals are due in week 10. Final presentations will be held during the last week of classes. The presentation room is TBA. Each team will have 15 minutes to present followed by 5 minutes of questions.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Weekly Schedule</text:p>
      <text:p text:style-name="Standard">Week 1-2: Introduction to Python and basic syntax</text:p>
      <text:p text:style-name="Standard">Week 3-4: Control flow, functions, and modules</text:p>
      <text:p text:style-name="Standard">Week 5-6: Data structures (lists, dictionaries, sets)</text:p>
      <text:p text:style-name="Standard">Week 7: Midterm review and exam</text:p>
      <text:p text:style-name="Standard">Week 8-9: Object-oriented programming</text:p>
      <text:p text:style-name="Standard">Week 10-11: Algorithms and complexity analysis</text:p>
      <text:p text:style-name="Standard">Week 12-13: Software engineering practices</text:p>
      <text:p text:style-name="Standard">Week 14: Final project presentations</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Guest lecture by Prof. David Kim on machine learning applications is tentatively scheduled for week 11. The exact date is TBA.</text:p>
    </office:text>
  </office:body>
</office:document-content>'''

META_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  office:version="1.2">
  <office:meta>
    <meta:generator>Python ODT Generator</meta:generator>
  </office:meta>
</office:document-meta>'''

STYLES_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
</office:document-styles>'''

MANIFEST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.text" manifest:full-path="/"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="meta.xml"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>
</manifest:manifest>'''

MIMETYPE = 'application/vnd.oasis.opendocument.text'

out_path = '/home/user/Documents/syllabus_draft.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
