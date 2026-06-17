# LibreOffice Writer Verifier

Programmatic state inspection for LibreOffice Writer documents in E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Prerequisites

Launch LibreOffice Writer with UNO socket listener enabled:

```bash
soffice --writer --accept="socket,host=localhost,port=2002;urp;" --norestore &
```

For file-based verification (ODF parsing), no running instance is needed — just a saved `.odt` file.

## Verification Channels

| Channel | When to use | Needs running LO? |
|---------|-------------|-------------------|
| **UNO API** | Live text, paragraphs, formatting, tables, images | Yes |
| **ODF parsing** | Saved file content, offline verification | No |
| **File checks** | File existence, save state | No |

## Endpoint Reference

### UNO Live State

#### `text`
Get the full text content of the document.
```bash
python3 /home/user/verifiers/libreoffice_writer.py text
```
```json
{"text": "Hello World\nSecond paragraph", "length": 30}
```

#### `paragraphs`
List all paragraphs with text and style name.
```bash
python3 /home/user/verifiers/libreoffice_writer.py paragraphs
```
```json
{"paragraphs": [{"index": 0, "text": "Title", "style": "Heading 1"}, {"index": 1, "text": "Body text", "style": "Default Paragraph Style"}], "count": 2}
```

#### `paragraph-format [index]`
Get detailed formatting of a specific paragraph.
```bash
python3 /home/user/verifiers/libreoffice_writer.py paragraph-format 0
```
```json
{"index": 0, "text": "Title", "style": "Heading 1", "alignment": "center", "bold": true, "italic": false, "font_name": "Arial", "font_size": 18.0, "font_color": "#000000"}
```

#### `doc-info`
Get document metadata.
```bash
python3 /home/user/verifiers/libreoffice_writer.py doc-info
```
```json
{"path": "file:///home/user/test.odt", "title": "test.odt", "page_count": 3, "word_count": 150, "modified": true}
```

#### `page-count`
Get the number of pages.
```bash
python3 /home/user/verifiers/libreoffice_writer.py page-count
```
```json
{"page_count": 3}
```

#### `tables`
List all tables in the document.
```bash
python3 /home/user/verifiers/libreoffice_writer.py tables
```
```json
{"tables": [{"name": "Table1", "rows": 3, "cols": 4}], "count": 1}
```

#### `table-data [table_name]`
Get cell data from a table.
```bash
python3 /home/user/verifiers/libreoffice_writer.py table-data Table1
```
```json
{"name": "Table1", "data": [["Name", "Score"], ["Alice", 90]], "rows": 2, "cols": 2}
```

#### `images`
List all images/graphic objects.
```bash
python3 /home/user/verifiers/libreoffice_writer.py images
```
```json
{"images": [{"name": "Image1", "width": 1000, "height": 800}], "count": 1}
```

#### `page-style [style_name]`
Get page style properties (margins, orientation, size).
```bash
python3 /home/user/verifiers/libreoffice_writer.py page-style
```
```json
{"name": "Standard", "width": 21000, "height": 29700, "orientation": "portrait", "margin_top": 2000, "margin_bottom": 2000, "margin_left": 2000, "margin_right": 2000}
```

#### `search <text> [regex]`
Search for text in the document.
```bash
python3 /home/user/verifiers/libreoffice_writer.py search "Hello"
python3 /home/user/verifiers/libreoffice_writer.py search "^Chapter.*" regex
```
```json
{"found": true, "count": 2, "matches": [{"text": "Hello", "index": 0}]}
```

#### `bookmarks`
List all bookmarks.
```bash
python3 /home/user/verifiers/libreoffice_writer.py bookmarks
```
```json
{"bookmarks": ["bookmark1", "bookmark2"], "count": 2}
```

#### `headers-footers`
Get header and footer text from Standard page style.
```bash
python3 /home/user/verifiers/libreoffice_writer.py headers-footers
```
```json
{"header_on": true, "footer_on": true, "header_text": "My Document", "footer_text": "Page 1"}
```

### ODF File Parsing (Offline)

These commands parse `.odt` files directly — no running LibreOffice needed.

#### `parse-text [file_path]`
Extract all text from an ODT file.
```bash
python3 /home/user/verifiers/libreoffice_writer.py parse-text /home/user/report.odt
```
```json
{"text": "Hello World\nBody text", "length": 21, "file": "/home/user/report.odt"}
```

#### `parse-paragraphs [file_path]`
List paragraphs with style from an ODT file.
```bash
python3 /home/user/verifiers/libreoffice_writer.py parse-paragraphs /home/user/report.odt
```
```json
{"paragraphs": [{"index": 0, "text": "Title", "style": "Heading_20_1", "heading": true, "level": 1}], "count": 1}
```

#### `parse-tables [file_path]`
List tables from an ODT file.
```bash
python3 /home/user/verifiers/libreoffice_writer.py parse-tables /home/user/report.odt
```
```json
{"tables": [{"name": "Table1", "rows": 2, "cols": 2, "data": [["A", "B"], ["1", "2"]]}], "count": 1}
```

### Composite Checks (Reward Signals)

All `check-*` commands return a dict with a **primary boolean key** that maps directly to a reward signal.

#### `check-text-contains <text>`
Check if the document contains specific text.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-text-contains "Hello World"
```
```json
{"contains": true, "count": 1, "snippet": "...Hello World..."}
```
**Reward key:** `contains`

#### `check-paragraph-count <expected>`
Check the number of paragraphs.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-paragraph-count 5
```
```json
{"match": true, "expected": 5, "actual": 5}
```
**Reward key:** `match`

#### `check-paragraph-text <index> <expected_text>`
Check if a paragraph has the expected text.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-paragraph-text 0 "Hello World"
```
```json
{"match": true, "index": 0, "expected": "Hello World", "actual": "Hello World"}
```
**Reward key:** `match`

#### `check-paragraph-style <index> <expected_style>`
Check if a paragraph has the expected style.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-paragraph-style 0 "Heading 1"
```
```json
{"match": true, "index": 0, "expected": "Heading 1", "actual": "Heading 1"}
```
**Reward key:** `match`

#### `check-paragraph-formatted <index> [bold=true/false]`
Check if a paragraph has specific formatting. Via CLI, checks bold only; use Python API for full control.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-paragraph-formatted 0 true
```
```json
{"match": true, "index": 0, "checks": {"bold": {"expected": true, "actual": true, "ok": true}}}
```
**Reward key:** `match`

#### `check-table-exists <table_name>`
Check if a table exists by name.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-table-exists Table1
```
```json
{"exists": true, "table": "Table1", "rows": 3, "cols": 4}
```
**Reward key:** `exists`

#### `check-table-cell <table_name> <row> <col> <expected>`
Check if a specific table cell has the expected value.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-table-cell Table1 0 0 Name
```
```json
{"match": true, "table": "Table1", "row": 0, "col": 0, "expected": "Name", "actual": "Name"}
```
**Reward key:** `match`

#### `check-heading-exists <text> [level]`
Check if a heading with the given text exists. Uses live paragraph heading metadata (`OutlineLevel` / heading style) when UNO is available, and falls back to parsing the saved `.odt` heading entries when needed.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-heading-exists "Introduction" 1
```
```json
{"exists": true, "heading": "Introduction", "level": 1, "index": 2}
```
**Reward key:** `exists`

#### `check-word-count <min> [max]`
Check if word count is within range.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-word-count 10 500
```
```json
{"in_range": true, "word_count": 250, "min": 10, "max": 500}
```
**Reward key:** `in_range`

#### `check-file-exists <file_path>`
Check if a document file exists.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-file-exists /home/user/report.odt
```
```json
{"exists": true, "path": "/home/user/report.odt", "size": 12345}
```
**Reward key:** `exists`

#### `check-file-saved`
Check if the document has been saved.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-file-saved
```
```json
{"saved": true, "path": "file:///home/user/test.odt"}
```
**Reward key:** `saved`

#### `check-image-count <expected>`
Check the number of images.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-image-count 2
```
```json
{"match": true, "expected": 2, "actual": 2}
```
**Reward key:** `match`

### Export Format Validation

LibreOffice Writer can export to various formats. These endpoints verify export success:

#### `check-file-format <file_path> <expected_format>`
Check if a file is in the expected format (docx, doc, rtf, txt, html, odt).
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-file-format /home/user/document.docx docx
```
```json
{"match": true, "expected": "docx", "detected": "docx", "file_path": "/home/user/document.docx"}
```
**Reward key:** `match`

#### `check-docx-contains <file_path> <text>`
Check if a DOCX file contains specific text.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-docx-contains /home/user/document.docx "Hello World"
```
```json
{"contains": true, "text": "Hello World", "file": "/home/user/document.docx"}
```
**Reward key:** `contains`

#### `check-doc-contains <file_path> <text>`
Check if a DOC file contains specific text (heuristic extraction).
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-doc-contains /home/user/document.doc "Hello World"
```
```json
{"contains": true, "text": "Hello World", "file": "/home/user/document.doc"}
```
**Reward key:** `contains`

#### `check-rtf-contains <file_path> <text>`
Check if an RTF file contains specific text (strips formatting codes).
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-rtf-contains /home/user/document.rtf "Hello World"
```
```json
{"contains": true, "text": "Hello World", "file": "/home/user/document.rtf"}
```
**Reward key:** `contains`

#### `check-txt-contains <file_path> <text>`
Check if a TXT file contains specific text.
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-txt-contains /home/user/document.txt "Hello World"
```
```json
{"contains": true, "text": "Hello World", "file": "/home/user/document.txt"}
```
**Reward key:** `contains`

#### `check-html-contains <file_path> <text>`
Check if an HTML file contains specific text (strips HTML tags).
```bash
python3 /home/user/verifiers/libreoffice_writer.py check-html-contains /home/user/document.html "Hello World"
```
```json
{"contains": true, "text": "Hello World", "file": "/home/user/document.html"}
```
**Reward key:** `contains`

## Common Verification Patterns

### Check if user typed text in the document
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_writer.py check-text-contains "Hello World"')
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0
```

### Check if user created a heading
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_writer.py check-heading-exists "Introduction" 1')
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if user formatted text bold
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-paragraph-formatted 0 true")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if user created a table
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-table-exists Table1")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Read a saved ODT file without LibreOffice running
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py parse-text /home/user/output.odt")
data = json.loads(result.stdout)
text = data["text"]
```

### Verify export format correctness
```python
# Verify DOCX export
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-file-format /home/user/output.docx docx")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0

# Verify DOCX content
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-docx-contains /home/user/output.docx 'Final Report'")
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0

# Verify RTF export
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-file-format /home/user/output.rtf rtf")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0

# Verify TXT export
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-txt-contains /home/user/output.txt 'Summary')
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0

# Verify HTML export
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-html-contains /home/user/output.html 'Conclusion'")
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0
```
