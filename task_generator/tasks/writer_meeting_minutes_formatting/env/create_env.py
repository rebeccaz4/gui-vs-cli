#!/usr/bin/env python3
"""Create meeting_notes.odt with unformatted meeting minutes."""
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
      <text:p text:style-name="Standard">Project Alpha Meeting Minutes</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Attendees</text:p>
      <text:p text:style-name="Standard">John Smith - Project Manager</text:p>
      <text:p text:style-name="Standard">Sarah Lee - Lead Developer</text:p>
      <text:p text:style-name="Standard">Mike Chen - QA Engineer</text:p>
      <text:p text:style-name="Standard">Lisa Park - UX Designer</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Agenda</text:p>
      <text:p text:style-name="Standard">1. Sprint review and demo of new features</text:p>
      <text:p text:style-name="Standard">2. Discussion of TBD items from last meeting</text:p>
      <text:p text:style-name="Standard">3. Resource allocation for next quarter</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Discussion</text:p>
      <text:p text:style-name="Standard">The team reviewed the current sprint progress. The new authentication module is TBD pending security review. The database migration timeline is TBD until infrastructure team confirms capacity. Sarah presented the API redesign which received positive feedback from all attendees.</text:p>
      <text:p text:style-name="Standard">Mike raised concerns about test coverage for the payment module. The deadline for completing integration tests is TBD based on developer availability.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Action Items</text:p>
      <text:p text:style-name="Standard">- John to schedule follow-up with infrastructure team by Friday</text:p>
      <text:p text:style-name="Standard">- Sarah to finalize API documentation, deadline TBD</text:p>
      <text:p text:style-name="Standard">- Mike to create test plan for payment module</text:p>
      <text:p text:style-name="Standard">- Lisa to share updated wireframes by next Monday</text:p>
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

out_path = '/home/user/Documents/meeting_notes.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    # mimetype must be first and uncompressed
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
