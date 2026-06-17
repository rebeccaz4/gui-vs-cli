#!/usr/bin/env python3
"""Create draft_article.odt with British English spellings to be replaced."""
import zipfile
import os

# 5x colour, 3x analyse, 4x organisation
CONTENT_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:body>
    <office:text>
      <text:p text:style-name="Standard">The Future of Artificial Intelligence</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Machine Learning Trends</text:p>
      <text:p text:style-name="Standard">Modern machine learning systems can analyse vast datasets to identify patterns that humans might miss. The colour of data visualizations plays a crucial role in how we interpret results. Each organisation involved in AI research brings a unique perspective to the field. When researchers analyse neural network outputs, they often use colour-coded heatmaps to highlight areas of interest.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Natural Language Processing</text:p>
      <text:p text:style-name="Standard">NLP has transformed how every organisation handles text data. The ability to analyse sentiment in customer feedback has become essential for modern businesses. Large language models can understand context, tone, and even the colour of language used in marketing materials. The colour spectrum of sentiment analysis dashboards helps teams quickly identify trends. Every major organisation now invests heavily in NLP capabilities to stay competitive.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Ethical Considerations</text:p>
      <text:p text:style-name="Standard">As AI systems become more powerful, each organisation must consider the ethical implications of their deployment. Bias in training data can affect outcomes regardless of the colour of the interface or the sophistication of the model. The responsible development of AI requires that we carefully consider how these tools affect society. No company should deploy AI systems without thorough testing and validation.</text:p>
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

out_path = '/home/user/Documents/draft_article.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
