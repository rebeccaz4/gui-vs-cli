"""
RenderDoc Verifier — programmatic state inspection for RenderDoc in E2B sandbox.

RenderDoc is a graphics frame capture / GPU debugger. The GUI is `qrenderdoc`,
the headless CLI is `renderdoccmd` (works without a display). Capture files use
the `.rdc` extension and start with a fixed FOURCC header. Capture-settings
files use `.cap` and are JSON. UI state lives in
`~/.local/share/qrenderdoc/UI.config` (a flat JSON map).

qrenderdoc cannot run reliably in the headless sandbox (Qt+GPU), so all live
GUI state endpoints are skipped. Instead, this verifier leverages THREE
verification channels:

  1. Disk files
     - UI.config JSON (theme, font, recent captures, toggles)
     - .rdc capture headers (magic FOURCC 'RDOC', serialise version, prog version)
     - .cap capture-settings JSON (executable, commandLine, workingDir, options)
     - Arbitrary filesystem paths (existence, size, type)
  2. `renderdoccmd` subprocess (headless, GPU-free for non-replay commands)
     - `renderdoccmd version` → build version, supported APIs
     - `renderdoccmd extract --list-sections` → embedded sections of an .rdc
     - `renderdoccmd thumb` → extract embedded thumbnail
     - `renderdoccmd convert -c xml` → dump structured capture metadata
  3. Install tree inspection
     - Vulkan implicit capture layer JSON
     - Plugin directory listing (amd/android/spirv plugins)

Skipped verifier categories (no reliable headless channel):
  - Live UI layout / window state / docking (no running GUI).
  - Shader source / texture pixels beyond structured metadata (would require
    full replay context with a GPU).
  - Keybindings (qrenderdoc does not persist customisable keybindings).
  - Live extensions enumeration (Python extension API needs running UI).

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/renderdoc.py config")
    sandbox.commands.run("python3 /home/user/verifiers/renderdoc.py rdcmd-version")
    sandbox.commands.run("python3 /home/user/verifiers/renderdoc.py rdc-sections /tmp/frame.rdc")
    sandbox.commands.run("python3 /home/user/verifiers/renderdoc.py cap-parse /home/user/captures/triangle.cap")

Returns:
  - All public methods return dicts/lists serializable as JSON.
  - Error conditions return `{"error": "..."}` — never raise.
  - `check-*` endpoints return a dict with one primary boolean key.
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

QRENDERDOC_DATA_DIR = Path.home() / ".local" / "share" / "qrenderdoc"
UI_CONFIG_PATH = QRENDERDOC_DATA_DIR / "UI.config"

# RDC file format constants — matches renderdoc/serialise/rdcfile.cpp v1.36
RDC_MAGIC_BYTES = b"RDOC"  # first 4 bytes of every valid .rdc
RDC_SERIALISE_VERSION = 0x00000102  # current known version at v1.36
RDC_FIXED_HEADER_LEN = 32  # magic(8) + version(4) + headerLength(4) + progVersion(16)


def _find_data_dir() -> Path | None:
    env_dir = os.environ.get("QRENDERDOC_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p
    if QRENDERDOC_DATA_DIR.exists():
        return QRENDERDOC_DATA_DIR
    return None


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {"error": f"File not found: {path}"}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        try:
            return json.loads(content, strict=False)
        except json.JSONDecodeError:
            sanitized = "".join(
                ch for ch in content
                if ord(ch) >= 0x20 or ch in ("\t", "\n", "\r")
            )
            return json.loads(sanitized, strict=False)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in {path}: {e}"}
    except OSError as e:
        return {"error": f"Cannot read {path}: {e}"}


def _parse_expected(raw: str) -> Any:
    """Try to parse a CLI argument as JSON (bool, int, float, list, string).

    Falls back to the raw string if JSON parsing fails.
    """
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Booleans in a shell-friendly form
        low = raw.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low == "null":
            return None
        return raw


# ---------------------------------------------------------------------------
# Verifier class
# ---------------------------------------------------------------------------

class RenderDocVerifier:
    """Stateless — every call re-reads the underlying config files."""

    # === UI.config ===

    def get_config(self, key: str | None = None) -> Any:
        """Read UI.config. With `key`, return a single setting.

        Example:
            v.get_config()
            => {"Font_GlobalScale": 1.5, "UIStyle": "Dark", ...}

            v.get_config("Font_GlobalScale")
            => {"key": "Font_GlobalScale", "value": 1.5}
        """
        data_dir = _find_data_dir()
        path = (data_dir / "UI.config") if data_dir else UI_CONFIG_PATH
        data = _read_json_file(path)
        if isinstance(data, dict) and "error" in data:
            return data
        if key is None:
            return data
        if isinstance(data, dict) and key in data:
            return {"key": key, "value": data[key]}
        return {"error": f"Key '{key}' not found in UI.config"}

    def list_config_keys(self) -> dict:
        """Return all top-level keys in UI.config.

        Example:
            v.list_config_keys()
            => {"keys": ["Font_GlobalScale", "UIStyle", ...], "count": 5}
        """
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return data
        keys = sorted(list(data.keys())) if isinstance(data, dict) else []
        return {"keys": keys, "count": len(keys)}

    def check_setting(self, key: str, expected: str) -> dict:
        """Check a UI.config setting matches the expected value.

        `expected` is parsed as JSON when possible (true/false/numbers/strings).
        """
        expected_val = _parse_expected(expected)
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return {**data, "match": False, "key": key, "expected": expected_val}
        if not isinstance(data, dict):
            return {"match": False, "error": "UI.config is not a JSON object",
                    "key": key, "expected": expected_val}
        if key not in data:
            return {"match": False, "key": key, "expected": expected_val,
                    "actual": None, "error": f"Key '{key}' not set"}
        actual = data[key]
        return {"match": actual == expected_val, "key": key,
                "expected": expected_val, "actual": actual}

    def check_setting_exists(self, key: str) -> dict:
        """Check whether a key exists in UI.config at all.

        Example:
            v.check_setting_exists("Font_GlobalScale")
            => {"exists": true, "key": "Font_GlobalScale", "value": 1.5}
        """
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return {**data, "exists": False, "key": key}
        if isinstance(data, dict) and key in data:
            return {"exists": True, "key": key, "value": data[key]}
        return {"exists": False, "key": key}

    # === Recent captures / recent settings ===

    def get_recent_captures(self) -> dict:
        """List recently opened capture files.

        Example:
            v.get_recent_captures()
            => {"files": ["/home/user/captures/a.rdc", ...], "count": 1}
        """
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return data
        files = data.get("RecentCaptureFiles") if isinstance(data, dict) else None
        if files is None:
            files = []
        if not isinstance(files, list):
            return {"error": "RecentCaptureFiles is not a list"}
        return {"files": files, "count": len(files)}

    def check_recent_capture(self, substring: str) -> dict:
        """Check if a recent capture path contains the given substring."""
        recent = self.get_recent_captures()
        if "error" in recent:
            return {**recent, "found": False, "substring": substring}
        files = recent.get("files", [])
        for f in files:
            if substring in f:
                return {"found": True, "substring": substring, "file": f,
                        "count": len(files)}
        return {"found": False, "substring": substring, "count": len(files),
                "files": files}

    def get_recent_settings(self) -> dict:
        """List RecentCaptureSettings paths (stored .cap capture-settings files)."""
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return data
        items = data.get("RecentCaptureSettings") if isinstance(data, dict) else None
        if items is None:
            items = []
        if not isinstance(items, list):
            return {"error": "RecentCaptureSettings is not a list"}
        return {"settings": items, "count": len(items)}

    # === RDC capture file inspection ===

    def get_rdc_header(self, path: str) -> dict:
        """Parse a .rdc capture file header without running RenderDoc.

        Returns the magic bytes string, serialise version, header length,
        progVersion string, and total file size. Errors if the file is too
        short or the magic doesn't match.
        """
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not p.is_file():
            return {"error": f"Not a file: {path}"}
        try:
            size = p.stat().st_size
            with open(p, "rb") as f:
                header = f.read(RDC_FIXED_HEADER_LEN)
        except OSError as e:
            return {"error": f"Cannot read {path}: {e}"}
        if len(header) < RDC_FIXED_HEADER_LEN:
            return {"error": f"File too short for RDC header ({len(header)} bytes)",
                    "size": size}
        magic = header[:4]
        if magic != RDC_MAGIC_BYTES:
            return {"error": f"Bad magic: expected {RDC_MAGIC_BYTES!r}, got {magic!r}",
                    "size": size, "magic_hex": magic.hex()}
        # Next 4 bytes are the high half of the uint64 magic and must be zero.
        magic_tail = header[4:8]
        try:
            version, header_len = struct.unpack("<II", header[8:16])
        except struct.error as e:
            return {"error": f"Cannot unpack header: {e}", "size": size}
        prog_version_bytes = header[16:32]
        prog_version = prog_version_bytes.split(b"\x00", 1)[0].decode("latin-1", "replace")
        return {
            "valid": True,
            "path": str(p),
            "size": size,
            "magic": magic.decode("latin-1"),
            "magic_hex": magic.hex(),
            "magic_tail_hex": magic_tail.hex(),
            "serialise_version": version,
            "header_length": header_len,
            "prog_version": prog_version,
        }

    def check_rdc_valid(self, path: str) -> dict:
        """Check whether `path` is a valid .rdc capture (magic bytes + parseable header)."""
        result = self.get_rdc_header(path)
        if "error" in result:
            return {"valid": False, "path": path, "error": result["error"]}
        return {"valid": True, "path": result["path"], "size": result["size"],
                "serialise_version": result["serialise_version"],
                "prog_version": result["prog_version"]}

    def check_rdc_version(self, path: str, expected_version: str) -> dict:
        """Check the serialise_version field of a .rdc file.

        `expected_version` may be decimal ("258") or hex ("0x102"). Both
        are compared against the parsed uint32.
        """
        expected_int: int
        try:
            if expected_version.lower().startswith("0x"):
                expected_int = int(expected_version, 16)
            else:
                expected_int = int(expected_version)
        except ValueError:
            return {"match": False, "error": f"Bad version format: {expected_version}"}
        result = self.get_rdc_header(path)
        if "error" in result:
            return {"match": False, "error": result["error"]}
        actual = result.get("serialise_version")
        return {"match": actual == expected_int, "expected": expected_int,
                "actual": actual, "path": result.get("path")}

    # === File listing / filesystem helpers ===

    def list_captures(self, directory: str) -> dict:
        """List all .rdc files in a directory (non-recursive), with per-file
        validity. Directory is resolved as-is; relative paths OK.
        """
        d = Path(directory)
        if not d.exists():
            return {"error": f"Directory not found: {directory}"}
        if not d.is_dir():
            return {"error": f"Not a directory: {directory}"}
        out: list[dict] = []
        for entry in sorted(d.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".rdc":
                hdr = self.get_rdc_header(str(entry))
                out.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size": entry.stat().st_size,
                    "valid": hdr.get("valid", False),
                })
        return {"directory": str(d), "captures": out, "count": len(out)}

    def check_capture_count(self, directory: str, expected: str) -> dict:
        """Check the number of .rdc files in a directory equals expected."""
        try:
            expected_int = int(expected)
        except ValueError:
            return {"match": False, "error": f"Bad count: {expected}"}
        listing = self.list_captures(directory)
        if "error" in listing:
            return {"match": False, **listing}
        actual = listing.get("count", 0)
        return {"match": actual == expected_int, "expected": expected_int,
                "actual": actual, "directory": listing.get("directory")}

    def check_file_exists(self, path: str) -> dict:
        """Generic: does this path exist on disk?"""
        p = Path(path)
        exists = p.exists()
        result = {"exists": exists, "path": str(p)}
        if exists:
            try:
                result["size"] = p.stat().st_size
                result["is_file"] = p.is_file()
                result["is_dir"] = p.is_dir()
            except OSError:
                pass
        return result

    def file_info(self, path: str) -> dict:
        """Return path, size, is_file, is_dir for any path."""
        return self.check_file_exists(path)

    # === UI.config convenience views ===

    def get_theme(self) -> dict:
        """Return the UI theme name from UI.config (`UIStyle` key).

        Known values: "", "Default", "Light", "Dark".
        """
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return data
        style = data.get("UIStyle", "") if isinstance(data, dict) else ""
        return {"theme": style}

    def check_theme(self, expected: str) -> dict:
        """Check UIStyle == expected (case-sensitive)."""
        t = self.get_theme()
        if "error" in t:
            return {**t, "match": False, "expected": expected}
        return {"match": t.get("theme") == expected,
                "expected": expected, "actual": t.get("theme")}

    def get_font_scale(self) -> dict:
        """Return `Font_GlobalScale` from UI.config (float, default 1.0)."""
        data = self.get_config()
        if isinstance(data, dict) and "error" in data:
            return data
        scale = data.get("Font_GlobalScale", 1.0) if isinstance(data, dict) else 1.0
        return {"scale": scale}

    def check_font_scale(self, expected: str) -> dict:
        """Check Font_GlobalScale matches expected (float comparison with tiny epsilon)."""
        try:
            expected_val = float(expected)
        except ValueError:
            return {"match": False, "error": f"Bad float: {expected}"}
        fs = self.get_font_scale()
        if "error" in fs:
            return {**fs, "match": False, "expected": expected_val}
        actual = fs.get("scale")
        try:
            match = abs(float(actual) - expected_val) < 1e-6
        except (TypeError, ValueError):
            match = False
        return {"match": match, "expected": expected_val, "actual": actual}

    # === renderdoccmd subprocess ===

    def _rdcmd_path(self) -> str | None:
        env_path = os.environ.get("RENDERDOCCMD")
        if env_path and Path(env_path).exists():
            return env_path
        for cand in ("renderdoccmd",
                     "/usr/local/bin/renderdoccmd",
                     "/opt/renderdoc/renderdoccmd"):
            found = shutil.which(cand) if "/" not in cand else (cand if Path(cand).exists() else None)
            if found:
                return found
        # Fallback: search /opt for any renderdoc_*/renderdoccmd
        opt = Path("/opt")
        if opt.exists():
            for d in sorted(opt.iterdir()):
                cand = d / "renderdoccmd"
                if cand.exists():
                    return str(cand)
                cand2 = d / "bin" / "renderdoccmd"
                if cand2.exists():
                    return str(cand2)
        return None

    def _run_rdcmd(self, args: list[str], timeout: int = 20) -> dict:
        bin_path = self._rdcmd_path()
        if not bin_path:
            return {"error": "renderdoccmd not found on PATH or /opt"}
        try:
            proc = subprocess.run(
                [bin_path, *args],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"renderdoccmd {args[0] if args else ''} timed out"}
        except OSError as e:
            return {"error": f"Cannot invoke renderdoccmd: {e}"}
        return {
            "binary": bin_path,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def rdcmd_available(self) -> dict:
        p = self._rdcmd_path()
        return {"available": p is not None, "path": p}

    def rdcmd_version(self) -> dict:
        r = self._run_rdcmd(["version"])
        if "error" in r:
            return r
        text = (r["stdout"] or "") + "\n" + (r["stderr"] or "")
        # Parse lines like "RenderDoc v1.36 (git sha xxx)" and supported APIs
        version = None
        m = re.search(r"[Vv]?(\d+\.\d+(?:\.\d+)?)", text)
        if m:
            version = m.group(1)
        git_sha = None
        m = re.search(r"([a-f0-9]{7,40})", text)
        if m:
            git_sha = m.group(1)
        apis: list[str] = []
        for name in ("Vulkan", "GL", "GLES", "D3D11", "D3D12", "OpenGL"):
            if re.search(rf"\b{name}\b", text):
                apis.append(name)
        return {"version": version, "git_sha": git_sha, "apis": sorted(set(apis)),
                "raw": text.strip()[:600], "binary": r.get("binary")}

    def check_rdcmd_version(self, expected: str) -> dict:
        """Check parsed renderdoccmd version starts with `expected` (e.g. '1.36')."""
        v = self.rdcmd_version()
        if "error" in v:
            return {**v, "match": False, "expected": expected}
        actual = v.get("version") or ""
        return {"match": actual.startswith(expected),
                "expected": expected, "actual": actual}

    def rdcmd_plugins(self) -> dict:
        """List plugin subdirectories under the renderdoccmd install tree."""
        p = self._rdcmd_path()
        if not p:
            return {"error": "renderdoccmd not found"}
        # Candidate plugin dirs
        base = Path(p).resolve().parent
        candidates = [
            base / "plugins",
            base.parent / "share" / "renderdoc" / "plugins",
            base / "share" / "renderdoc" / "plugins",
            Path("/usr/share/renderdoc/plugins"),
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                entries = sorted([e.name for e in c.iterdir() if e.is_dir()])
                return {"plugins_dir": str(c), "plugins": entries, "count": len(entries)}
        return {"plugins_dir": None, "plugins": [], "count": 0,
                "note": "No renderdoc plugins directory found"}

    def check_rdcmd_plugin(self, name: str) -> dict:
        info = self.rdcmd_plugins()
        if "error" in info:
            return {**info, "present": False, "plugin": name}
        present = name in info.get("plugins", [])
        return {"present": present, "plugin": name,
                "plugins_dir": info.get("plugins_dir"),
                "available_plugins": info.get("plugins", [])}

    def vulkan_layer_status(self) -> dict:
        """Look for renderdoc's implicit Vulkan capture layer JSON."""
        candidates: list[Path] = []
        for root in ("/opt", "/usr/local/share", "/usr/share", "/etc"):
            rootp = Path(root)
            if not rootp.exists():
                continue
            for sub in rootp.rglob("renderdoc_capture.json"):
                candidates.append(sub)
                if len(candidates) > 5:
                    break
            if len(candidates) > 5:
                break
        # Also check the standard user dirs
        for extra in (
            Path.home() / ".local/share/vulkan/implicit_layer.d/renderdoc_capture.json",
            Path("/usr/share/vulkan/implicit_layer.d/renderdoc_capture.json"),
            Path("/etc/vulkan/implicit_layer.d/renderdoc_capture.json"),
        ):
            if extra.exists() and extra not in candidates:
                candidates.append(extra)
        return {"registered": len(candidates) > 0,
                "layer_files": [str(c) for c in candidates],
                "count": len(candidates)}

    # === .rdc structured inspection via renderdoccmd ===

    def rdc_sections(self, path: str) -> dict:
        """List embedded sections of an .rdc capture via `renderdoccmd extract`."""
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        r = self._run_rdcmd(["extract", "--list-sections", str(p)])
        if "error" in r:
            return r
        text = (r.get("stdout") or "") + "\n" + (r.get("stderr") or "")
        # Output lines typically look like "Section 0: <Name> (type=..., version=...)"
        sections: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Accept any line that contains a colon and looks section-ish
            m = re.match(r"^(?:Section\s+\d+[:\s]+)?([A-Za-z][\w./-]*)", line)
            if m and (":" in line or "Section" in line or "type" in line.lower()):
                name = m.group(1)
                if name.lower() not in ("usage", "error"):
                    sections.append(name)
        # De-dup preserve order
        seen: set[str] = set()
        unique: list[str] = []
        for s in sections:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return {"path": str(p), "sections": unique, "count": len(unique),
                "exit_code": r.get("exit_code"), "raw": text.strip()[:800]}

    def check_rdc_has_section(self, path: str, section: str) -> dict:
        info = self.rdc_sections(path)
        if "error" in info:
            return {**info, "present": False, "section": section}
        sects = info.get("sections", [])
        present = any(section.lower() in s.lower() for s in sects)
        return {"present": present, "section": section,
                "sections": sects, "path": info.get("path")}

    def rdc_extract_thumbnail(self, path: str, out_path: str) -> dict:
        """Extract the embedded thumbnail PNG/JPG from a capture."""
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        outp = Path(out_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        # renderdoccmd thumb -o OUT FILE
        r = self._run_rdcmd(["thumb", "-o", str(outp), str(p)])
        if "error" in r:
            return r
        exists = outp.exists()
        size = outp.stat().st_size if exists else 0
        # Sniff format by first bytes
        fmt = None
        if exists and size >= 8:
            with open(outp, "rb") as f:
                head = f.read(8)
            if head.startswith(b"\x89PNG"):
                fmt = "png"
            elif head.startswith(b"\xff\xd8\xff"):
                fmt = "jpg"
            elif head.startswith(b"BM"):
                fmt = "bmp"
        return {"extracted": exists and size > 0,
                "out_path": str(outp), "size": size, "format": fmt,
                "exit_code": r.get("exit_code"),
                "stderr": (r.get("stderr") or "").strip()[:400]}

    def check_rdc_has_thumbnail(self, path: str) -> dict:
        out = f"/tmp/_rd_thumb_{os.getpid()}.png"
        r = self.rdc_extract_thumbnail(path, out)
        try:
            Path(out).unlink(missing_ok=True)
        except OSError:
            pass
        if "error" in r and "extracted" not in r:
            return {**r, "has_thumbnail": False, "path": path}
        return {"has_thumbnail": bool(r.get("extracted")),
                "path": path, "format": r.get("format"),
                "size": r.get("size", 0)}

    def rdc_convert_xml(self, path: str, out_path: str | None = None) -> dict:
        """Convert a capture to structured XML and summarise."""
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        outp = Path(out_path) if out_path else Path(f"/tmp/_rd_convert_{os.getpid()}.xml")
        outp.parent.mkdir(parents=True, exist_ok=True)
        r = self._run_rdcmd(
            ["convert", "-f", str(p), "-o", str(outp), "-c", "xml"],
            timeout=60,
        )
        if "error" in r:
            return r
        if not outp.exists() or outp.stat().st_size == 0:
            return {"error": "renderdoccmd convert produced no XML output",
                    "exit_code": r.get("exit_code"),
                    "stderr": (r.get("stderr") or "")[:400]}
        try:
            with open(outp, encoding="utf-8", errors="replace") as f:
                xml = f.read()
        except OSError as e:
            return {"error": f"Cannot read XML output: {e}"}
        # Lightweight summary — avoid a full XML parse so we don't care about
        # renderdoccmd's exact schema version.
        api = None
        for api_name in ("Vulkan", "D3D12", "D3D11", "OpenGL", "GLES", "GL"):
            if f'"{api_name}"' in xml or f">{api_name}<" in xml or f"api=\"{api_name}\"" in xml:
                api = api_name
                break
        if api is None:
            m = re.search(r"api\s*=\s*['\"]([A-Za-z0-9]+)['\"]", xml)
            if m:
                api = m.group(1)
        chunks = len(re.findall(r"<chunk\b", xml, re.IGNORECASE))
        events = len(re.findall(r"<event\b", xml, re.IGNORECASE))
        resources = len(re.findall(r"<resource\b", xml, re.IGNORECASE))
        actions = len(re.findall(r"<action\b", xml, re.IGNORECASE))
        return {"xml_path": str(outp), "size": outp.stat().st_size,
                "api": api, "chunks": chunks, "events": events,
                "resources": resources, "actions": actions,
                "exit_code": r.get("exit_code")}

    def check_rdc_api(self, path: str, expected_api: str) -> dict:
        info = self.rdc_convert_xml(path)
        if "error" in info:
            return {**info, "match": False, "expected": expected_api}
        actual = info.get("api")
        match = (actual or "").lower() == expected_api.lower()
        return {"match": match, "expected": expected_api, "actual": actual,
                "path": path}

    def check_rdc_min_chunks(self, path: str, minimum: str) -> dict:
        try:
            n = int(minimum)
        except ValueError:
            return {"match": False, "error": f"Bad minimum: {minimum}"}
        info = self.rdc_convert_xml(path)
        if "error" in info:
            return {**info, "match": False, "min": n}
        chunks = info.get("chunks", 0)
        return {"match": chunks >= n, "min": n, "actual": chunks, "path": path}

    # === .cap capture-settings JSON ===

    def cap_parse(self, path: str) -> dict:
        """Parse a qrenderdoc .cap capture-settings file (JSON)."""
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not p.is_file():
            return {"error": f"Not a file: {path}"}
        data = _read_json_file(p)
        if isinstance(data, dict) and "error" in data:
            return data
        if not isinstance(data, dict):
            return {"error": ".cap file is not a JSON object"}
        # Normalise common fields — qrenderdoc's CaptureSettings serialises to:
        #   rdocCaptureSettings (magic), settings { executable, workingDir,
        #   commandLine, environment[], options{}, inject, autoStart,
        #   queueFrameCap, numQueuedFrames }
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else data
        return {"path": str(p), "raw": data, "settings": settings,
                "executable": settings.get("executable"),
                "workingDir": settings.get("workingDir"),
                "commandLine": settings.get("commandLine"),
                "environment": settings.get("environment") or [],
                "options": settings.get("options") or {},
                "autoStart": settings.get("autoStart"),
                "queueFrameCap": settings.get("queueFrameCap"),
                "numQueuedFrames": settings.get("numQueuedFrames")}

    def check_cap_executable(self, path: str, expected: str) -> dict:
        d = self.cap_parse(path)
        if "error" in d:
            return {**d, "match": False, "expected": expected}
        actual = d.get("executable")
        return {"match": actual == expected, "expected": expected,
                "actual": actual, "path": d.get("path")}

    def check_cap_working_dir(self, path: str, expected: str) -> dict:
        d = self.cap_parse(path)
        if "error" in d:
            return {**d, "match": False, "expected": expected}
        actual = d.get("workingDir")
        return {"match": actual == expected, "expected": expected,
                "actual": actual, "path": d.get("path")}

    def check_cap_command_line(self, path: str, expected_substring: str) -> dict:
        d = self.cap_parse(path)
        if "error" in d:
            return {**d, "match": False, "substring": expected_substring}
        actual = d.get("commandLine") or ""
        return {"match": expected_substring in actual,
                "substring": expected_substring, "actual": actual,
                "path": d.get("path")}

    def check_cap_option(self, path: str, key: str, expected: str) -> dict:
        """Check one key inside the nested `options` dict."""
        expected_val = _parse_expected(expected)
        d = self.cap_parse(path)
        if "error" in d:
            return {**d, "match": False, "key": key, "expected": expected_val}
        opts = d.get("options") or {}
        if key not in opts:
            return {"match": False, "key": key, "expected": expected_val,
                    "actual": None, "error": f"Option '{key}' not set"}
        actual = opts[key]
        return {"match": actual == expected_val, "key": key,
                "expected": expected_val, "actual": actual}

    def check_cap_env(self, path: str, var_name: str) -> dict:
        """Check whether a named environment variable is set in the capture env list."""
        d = self.cap_parse(path)
        if "error" in d:
            return {**d, "present": False, "var": var_name}
        env = d.get("environment") or []
        # Entries can be dicts ({name, value, ...}) or "NAME=VALUE" strings
        found = None
        for e in env:
            if isinstance(e, dict):
                name = e.get("name") or e.get("variable")
                if name == var_name:
                    found = e
                    break
            elif isinstance(e, str):
                if e.split("=", 1)[0] == var_name:
                    found = e
                    break
        return {"present": found is not None, "var": var_name, "value": found,
                "env_count": len(env)}


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

COMMANDS: dict[str, tuple[str, Any]] = {
    # Config
    "config": ("Read UI.config (optional key)",
               lambda v, args: v.get_config(args[0] if args else None)),
    "config-keys": ("List all keys in UI.config",
                    lambda v, args: v.list_config_keys()),
    "check-setting": ("Check UI.config setting equals value",
                      lambda v, args: v.check_setting(args[0], args[1])),
    "check-setting-exists": ("Check a key exists in UI.config",
                             lambda v, args: v.check_setting_exists(args[0])),

    # Theme / font shortcuts
    "theme": ("Get UIStyle theme", lambda v, args: v.get_theme()),
    "check-theme": ("Check UIStyle equals value",
                    lambda v, args: v.check_theme(args[0])),
    "font-scale": ("Get Font_GlobalScale", lambda v, args: v.get_font_scale()),
    "check-font-scale": ("Check Font_GlobalScale equals value",
                         lambda v, args: v.check_font_scale(args[0])),

    # Recent captures
    "recent-captures": ("List RecentCaptureFiles",
                        lambda v, args: v.get_recent_captures()),
    "check-recent-capture": ("Check substring appears in RecentCaptureFiles",
                             lambda v, args: v.check_recent_capture(args[0])),
    "recent-settings": ("List RecentCaptureSettings",
                        lambda v, args: v.get_recent_settings()),

    # .rdc parsing
    "rdc-header": ("Parse a .rdc file header",
                   lambda v, args: v.get_rdc_header(args[0])),
    "check-rdc-valid": ("Check a path is a valid .rdc file",
                        lambda v, args: v.check_rdc_valid(args[0])),
    "check-rdc-version": ("Check a .rdc file's serialise_version",
                          lambda v, args: v.check_rdc_version(args[0], args[1])),

    # Filesystem
    "list-captures": ("List .rdc files in a directory",
                      lambda v, args: v.list_captures(args[0])),
    "check-capture-count": ("Check .rdc file count in a directory",
                            lambda v, args: v.check_capture_count(args[0], args[1])),
    "check-file-exists": ("Check a file exists",
                          lambda v, args: v.check_file_exists(args[0])),
    "file-info": ("Get info for a path",
                  lambda v, args: v.file_info(args[0])),

    # renderdoccmd (headless CLI)
    "rdcmd-available": ("Is renderdoccmd installed",
                        lambda v, args: v.rdcmd_available()),
    "rdcmd-version": ("Get renderdoccmd version + supported APIs",
                      lambda v, args: v.rdcmd_version()),
    "check-rdcmd-version": ("Check renderdoccmd version starts with value",
                            lambda v, args: v.check_rdcmd_version(args[0])),
    "rdcmd-plugins": ("List renderdoc plugins directory",
                      lambda v, args: v.rdcmd_plugins()),
    "check-rdcmd-plugin": ("Check a specific plugin is present",
                           lambda v, args: v.check_rdcmd_plugin(args[0])),
    "vulkan-layer-status": ("Check renderdoc vulkan capture layer is registered",
                            lambda v, args: v.vulkan_layer_status()),

    # .rdc structured inspection
    "rdc-sections": ("List embedded sections of a .rdc capture",
                     lambda v, args: v.rdc_sections(args[0])),
    "check-rdc-has-section": ("Check a capture has a named section",
                              lambda v, args: v.check_rdc_has_section(args[0], args[1])),
    "rdc-thumb": ("Extract embedded thumbnail to a path",
                  lambda v, args: v.rdc_extract_thumbnail(args[0], args[1])),
    "check-rdc-has-thumbnail": ("Check a capture has an embedded thumbnail",
                                lambda v, args: v.check_rdc_has_thumbnail(args[0])),
    "rdc-convert-xml": ("Convert a capture to structured XML + summary",
                        lambda v, args: v.rdc_convert_xml(args[0],
                                                           args[1] if len(args) > 1 else None)),
    "check-rdc-api": ("Check a capture's API (Vulkan, D3D12, OpenGL, ...)",
                      lambda v, args: v.check_rdc_api(args[0], args[1])),
    "check-rdc-min-chunks": ("Check a capture has >= N chunks",
                             lambda v, args: v.check_rdc_min_chunks(args[0], args[1])),

    # .cap capture-settings JSON
    "cap-parse": ("Parse a .cap capture-settings JSON file",
                  lambda v, args: v.cap_parse(args[0])),
    "check-cap-executable": ("Check .cap executable == value",
                             lambda v, args: v.check_cap_executable(args[0], args[1])),
    "check-cap-working-dir": ("Check .cap workingDir == value",
                              lambda v, args: v.check_cap_working_dir(args[0], args[1])),
    "check-cap-command-line": ("Check .cap commandLine contains substring",
                               lambda v, args: v.check_cap_command_line(args[0], args[1])),
    "check-cap-option": ("Check .cap options[<key>] == value",
                         lambda v, args: v.check_cap_option(args[0], args[1], args[2])),
    "check-cap-env": ("Check .cap environment has a named variable",
                      lambda v, args: v.check_cap_env(args[0], args[1])),
}


def _print_usage():
    print("RenderDoc Verifier — file-based inspection of UI.config + .rdc captures")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(n) for n in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nUI.config path: {UI_CONFIG_PATH}")
    print("\nAll output is JSON.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run --help for usage."}))
        sys.exit(1)
    verifier = RenderDocVerifier()
    _, handler = COMMANDS[cmd]
    try:
        result = handler(verifier, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    print(json.dumps(result, indent=2, default=str))
