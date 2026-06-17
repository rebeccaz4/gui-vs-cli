# Kdenlive Verifier

Programmatic state inspection for Kdenlive video editing projects in E2B desktop sandboxes.

## Verification Channels

1. **XML parsing** (primary) -- `.kdenlive` project files use MLT XML schema. Parse to extract clips, tracks, effects, transitions, and project settings.
2. **ffprobe** -- verify rendered output media files (codec, duration, resolution).
3. **File-based config** -- `~/.config/kdenliverc` for application settings.

## .kdenlive XML Structure

Kdenlive project files are MLT (Media Lovin' Toolkit) XML documents:

- `<mlt>` -- root element
- `<profile>` -- resolution, frame rate, colorspace
- `<producer>` -- media clips (resource path, length, clip type)
- `<playlist>` -- tracks containing entries and blanks
- `<tractor>` -- timeline assembly combining tracks
- `<filter>` -- effects applied to clips or tracks
- `<transition>` -- transitions between tracks

## CLI Usage

```bash
# Query endpoints
python3 kdenlive.py project-info /path/to/project.kdenlive
python3 kdenlive.py clips /path/to/project.kdenlive
python3 kdenlive.py tracks /path/to/project.kdenlive
python3 kdenlive.py effects /path/to/project.kdenlive
python3 kdenlive.py transitions /path/to/project.kdenlive
python3 kdenlive.py clip-info /path/to/project.kdenlive producer0
python3 kdenlive.py profile /path/to/project.kdenlive
python3 kdenlive.py render-info /path/to/output.mp4

# Check endpoints (return {"match": true/false, ...} or {"exists": true/false, ...})
python3 kdenlive.py check-file-exists /path/to/file.mp4
python3 kdenlive.py check-clip-exists /path/to/project.kdenlive clip.mp4
python3 kdenlive.py check-clip-count /path/to/project.kdenlive 3
python3 kdenlive.py check-track-count /path/to/project.kdenlive 4
python3 kdenlive.py check-effect-exists /path/to/project.kdenlive frei0r.glow
python3 kdenlive.py check-transition-exists /path/to/project.kdenlive luma
python3 kdenlive.py check-resolution /path/to/project.kdenlive 1920 1080
python3 kdenlive.py check-fps /path/to/project.kdenlive 25
python3 kdenlive.py check-render-output /path/to/output.mp4
```

## Python Usage

```python
from verifiers.kdenlive import KdenliveVerifier

v = KdenliveVerifier()

# Query
info = v.get_project_info("/path/to/project.kdenlive")
clips = v.get_clips("/path/to/project.kdenlive")
profile = v.get_profile("/path/to/project.kdenlive")

# Checks
result = v.check_clip_count("/path/to/project.kdenlive", 3)
# => {"match": True, "expected": 3, "actual": 3}

result = v.check_resolution("/path/to/project.kdenlive", 1920, 1080)
# => {"match": True, "expected": {"width": 1920, "height": 1080}, "actual": {...}}
```

## Sandbox Integration

```python
from e2b_desktop import Sandbox

sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)
sandbox.commands.run("mkdir -p /home/user/verifiers")
sandbox.files.write("/home/user/verifiers/kdenlive.py", open("kdenlive.py").read())

# Run verifier commands
result = sandbox.commands.run("python3 /home/user/verifiers/kdenlive.py clips /path/to/project.kdenlive")
data = json.loads(result.stdout)
```

## Headless Rendering

Kdenlive projects can be rendered headlessly using `melt`:

```bash
melt project.kdenlive -consumer avformat:output.mp4 acodec=aac vcodec=libx264
```

Then verify the output:

```bash
python3 kdenlive.py check-render-output /path/to/output.mp4
```

## Dependencies

- Python 3.10+ (standard library only: `xml.etree.ElementTree`, `json`, `subprocess`)
- `ffprobe` (from ffmpeg) for `render-info` and `check-render-output` commands
