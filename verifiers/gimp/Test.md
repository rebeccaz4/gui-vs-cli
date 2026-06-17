# GIMP Verifier Test Plan

## Module Overview

The GIMP verifier inspects image state through two channels:

1. **Script-Fu TCP server** (port 10008) — live queries for open images, layers, channels, pixel colors, resolution
2. **PIL (Pillow)** — file-based inspection of exported images (dimensions, format, mode, pixel colors)
3. **Config parsing** — gimprc preferences

Prerequisites: GIMP must be launched with `gimp -b '(plug-in-script-fu-server RUN-NONINTERACTIVE "127.0.0.1" 10008 "")' &` for live endpoints.

## Test Groups

### Group 1: Help/Usage
- **What is tested**: CLI `--help` output, unknown subcommand error
- **Edge cases**: No arguments, `-h` flag, `help` subcommand
- **Expected test count**: 3

### Group 2: Error Handling — Script-Fu Not Running
- **What is tested**: All live endpoints when GIMP/Script-Fu server is not running
- **Edge cases**: Connection refused on all Script-Fu-dependent commands
- **Expected test count**: 8 (one per live endpoint: images, image-info, layers, channels, active-layer, pixel-color, check-image-open, check-layer-exists)

### Group 3: Error Handling — File Not Found
- **What is tested**: All file-based endpoints with nonexistent paths
- **Edge cases**: Nonexistent file, empty path, directory instead of file
- **Expected test count**: 7 (file-info, pixel-color-file, check-file-exists, check-file-dimensions, check-file-format, check-file-mode, check-pixel-color-file)

### Group 4: Error Handling — Missing Arguments
- **What is tested**: CLI commands called without required arguments
- **Edge cases**: Missing file path, missing coordinates, missing expected values
- **Expected test count**: 6

### Group 5: File-Based Query Endpoints
- **What is tested**: `file-info`, `pixel-color-file` with various image formats
- **Edge cases**: PNG, JPEG, BMP, GIF images; RGB vs RGBA vs grayscale; edge pixel coordinates
- **Expected test count**: 12

### Group 6: File-Based Check Endpoints — Positive Cases
- **What is tested**: `check-file-exists`, `check-file-dimensions`, `check-file-format`, `check-file-mode`, `check-pixel-color-file` returning true
- **Edge cases**: Various formats and modes
- **Expected test count**: 10

### Group 7: File-Based Check Endpoints — Negative Cases
- **What is tested**: Same check endpoints returning false (wrong dimensions, wrong format, wrong color, etc.)
- **Edge cases**: Close-but-wrong values, format aliases (JPG vs JPEG)
- **Expected test count**: 10

### Group 8: Script-Fu Live Query Endpoints
- **What is tested**: `images`, `image-info`, `layers`, `channels`, `active-layer`, `pixel-color` with images open
- **Edge cases**: Single image, multi-layer image, image with alpha, different color modes
- **Expected test count**: 15

### Group 9: Script-Fu Live Check Endpoints — Positive Cases
- **What is tested**: `check-image-open`, `check-layer-exists`, `check-layer-count`, `check-image-mode`, `check-has-alpha`, `check-resolution`, `check-image-size`
- **Edge cases**: Exact match values
- **Expected test count**: 7

### Group 10: Script-Fu Live Check Endpoints — Negative Cases
- **What is tested**: Same check endpoints with wrong/mismatched values
- **Edge cases**: Wrong layer name, wrong count, wrong mode, wrong size
- **Expected test count**: 7

### Group 11: Preferences Endpoint
- **What is tested**: `preferences` reading from gimprc
- **Edge cases**: No key (list all), specific key, nonexistent key, config dir not found
- **Expected test count**: 3

### Group 12: JSON Validity Sweep
- **What is tested**: Every CLI subcommand produces valid JSON output
- **Edge cases**: All 21 commands with valid arguments
- **Expected test count**: 21

## Test Fixtures

### Fixture 1: `test_rgb_800x600.png`
- **Path**: Generated in sandbox at `/home/user/test_fixtures/test_rgb_800x600.png`
- **Format**: PNG, RGB mode, 800x600
- **Contents**: Red rectangle (top-left quadrant), green rectangle (top-right), blue rectangle (bottom-left), white rectangle (bottom-right). Pixel (0,0)=(255,0,0), pixel (400,0)=(0,255,0), pixel (0,300)=(0,0,255), pixel (400,300)=(255,255,255)
- **Used by**: Groups 5, 6, 7, 12

### Fixture 2: `test_rgba_256x256.png`
- **Path**: `/home/user/test_fixtures/test_rgba_256x256.png`
- **Format**: PNG, RGBA mode, 256x256
- **Contents**: Semi-transparent red circle on transparent background. Pixel (128,128) has alpha < 255, pixel (0,0) has alpha=0
- **Used by**: Groups 5, 6, 7

### Fixture 3: `test_gray_100x100.png`
- **Path**: `/home/user/test_fixtures/test_gray_100x100.png`
- **Format**: PNG, L mode (grayscale), 100x100
- **Contents**: Gradient from black (left) to white (right). Pixel (0,50)~0, pixel (99,50)~255
- **Used by**: Groups 5, 6, 7

### Fixture 4: `test_photo.jpg`
- **Path**: `/home/user/test_fixtures/test_photo.jpg`
- **Format**: JPEG, RGB mode, 640x480
- **Contents**: Solid blue image (0, 0, 255) — simple but verifiable
- **Used by**: Groups 5, 6, 7

### Fixture 5: `test_small.bmp`
- **Path**: `/home/user/test_fixtures/test_small.bmp`
- **Format**: BMP, RGB mode, 50x50
- **Contents**: Solid green (0, 255, 0)
- **Used by**: Groups 5, 6, 7

### Fixture 6: `test_multi_layer.xcf` (opened in GIMP for live tests)
- **Path**: Created by opening fixture PNGs in GIMP and adding layers via Script-Fu
- **Contents**: 3-layer image — "Background" (white, 800x600), "Red Layer" (red, 800x600, 80% opacity), "Blue Overlay" (blue, 400x300, offset at 100,100)
- **Used by**: Groups 8, 9, 10

### Fixture 7: `test_grayscale.png` (opened in GIMP for mode check)
- **Path**: `/home/user/test_fixtures/test_grayscale_open.png`
- **Format**: PNG, grayscale
- **Contents**: 200x200 gray gradient, converted to GRAY mode in GIMP
- **Used by**: Groups 9, 10

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected behavior |
|---|---|---|
| Script-Fu server not running | All live endpoints | `{"error": "Cannot connect to Script-Fu server..."}` |
| No images open | image-info, layers, channels, active-layer | `{"error": "No images open in GIMP"}` |
| Image index out of range | image-info 99, layers 99 | `{"error": "Image index 99 out of range..."}` |
| Missing required argument | check-layer-exists (no args) | exit 1 + `{"error": "Missing required argument..."}` |
| Unknown subcommand | `gibberish` | exit 1 + `{"error": "Unknown command: gibberish..."}` |
| Nonexistent file path | file-info /tmp/nope.png | `{"error": "File not found: /tmp/nope.png"}` |
| Coordinates out of bounds | pixel-color-file ... 9999 9999 | `{"error": "Coordinates (9999, 9999) out of bounds..."}` |
| Wrong argument type | check-layer-count abc | exit 1 + error JSON |
| Empty image (no layers) | layers, check-layer-count 0 | empty list / match=true |
| Non-image file | file-info /etc/passwd | `{"error": "Cannot read image: ..."}` |

## Positive / Negative Case Pairs

### File-based checks

| Endpoint | Positive case | Negative case |
|---|---|---|
| check-file-exists | Existing PNG fixture | `/tmp/definitely_not_here.png` |
| check-file-dimensions | test_rgb_800x600.png with 800 600 | Same file with 1024 768 |
| check-file-format | test_photo.jpg with JPEG | Same file with PNG |
| check-file-mode | test_rgba_256x256.png with RGBA | Same file with RGB |
| check-pixel-color-file | test_rgb_800x600.png (0,0) with 255,0,0 | Same pixel with 0,255,0 |

### Live checks

| Endpoint | Positive case | Negative case |
|---|---|---|
| check-image-open | Filename of opened image | `nonexistent_image.xcf` |
| check-layer-exists | "Background" (exists) | "NoSuchLayer" |
| check-layer-count | Actual count matches | Count off by 1 |
| check-image-mode | Actual mode (RGB) | Wrong mode (GRAY) |
| check-has-alpha | Image with alpha layer | Image without alpha |
| check-resolution | Actual DPI | Wrong DPI |
| check-image-size | Actual dimensions | Wrong dimensions |

## JSON Validity Sweep

All CLI subcommands to test for valid JSON output:

1. `images`
2. `image-info`
3. `image-info 0`
4. `layers`
5. `layers 0`
6. `channels 0`
7. `active-layer`
8. `pixel-color 0 0`
9. `file-info <fixture_path>`
10. `pixel-color-file <fixture_path> 0 0`
11. `preferences`
12. `check-image-open test`
13. `check-layer-exists Background`
14. `check-layer-count 1`
15. `check-image-mode RGB`
16. `check-has-alpha`
17. `check-resolution 72 72`
18. `check-image-size 800 600`
19. `check-file-exists <fixture_path>`
20. `check-file-dimensions <fixture_path> 800 600`
21. `check-file-format <fixture_path> PNG`
22. `check-file-mode <fixture_path> RGB`
23. `check-pixel-color-file <fixture_path> 0 0 255 0 0`

## Summary

| Metric | Count |
|---|---|
| Test groups | 12 |
| Total assertions | ~102 |
| Test fixtures (files generated) | 7 |
| `check-*` endpoints with pos+neg pairs | 12 |
| Error scenarios covered | 10 |
