#!/usr/bin/env python3
"""Create project_data.odt with plain text project information."""
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
      <text:p text:style-name="Standard">Project Phoenix Status Report</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Timeline</text:p>
      <text:p text:style-name="Standard">The project kicked off on January 15, 2025 and is currently in Phase 3 of 4. Phase 1 (Requirements) was completed on time. Phase 2 (Design) was completed two weeks ahead of schedule. Phase 3 (Development) is currently 75% complete with an expected completion date of April 30, 2026. Phase 4 (Testing and Deployment) is scheduled for May through July 2026.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Budget Summary</text:p>
      <text:p text:style-name="Standard">The overall project budget is $95,000. Current spending is tracking slightly under budget. Development costs are the largest line item at $50,000 budgeted. Testing has a budget of $15,000. Infrastructure costs are budgeted at $20,000. Training and documentation budget is $10,000.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Team Assignments</text:p>
      <text:p text:style-name="Standard">Project Manager: Rachel Green - Overall coordination and stakeholder communication. Lead Developer: Tom Wilson - Architecture decisions and code reviews. Backend Team: 3 developers working on API and database layers. Frontend Team: 2 developers building the user interface. QA Lead: Nina Patel - Test planning and execution. DevOps: Alex Kim - CI/CD pipeline and infrastructure.</text:p>
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

out_path = '/home/user/Documents/project_data.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
