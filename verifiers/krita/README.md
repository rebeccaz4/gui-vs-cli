# Krita Verifier

Programmatic state inspection for Krita `.kra` files in E2B sandbox.

## Verification Channel

`.kra` files are ZIP archives. The verifier unzips and parses internal files:

| Internal File | Content |
|---|---|
| `maindoc.xml` | Document structure, layer tree, dimensions, color space |
| `documentinfo.xml` | Metadata (title, author, description, creation date) |
| `mergedimage.png` | Flattened preview of all visible layers |
| `layers/` | Individual layer data as PNG files |

## Usage

```bash
# CLI (inside sandbox)
python3 /home/user/verifiers/krita.py doc-info /home/user/painting.kra
python3 /home/user/verifiers/krita.py layers /home/user/painting.kra
python3 /home/user/verifiers/krita.py check-layer-exists /home/user/painting.kra "Background"

# From check agent (outside sandbox)
result = sandbox.commands.run("python3 /home/user/verifiers/krita.py check-image-size /home/user/painting.kra 1920 1080")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

## Commands

### Query

| Command | Args | Description |
|---|---|---|
| `doc-info` | `<kra_file>` | Document dimensions, color space, resolution |
| `metadata` | `<kra_file>` | Title, author, description from documentinfo.xml |
| `layers` | `<kra_file>` | List all layers with name, type, visibility, opacity |
| `layer-info` | `<kra_file> <layer_name>` | Detailed info for a specific layer |
| `color-profile` | `<kra_file>` | Color profile and resolution info |
| `preview` | `<kra_file>` | Dimensions and format of mergedimage.png |

### Check

| Command | Args | Description |
|---|---|---|
| `check-file-exists` | `<path>` | File exists at path |
| `check-image-size` | `<kra_file> <width> <height>` | Document dimensions match |
| `check-layer-exists` | `<kra_file> <layer_name>` | Layer with name exists |
| `check-layer-count` | `<kra_file> <count>` | Number of layers matches |
| `check-layer-visible` | `<kra_file> <layer_name>` | Layer is visible |
| `check-color-space` | `<kra_file> <color_space>` | Color model matches (RGBA, GRAYA, etc.) |
| `check-has-metadata` | `<kra_file> <key>` | Metadata field exists (title, author, etc.) |
| `check-resolution` | `<kra_file> <dpi>` | X-resolution matches DPI |

## .kra File Structure

```
painting.kra (ZIP archive)
├── mimetype                 # "application/x-krita"
├── maindoc.xml              # <IMAGE width="1920" height="1080" colorspacename="RGBA" x-res="300" ...>
│                            #   <layers>
│                            #     <layer name="Background" nodetype="paintlayer" visible="1" opacity="255" .../>
│                            #   </layers>
│                            # </IMAGE>
├── documentinfo.xml         # <about><title>...</title></about>
│                            # <author><full-name>...</full-name></author>
├── mergedimage.png          # Flattened preview of all visible layers
├── preview.png              # Thumbnail
└── layers/
    └── layer0/              # Individual layer PNG data
        └── ...
```

## Config Location

- Krita config: `~/.config/kritarc`
- CLI export: `krita input.kra --export --export-filename output.png`

## Dependencies

- `zipfile`, `xml.etree.ElementTree` (standard library)
- `Pillow` (PIL) for mergedimage.png inspection (optional, gracefully degrades)
