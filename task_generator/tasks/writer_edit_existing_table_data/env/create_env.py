#!/usr/bin/env python3
"""Create sales_report.odt with a heading and an existing table with sales data.
The table has some values that need to be corrected by the agent.
Also contains 'Q3 2025' text that needs to be replaced with 'Q4 2025'."""
import zipfile
import os

CONTENT_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Monthly Sales Report</text:h>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">This report covers the sales performance for Q3 2025. All figures are based on confirmed orders and shipped products. The data was compiled by the sales analytics team on the last business day of Q3 2025.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <table:table table:name="Table1">
        <table:table-column table:number-columns-repeated="4"/>
        <table:table-row>
          <table:table-cell><text:p>Region</text:p></table:table-cell>
          <table:table-cell><text:p>Product</text:p></table:table-cell>
          <table:table-cell><text:p>Units Sold</text:p></table:table-cell>
          <table:table-cell><text:p>Revenue</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>North</text:p></table:table-cell>
          <table:table-cell><text:p>Widget A</text:p></table:table-cell>
          <table:table-cell><text:p>150</text:p></table:table-cell>
          <table:table-cell><text:p>$75,000</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>South</text:p></table:table-cell>
          <table:table-cell><text:p>Widget B</text:p></table:table-cell>
          <table:table-cell><text:p>200</text:p></table:table-cell>
          <table:table-cell><text:p>$60,000</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>East</text:p></table:table-cell>
          <table:table-cell><text:p>Widget C</text:p></table:table-cell>
          <table:table-cell><text:p>180</text:p></table:table-cell>
          <table:table-cell><text:p>$45,000</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>West</text:p></table:table-cell>
          <table:table-cell><text:p>Widget D</text:p></table:table-cell>
          <table:table-cell><text:p>95</text:p></table:table-cell>
          <table:table-cell><text:p>$38,000</text:p></table:table-cell>
        </table:table-row>
      </table:table>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Notes: All revenue figures are in USD. Units sold figures may be subject to minor adjustments pending final reconciliation.</text:p>
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

out_path = '/home/user/Documents/sales_report.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
