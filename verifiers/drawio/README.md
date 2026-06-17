# Draw.io Verifier

Programmatic state inspection for draw.io Desktop (`.drawio` files) in E2B sandbox environments.

## Verification Channel

**XML file parsing** — `.drawio` files are XML with `<mxfile>` root element. No API or IPC is needed; all state is read directly from the file.

### File Format

- Root element: `<mxfile>`
- Pages: `<diagram>` elements (each is a page/tab)
- Shapes/connections: `<mxCell>` elements inside `<mxGraphModel><root>`
- Cells have `vertex="1"` (shapes) or `edge="1"` (connections)
- Edges reference `source` and `target` vertex IDs
- Labels are stored in the `value` attribute
- Styles are semicolon-delimited key=value strings

### Encoded Diagrams

Some `.drawio` files store diagram content as base64+deflate encoded text inside `<diagram>` elements rather than inline XML. The verifier handles both formats automatically.

Decoding pipeline: `base64 decode -> deflate decompress -> URL-decode -> XML`

## CLI Usage

```bash
# From E2B sandbox
python3 /home/user/verifiers/drawio.py <command> [args...]

# Help
python3 /home/user/verifiers/drawio.py --help
```

## Commands

### Query Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `diagrams` | `<file>` | List diagram pages (name, id) |
| `cells` | `<file> [page_index]` | List all cells (vertices and edges) |
| `vertices` | `<file> [page_index]` | List vertex cells (shapes) |
| `edges` | `<file> [page_index]` | List edge cells (connections) |
| `cell-info` | `<file> <cell_id> [page_index]` | Detailed cell info |
| `labels` | `<file> [page_index]` | Extract all text labels |
| `connections` | `<file> [page_index]` | List source->target connections |
| `styles` | `<file> <cell_id> [page_index]` | Parse style string into dict |

### Check Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `check-file-exists` | `<path>` | File exists and is valid |
| `check-cell-exists` | `<file> <cell_id>` | Cell with ID exists |
| `check-label-exists` | `<file> <text>` | Label text exists |
| `check-connection-exists` | `<file> <source_id> <target_id>` | Connection exists |
| `check-cell-count` | `<file> <count> [page_index]` | Total cell count matches |
| `check-vertex-count` | `<file> <count> [page_index]` | Vertex count matches |
| `check-edge-count` | `<file> <count> [page_index]` | Edge count matches |
| `check-page-count` | `<file> <count>` | Page count matches |
| `check-style-property` | `<file> <cell_id> <property> <value> [page_index]` | Style property matches |

## Examples

```bash
# List all pages in a diagram
python3 drawio.py diagrams flowchart.drawio
# [{"index": 0, "name": "Page-1", "id": "abc123"}]

# Get all shapes on page 0
python3 drawio.py vertices flowchart.drawio
# [{"id": "2", "value": "Start", "vertex": true, ...}]

# Check if a connection exists between two shapes
python3 drawio.py check-connection-exists flowchart.drawio 2 3
# {"exists": true, "edge_id": "5", "page_index": 0}

# Check a cell's fill color
python3 drawio.py check-style-property flowchart.drawio 2 fillColor "#ffffff"
# {"match": true, "expected": "#ffffff", "actual": "#ffffff"}
```

## Python API

```python
from verifiers.drawio import DrawioVerifier

v = DrawioVerifier()

# Query
pages = v.get_diagrams("/path/to/file.drawio")
cells = v.get_cells("/path/to/file.drawio", page_index=0)
vertices = v.get_vertices("/path/to/file.drawio")
edges = v.get_edges("/path/to/file.drawio")
labels = v.get_labels("/path/to/file.drawio")
connections = v.get_connections("/path/to/file.drawio")

# Check
result = v.check_cell_exists("/path/to/file.drawio", "3")
result = v.check_connection_exists("/path/to/file.drawio", "2", "3")
result = v.check_style_property("/path/to/file.drawio", "2", "fillColor", "#ffffff")
```

## Dependencies

Standard library only — no extra packages required:
- `xml.etree.ElementTree`
- `base64`, `zlib`, `urllib.parse`

## CLI Export (Optional)

draw.io Desktop supports command-line export:

```bash
drawio -x -f png -o output.png input.drawio
drawio -x -f pdf -o output.pdf input.drawio
drawio -x -f svg -o output.svg input.drawio
```
