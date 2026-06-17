#!/usr/bin/env python3
"""Create quarterly_report.odt with flat unstructured report text."""
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
      <text:p text:style-name="Standard">Q4 2025 Quarterly Report</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Revenue Overview</text:p>
      <text:p text:style-name="Standard">The fourth quarter showed strong performance across all business segments. Product sales exceeded projections by 8 percent, driven by the successful launch of our new enterprise platform. Services revenue grew by 12 percent year-over-year, reflecting increased demand for consulting and implementation support.</text:p>
      <text:p text:style-name="Standard">Total Revenue: $2,450,000</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Expense Analysis</text:p>
      <text:p text:style-name="Standard">Operating expenses remained within budget for the quarter. The largest increase was in R&amp;D spending, which grew by 15 percent to support ongoing product development initiatives. Marketing spend was reduced by 5 percent through improved digital campaign efficiency.</text:p>
      <text:p text:style-name="Standard">Total Expenses: $1,890,000</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Key Achievements</text:p>
      <text:p text:style-name="Standard">Successfully launched Enterprise Platform v3.0 with zero critical defects. Onboarded 45 new enterprise clients, exceeding the target of 35. Customer satisfaction scores improved from 4.2 to 4.6 out of 5.0. Completed SOC 2 Type II certification ahead of schedule.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Next Steps</text:p>
      <text:p text:style-name="Standard">For Q1 2026, the focus will be on expanding into the APAC market, launching the mobile companion app, and scaling the customer success team. Budget proposals for new hires are due by January 15, 2026.</text:p>
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

out_path = '/home/user/Documents/quarterly_report.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
