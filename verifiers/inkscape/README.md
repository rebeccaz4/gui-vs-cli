# Inkscape Verifier

Programmatic state inspection for Inkscape SVG documents in E2B desktop sandboxes.

## Overview

The Inkscape verifier parses SVG files directly using Python's `xml.etree.ElementTree` (stdlib) to extract document structure, elements, layers, styles, and text content. No external dependencies are required.

SVG is XML, so every element attribute is directly queryable. The verifier handles Inkscape-specific namespaces (`inkscape:`, `sodipodi:`) for features like layers and connectors.

## Verification Channels

| Channel | Use Case | Dependency |
|---------|----------|------------|
| SVG/XML parsing (primary) | Element queries, text, layers, styles, attributes | `xml.etree.ElementTree` (stdlib) |
| Inkscape CLI (secondary) | Geometry/bounding box queries | `inkscape` binary |

## Installation

Copy `inkscape.py` into the sandbox:

```python
sb.files.write("/home/user/verifiers/inkscape.py", open("verifiers/inkscape/inkscape.py").read())
```

## Usage

### From E2B (CLI mode)

```python
result = sb.commands.run("python3 /home/user/verifiers/inkscape.py elements /home/user/drawing.svg")
data = json.loads(result.stdout)
```

### From Python

```python
from verifiers.inkscape.inkscape import InkscapeVerifier

v = InkscapeVerifier()
elements = v.get_elements("drawing.svg")
layers = v.get_layers("drawing.svg")
```

## Endpoints

### Query Endpoints

| Command | Args | Description |
|---------|------|-------------|
| `elements` | `<svg_file>` | List all elements with id, tag, transform, style |
| `element-info` | `<svg_file> <element_id>` | Detailed info for a specific element |
| `text-content` | `<svg_file>` | Extract all text elements with content and position |
| `layers` | `<svg_file>` | List Inkscape layers |
| `page-info` | `<svg_file>` | Page dimensions, viewBox, units |
| `styles` | `<svg_file> [element_id]` | Get style properties (all or specific element) |
| `paths` | `<svg_file>` | List all path elements with d attribute summary |
| `groups` | `<svg_file>` | List all groups and their children |
| `connections` | `<svg_file>` | List connector elements between objects |

### Check Endpoints

All check endpoints return a dict with a primary boolean key (`exists`, `match`, or `contains`).

| Command | Args | Boolean Key | Description |
|---------|------|-------------|-------------|
| `check-file-exists` | `<path>` | `exists` | Check file exists on disk |
| `check-element-exists` | `<svg_file> <element_id>` | `exists` | Check element exists by id |
| `check-element-count` | `<svg_file> <count>` | `match` | Total element count matches |
| `check-text-contains` | `<svg_file> <text>` | `contains` | SVG contains given text |
| `check-layer-exists` | `<svg_file> <layer_name>` | `exists` | Layer exists by label |
| `check-layer-count` | `<svg_file> <count>` | `match` | Number of layers matches |
| `check-page-size` | `<svg_file> <width> <height>` | `match` | Page dimensions match |
| `check-element-attribute` | `<svg_file> <id> <attr> <value>` | `match` | Element attribute matches (hex colors compared case-insensitively) |
| `check-style-property` | `<svg_file> <id> <property> <value>` | `match` | CSS style property matches (hex colors compared case-insensitively) |
| `check-has-element-type` | `<svg_file> <tag>` | `exists` | Element type exists (rect, circle, etc.) |

## SVG Namespaces

The verifier handles these namespaces automatically:

- `svg:` — `http://www.w3.org/2000/svg`
- `inkscape:` — `http://www.inkscape.org/namespaces/inkscape`
- `sodipodi:` — `http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd`
- `xlink:` — `http://www.w3.org/1999/xlink`

## Testing

```bash
python verifiers/inkscape/test_inkscape.py
```

Requires an E2B sandbox with the `desktop-all-apps` template.
