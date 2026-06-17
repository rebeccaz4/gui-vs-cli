"""
Audacity Verifier - programmatic state inspection for Audacity 2.x projects.

The E2B `desktop-all-apps` template ships Audacity 2.4.2 (Ubuntu jammy package),
which stores projects as an **XML** `.aup` file plus a sibling `<name>_data/`
directory containing the audio block files. This verifier parses the `.aup`
XML directly -- no SQLite, no running Audacity instance required.

Verification channels (in order of preference):
  1. XML parsing of .aup project files (primary) -- extracts the <project>
     element's attributes (rate, snapto, selectionformat, etc.), every
     <wavetrack> and <labeltrack> and their attributes (name, channel,
     linked, mute, solo, rate, height, gain, pan), clip counts, and
     <tags> metadata (title, artist, album, year, genre, comments).
  2. INI parsing of ~/.audacity-data/audacity.cfg -- user preferences
     (theme, default sample rate, recording/playback, warnings, import
     defaults, effect settings, etc.). Plugin registry at
     ~/.audacity-data/pluginregistry.cfg is parsed the same way.
  3. ffprobe -- verify exported audio files (WAV, MP3, OGG, FLAC) for
     codec, sample rate, channel count, duration, bit rate.
  4. Plain file existence / size checks, including the `<project>_data/`
     directory audacity writes beside each .aup file.

Skipped categories (see README):
  - UI window layout: Audacity 2.x does not persist track-panel / toolbar
    layout in a reliably parseable way across sessions.
  - Keybindings: stored in audacity.cfg but flat and best treated as
    generic preferences (the generic `preference` endpoints expose them).
  - Plugin deep introspection: we enumerate the plugin registry but do
    not evaluate plugin internals.

Usage from outside the sandbox:
    sandbox.commands.run("python3 /home/user/verifiers/audacity.py project-info /path/to/song.aup")
    sandbox.commands.run("python3 /home/user/verifiers/audacity.py tracks /path/to/song.aup")
    sandbox.commands.run("python3 /home/user/verifiers/audacity.py check-track-count /path/to/song.aup 2")
    sandbox.commands.run("python3 /home/user/verifiers/audacity.py check-export-codec /path/to/out.wav pcm_s16le")

All endpoints return JSON to stdout. Errors become `{"error": "..."}`.
`check-*` endpoints return a dict with one primary boolean key
(`match` / `exists` / `valid`) plus context.

Requires stdlib only + ffprobe (present in desktop-all-apps).
"""

import array
import configparser
import json
import math
import os
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

AUDACITY_DATA_DIR = Path(os.environ.get(
    "AUDACITY_DATA_DIR",
    Path.home() / ".audacity-data",
))
AUDACITY_CFG = AUDACITY_DATA_DIR / "audacity.cfg"
PLUGIN_REGISTRY = AUDACITY_DATA_DIR / "pluginregistry.cfg"


# ---------------------------------------------------------------------------
# .aup XML helpers
# ---------------------------------------------------------------------------

AUP_NS = "http://audacity.sourceforge.net/xml/"


def _strip_ns(tag: str) -> str:
    """Return local-name portion of an ElementTree tag ('{ns}x' -> 'x')."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _assert_aup(filepath: str) -> Path:
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Project file not found: {filepath}")
    if p.suffix.lower() not in (".aup",):
        raise ValueError(f"Not an .aup file: {filepath}")
    return p


def _parse_aup(filepath: str) -> ET.Element:
    """Parse an .aup XML file and return the root <project> element."""
    _assert_aup(filepath)
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML in {filepath}: {e}")
    root = tree.getroot()
    if _strip_ns(root.tag) != "project":
        raise ValueError(f"Expected <project> root, got <{_strip_ns(root.tag)}>")
    return root


def _el_attrs(el: ET.Element) -> dict:
    """Return attribute dict with namespaces stripped."""
    return {_strip_ns(k): v for k, v in el.attrib.items()}


def _iter_local(el: ET.Element, name: str):
    """Iterate descendants with local name `name`."""
    for e in el.iter():
        if _strip_ns(e.tag) == name:
            yield e


def _get_wavetracks(root: ET.Element) -> list[dict]:
    tracks = []
    for idx, wt in enumerate(_iter_local(root, "wavetrack")):
        t = _el_attrs(wt)
        t["_index"] = idx
        # Count clips
        clips = list(_iter_local(wt, "waveclip"))
        t["_clip_count"] = len(clips)
        # Sum clip durations (in frames) if offsets/length available
        durations = []
        for clip in clips:
            ca = _el_attrs(clip)
            if "offset" in ca:
                t.setdefault("_clip_offsets", []).append(ca["offset"])
        # Count sequences
        seqs = list(_iter_local(wt, "sequence"))
        t["_sequence_count"] = len(seqs)
        # Numsamples aggregated from sequences if present
        total_ns = 0
        for sq in seqs:
            sa = _el_attrs(sq)
            ns = sa.get("numsamples", "")
            if ns.isdigit():
                total_ns += int(ns)
        t["_total_numsamples"] = total_ns
        tracks.append(t)
    return tracks


def _get_labeltracks(root: ET.Element) -> list[dict]:
    tracks = []
    for idx, lt in enumerate(_iter_local(root, "labeltrack")):
        t = _el_attrs(lt)
        t["_index"] = idx
        labels = []
        for lbl in _iter_local(lt, "label"):
            labels.append(_el_attrs(lbl))
        t["_labels"] = labels
        t["_label_count"] = len(labels)
        tracks.append(t)
    return tracks


def _get_notetracks(root: ET.Element) -> list[dict]:
    tracks = []
    for idx, nt in enumerate(_iter_local(root, "notetrack")):
        t = _el_attrs(nt)
        t["_index"] = idx
        tracks.append(t)
    return tracks


def _get_timetrack(root: ET.Element) -> list[dict]:
    tracks = []
    for idx, tt in enumerate(_iter_local(root, "timetrack")):
        t = _el_attrs(tt)
        t["_index"] = idx
        tracks.append(t)
    return tracks


def _get_tags(root: ET.Element) -> dict:
    """Extract <tags> metadata (title/artist/album/year/genre/comments)."""
    tags: dict = {}
    for tg in _iter_local(root, "tags"):
        for k, v in _el_attrs(tg).items():
            tags[k] = v
        # Audacity also stores each tag as a <tag name=.. value=..> child.
        for tag_el in _iter_local(tg, "tag"):
            ta = _el_attrs(tag_el)
            nm = ta.get("name")
            val = ta.get("value", "")
            if nm:
                tags[nm] = val
    return tags


def _get_project_attrs(root: ET.Element) -> dict:
    return _el_attrs(root)


def _count_blockfiles(root: ET.Element) -> int:
    """Count <simpleblockfile> / <silentblockfile> / <pcmaliasblockfile> references."""
    n = 0
    for kind in ("simpleblockfile", "silentblockfile", "pcmaliasblockfile"):
        n += sum(1 for _ in _iter_local(root, kind))
    return n


def _referenced_blockfiles(root: ET.Element) -> list[str]:
    refs: list[str] = []
    for kind in ("simpleblockfile", "silentblockfile", "pcmaliasblockfile"):
        for block in _iter_local(root, kind):
            filename = _el_attrs(block).get("filename", "")
            if filename:
                refs.append(filename)
    return refs


def _data_dir_for(aup_path: Path) -> Path:
    return aup_path.with_name(aup_path.stem + "_data")


# ---------------------------------------------------------------------------
# INI (audacity.cfg / pluginregistry.cfg) helpers
# ---------------------------------------------------------------------------

def _load_cfg(path: Path | None = None) -> tuple[configparser.ConfigParser | None, str | None]:
    p = Path(path) if path else AUDACITY_CFG
    if not p.exists():
        return None, f"Config file not found: {p}"
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str  # preserve case
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            cfg.read_file(f)
    except configparser.Error as e:
        return None, f"Cannot parse {p}: {e}"
    return cfg, None


# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------

def _run_ffprobe(filepath: str) -> dict:
    p = Path(filepath)
    if not p.exists():
        return {"error": f"File not found: {filepath}"}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", filepath],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"error": f"ffprobe failed: {result.stderr[:300]}"}
        return json.loads(result.stdout)
    except FileNotFoundError:
        return {"error": "ffprobe not found. Install ffmpeg."}
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out"}
    except json.JSONDecodeError:
        return {"error": "ffprobe returned invalid JSON"}


# ---------------------------------------------------------------------------
# Audio content analysis helpers (via ffmpeg decode to PCM16 mono)
# ---------------------------------------------------------------------------

def _decode_wav_mono_f32(filepath: str, start: float | None, end: float | None
                         ) -> tuple[list[float], int, str | None]:
    """Stdlib-only WAV decode (PCM16/PCM8/PCM24/PCM32 limited). Downmixes to mono."""
    import wave
    try:
        with wave.open(filepath, "rb") as wf:
            sr = wf.getframerate()
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            total = wf.getnframes()
            s0 = 0 if start is None else max(0, int(round(start * sr)))
            s1 = total if end is None else min(total, int(round(end * sr)))
            if s1 <= s0:
                return [], sr, None
            wf.setpos(s0)
            raw = wf.readframes(s1 - s0)
    except Exception as e:
        return [], 0, f"WAV decode failed: {e}"
    n = s1 - s0
    if sw == 2:
        vals = struct.unpack(f"<{n * nch}h", raw[: n * nch * 2])
        scale = 32768.0
    elif sw == 1:
        vals = [b - 128 for b in raw[: n * nch]]
        scale = 128.0
    elif sw == 4:
        vals = struct.unpack(f"<{n * nch}i", raw[: n * nch * 4])
        scale = 2147483648.0
    elif sw == 3:
        vals = []
        for i in range(n * nch):
            b = raw[i * 3: i * 3 + 3]
            v = int.from_bytes(b, "little", signed=True)
            vals.append(v)
        scale = 8388608.0
    else:
        return [], sr, f"Unsupported WAV sample width: {sw}"
    if nch == 1:
        samples = [v / scale for v in vals]
    else:
        samples = []
        for i in range(0, len(vals), nch):
            s = sum(vals[i: i + nch]) / nch
            samples.append(s / scale)
    return samples, sr, None


def _decode_region_mono_f32(filepath: str, start: float | None = None,
                            end: float | None = None,
                            target_rate: int = 44100) -> tuple[list[float], int, str | None]:
    """Decode a (possibly sliced) region of an audio file to mono float samples in [-1,1].

    Fast path: WAV via stdlib. Fallback: ffmpeg for MP3/OGG/FLAC.
    Returns (samples, sample_rate, error).
    """
    p = Path(filepath)
    if not p.exists():
        return [], 0, f"File not found: {filepath}"
    if p.suffix.lower() == ".wav":
        return _decode_wav_mono_f32(str(p), start, end)
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{float(start):.6f}"]
    cmd += ["-i", str(filepath)]
    if end is not None and start is not None:
        cmd += ["-t", f"{max(0.0, float(end) - float(start)):.6f}"]
    elif end is not None:
        cmd += ["-t", f"{float(end):.6f}"]
    cmd += [
        "-ac", "1",
        "-ar", str(int(target_rate)),
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
    except FileNotFoundError:
        return [], 0, "ffmpeg not found"
    except subprocess.TimeoutExpired:
        return [], 0, "ffmpeg timed out"
    if result.returncode != 0:
        return [], 0, f"ffmpeg failed: {result.stderr[:300].decode(errors='replace')}"
    raw = result.stdout
    if len(raw) < 2:
        return [], target_rate, None
    n = len(raw) // 2
    pcm = struct.unpack(f"<{n}h", raw[: n * 2])
    samples = [s / 32768.0 for s in pcm]
    return samples, target_rate, None


SILENCE_FLOOR_DB = -120.0


def _peak_db(samples: list[float]) -> float:
    if not samples:
        return SILENCE_FLOOR_DB
    peak = max(abs(s) for s in samples)
    if peak <= 0.0:
        return SILENCE_FLOOR_DB
    return 20.0 * math.log10(peak)


def _rms_db(samples: list[float]) -> float:
    if not samples:
        return SILENCE_FLOOR_DB
    total = 0.0
    for s in samples:
        total += s * s
    rms = math.sqrt(total / len(samples))
    if rms <= 0.0:
        return SILENCE_FLOOR_DB
    return 20.0 * math.log10(rms)


def _goertzel_mag(samples: list[float], sample_rate: int, freq: float) -> float:
    """Goertzel magnitude at a single frequency. Returns normalized magnitude."""
    n = len(samples)
    if n == 0 or sample_rate <= 0:
        return 0.0
    omega = 2.0 * math.pi * freq / sample_rate
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for x in samples:
        s = x + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return math.sqrt(max(0.0, power)) / max(1, n)


def _dominant_freq(samples: list[float], sample_rate: int,
                   fmin: float = 50.0, fmax: float | None = None,
                   step_hz: float = 5.0) -> float:
    """Scan candidate frequencies via Goertzel; return the frequency with max magnitude."""
    if not samples:
        return 0.0
    if fmax is None:
        fmax = sample_rate / 2.0 - 100.0
    best_f = 0.0
    best_mag = -1.0
    f = fmin
    # Coarse scan
    while f <= fmax:
        m = _goertzel_mag(samples, sample_rate, f)
        if m > best_mag:
            best_mag = m
            best_f = f
        f += step_hz
    # Refine around best
    refine_lo = max(fmin, best_f - step_hz)
    refine_hi = min(fmax, best_f + step_hz)
    f = refine_lo
    while f <= refine_hi:
        m = _goertzel_mag(samples, sample_rate, f)
        if m > best_mag:
            best_mag = m
            best_f = f
        f += 0.5
    return best_f


def _band_energy_ratio(samples: list[float], sample_rate: int,
                       cutoff_hz: float) -> float:
    """Energy ratio = (energy above cutoff) / (total energy), computed via simple
    one-pole high-pass vs total. Returns 0..1."""
    if not samples:
        return 0.0
    total_e = sum(s * s for s in samples)
    if total_e <= 0.0:
        return 0.0
    # One-pole high-pass filter
    # alpha = RC/(RC+dt); fc = 1/(2*pi*RC)
    dt = 1.0 / sample_rate
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    alpha = rc / (rc + dt)
    y_prev = 0.0
    x_prev = 0.0
    hp_e = 0.0
    for x in samples:
        y = alpha * (y_prev + x - x_prev)
        hp_e += y * y
        y_prev = y
        x_prev = x
    return hp_e / total_e


# ---------------------------------------------------------------------------
# AudacityVerifier class
# ---------------------------------------------------------------------------

class AudacityVerifier:
    """Stateless Audacity 2.x verifier. Each method is independent."""

    # === .aup queries ===================================================

    def get_project_info(self, filepath: str) -> dict:
        root = _parse_aup(filepath)
        attrs = _get_project_attrs(root)
        wavetracks = _get_wavetracks(root)
        labeltracks = _get_labeltracks(root)
        notetracks = _get_notetracks(root)
        timetracks = _get_timetrack(root)
        tags = _get_tags(root)
        p = Path(filepath)
        data_dir = _data_dir_for(p)
        return {
            "file": str(filepath),
            "size": p.stat().st_size,
            "attributes": attrs,
            "wavetrack_count": len(wavetracks),
            "labeltrack_count": len(labeltracks),
            "notetrack_count": len(notetracks),
            "timetrack_count": len(timetracks),
            "total_track_count": (
                len(wavetracks) + len(labeltracks) + len(notetracks) + len(timetracks)
            ),
            "track_names": [t.get("name", "") for t in wavetracks],
            "blockfile_count": _count_blockfiles(root),
            "tag_count": len(tags),
            "data_dir": str(data_dir),
            "data_dir_exists": data_dir.exists(),
        }

    def get_project_attrs(self, filepath: str) -> dict:
        return _get_project_attrs(_parse_aup(filepath))

    def get_tracks(self, filepath: str) -> list[dict]:
        return _get_wavetracks(_parse_aup(filepath))

    def get_track(self, filepath: str, index_or_name: str) -> dict:
        tracks = self.get_tracks(filepath)
        try:
            idx = int(index_or_name)
            if 0 <= idx < len(tracks):
                return tracks[idx]
            return {"error": f"Track index out of range: {idx} (have {len(tracks)})"}
        except ValueError:
            pass
        for t in tracks:
            if t.get("name", "") == index_or_name:
                return t
        return {"error": f"Track not found: {index_or_name}"}

    def get_label_tracks(self, filepath: str) -> list[dict]:
        return _get_labeltracks(_parse_aup(filepath))

    def get_labels(self, filepath: str) -> list[dict]:
        """Flat list of every label across every label track."""
        out: list[dict] = []
        for lt in _get_labeltracks(_parse_aup(filepath)):
            track_name = lt.get("name", "")
            for lbl in lt.get("_labels", []):
                out.append({
                    "track": track_name,
                    "title": lbl.get("title", ""),
                    "t": lbl.get("t", ""),
                    "t1": lbl.get("t1", ""),
                })
        return out

    def get_tags(self, filepath: str) -> dict:
        return _get_tags(_parse_aup(filepath))

    def get_note_tracks(self, filepath: str) -> list[dict]:
        return _get_notetracks(_parse_aup(filepath))

    def get_time_tracks(self, filepath: str) -> list[dict]:
        return _get_timetrack(_parse_aup(filepath))

    def get_blockfile_count(self, filepath: str) -> dict:
        return {"count": _count_blockfiles(_parse_aup(filepath))}

    def get_data_dir_info(self, filepath: str) -> dict:
        p = _assert_aup(filepath)
        data_dir = _data_dir_for(p)
        info: dict = {
            "data_dir": str(data_dir),
            "exists": data_dir.exists(),
        }
        if data_dir.exists():
            total = 0
            files = 0
            for sub in data_dir.rglob("*"):
                if sub.is_file():
                    files += 1
                    total += sub.stat().st_size
            info["file_count"] = files
            info["total_bytes"] = total
        return info

    # === preferences (audacity.cfg) ======================================

    def get_preferences(self, section: str | None = None, cfg_path: str | None = None) -> dict:
        cfg, err = _load_cfg(Path(cfg_path) if cfg_path else None)
        if err:
            return {"error": err}
        if section:
            if not cfg.has_section(section):
                return {"error": f"Section not found: {section}",
                        "sections": cfg.sections()}
            return {k: cfg.get(section, k) for k in cfg.options(section)}
        return {s: {k: cfg.get(s, k) for k in cfg.options(s)} for s in cfg.sections()}

    def get_preference(self, section: str, key: str, cfg_path: str | None = None) -> dict:
        cfg, err = _load_cfg(Path(cfg_path) if cfg_path else None)
        if err:
            return {"error": err}
        if not cfg.has_section(section):
            return {"error": f"Section not found: {section}"}
        if not cfg.has_option(section, key):
            return {"error": f"Key not found: {section}/{key}"}
        return {"section": section, "key": key, "value": cfg.get(section, key)}

    def list_preference_sections(self, cfg_path: str | None = None) -> list[str]:
        cfg, err = _load_cfg(Path(cfg_path) if cfg_path else None)
        if err:
            return []
        return cfg.sections()

    # === plugins =========================================================

    def get_plugins(self, registry_path: str | None = None) -> dict:
        p = Path(registry_path) if registry_path else PLUGIN_REGISTRY
        if not p.exists():
            return {"error": f"Plugin registry not found: {p}"}
        cfg = configparser.ConfigParser(strict=False, interpolation=None)
        cfg.optionxform = str
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                cfg.read_file(f)
        except configparser.Error as e:
            return {"error": f"Cannot parse plugin registry: {e}"}
        return {s: {k: cfg.get(s, k) for k in cfg.options(s)} for s in cfg.sections()}

    # === exports (ffprobe) ===============================================

    def get_export_info(self, filepath: str) -> dict:
        return _run_ffprobe(filepath)

    # === file checks =====================================================

    def check_file_exists(self, path: str) -> dict:
        p = Path(path)
        exists = p.exists()
        out: dict = {"exists": exists, "path": str(path)}
        if exists:
            out["size"] = p.stat().st_size
            out["is_file"] = p.is_file()
        return out

    def check_file_size_min(self, path: str, min_bytes: int) -> dict:
        p = Path(path)
        if not p.exists():
            return {"match": False, "error": f"File not found: {path}"}
        size = p.stat().st_size
        return {"match": size >= int(min_bytes), "size": size,
                "min_bytes": int(min_bytes)}

    # === .aup checks =====================================================

    def check_valid_aup(self, filepath: str) -> dict:
        p = Path(filepath)
        if not p.exists():
            return {"valid": False, "error": f"File not found: {filepath}"}
        if p.suffix.lower() != ".aup":
            return {"valid": False, "error": f"Wrong extension: {p.suffix}"}
        try:
            root = _parse_aup(filepath)
        except (ValueError, FileNotFoundError) as e:
            return {"valid": False, "error": str(e)}
        refs = _referenced_blockfiles(root)
        data_dir = _data_dir_for(p)
        if refs and not data_dir.exists():
            return {
                "valid": False,
                "error": f"Project data directory not found: {data_dir}",
            }
        missing = [
            filename for filename in refs
            if not any(candidate.is_file() for candidate in data_dir.rglob(filename))
        ]
        if missing:
            sample = ", ".join(missing[:3])
            suffix = "..." if len(missing) > 3 else ""
            return {
                "valid": False,
                "error": f"Missing blockfiles in {data_dir}: {sample}{suffix}",
            }
        attrs = _get_project_attrs(root)
        return {
            "valid": True,
            "audacity_version": attrs.get("audacityversion", ""),
            "project_version": attrs.get("projname", ""),
            "wavetracks": sum(1 for _ in _iter_local(root, "wavetrack")),
        }

    def check_track_count(self, filepath: str, expected: int) -> dict:
        tracks = self.get_tracks(filepath)
        actual = len(tracks)
        return {"match": actual == int(expected),
                "expected": int(expected), "actual": actual}

    def check_labeltrack_count(self, filepath: str, expected: int) -> dict:
        tracks = self.get_label_tracks(filepath)
        actual = len(tracks)
        return {"match": actual == int(expected),
                "expected": int(expected), "actual": actual}

    def check_track_name(self, filepath: str, name: str) -> dict:
        tracks = self.get_tracks(filepath)
        names = [t.get("name", "") for t in tracks]
        return {"match": name in names, "name": name, "names": names}

    def check_track_rate(self, filepath: str, expected_rate: int) -> dict:
        tracks = self.get_tracks(filepath)
        rates = []
        for t in tracks:
            r = t.get("rate", "")
            try:
                rates.append(int(r))
            except ValueError:
                pass
        return {
            "match": int(expected_rate) in rates,
            "expected": int(expected_rate),
            "rates": rates,
        }

    def check_project_rate(self, filepath: str, expected_rate: int) -> dict:
        attrs = self.get_project_attrs(filepath)
        raw = attrs.get("rate", "")
        try:
            actual = int(float(raw)) if raw else None
        except ValueError:
            actual = None
        return {
            "match": actual is not None and actual == int(expected_rate),
            "expected": int(expected_rate),
            "actual": actual,
        }

    def check_track_mute(self, filepath: str, index: int, muted: bool) -> dict:
        tracks = self.get_tracks(filepath)
        try:
            t = tracks[int(index)]
        except (IndexError, ValueError):
            return {"match": False, "error": f"Track {index} not found"}
        raw = t.get("mute", "0")
        actual = str(raw) in ("1", "true", "True")
        return {"match": actual == bool(muted),
                "expected": bool(muted), "actual": actual}

    def check_track_solo(self, filepath: str, index: int, solo: bool) -> dict:
        tracks = self.get_tracks(filepath)
        try:
            t = tracks[int(index)]
        except (IndexError, ValueError):
            return {"match": False, "error": f"Track {index} not found"}
        raw = t.get("solo", "0")
        actual = str(raw) in ("1", "true", "True")
        return {"match": actual == bool(solo),
                "expected": bool(solo), "actual": actual}

    def check_track_gain(self, filepath: str, index: int, expected_gain: float,
                         tolerance: float = 0.01) -> dict:
        tracks = self.get_tracks(filepath)
        try:
            t = tracks[int(index)]
        except (IndexError, ValueError):
            return {"match": False, "error": f"Track {index} not found"}
        try:
            actual = float(t.get("gain", "0"))
        except ValueError:
            actual = 0.0
        return {
            "match": abs(actual - float(expected_gain)) <= float(tolerance),
            "expected": float(expected_gain),
            "actual": actual,
        }

    def check_track_pan(self, filepath: str, index: int, expected_pan: float,
                        tolerance: float = 0.01) -> dict:
        tracks = self.get_tracks(filepath)
        try:
            t = tracks[int(index)]
        except (IndexError, ValueError):
            return {"match": False, "error": f"Track {index} not found"}
        try:
            actual = float(t.get("pan", "0"))
        except ValueError:
            actual = 0.0
        return {
            "match": abs(actual - float(expected_pan)) <= float(tolerance),
            "expected": float(expected_pan),
            "actual": actual,
        }

    def check_snapto(self, filepath: str, expected: str) -> dict:
        attrs = self.get_project_attrs(filepath)
        actual = attrs.get("snapto", "")
        return {"match": str(actual) == str(expected),
                "expected": expected, "actual": actual}

    def check_selection_format(self, filepath: str, expected: str) -> dict:
        """Check <project selectionformat=..> attribute (e.g. 'hh:mm:ss')."""
        attrs = self.get_project_attrs(filepath)
        actual = attrs.get("selectionformat", "")
        return {"match": str(actual) == str(expected),
                "expected": expected, "actual": actual}

    def check_blockfile_count_min(self, filepath: str, min_count: int) -> dict:
        n = _count_blockfiles(_parse_aup(filepath))
        return {"match": n >= int(min_count), "count": n,
                "min_count": int(min_count)}

    def check_label_exists(self, filepath: str, title: str) -> dict:
        labels = self.get_labels(filepath)
        titles = [l.get("title", "") for l in labels]
        return {"match": title in titles, "title": title, "titles": titles}

    def check_label_count(self, filepath: str, expected: int) -> dict:
        labels = self.get_labels(filepath)
        actual = len(labels)
        return {"match": actual == int(expected),
                "expected": int(expected), "actual": actual}

    def check_data_dir_exists(self, filepath: str) -> dict:
        p = _assert_aup(filepath)
        data_dir = _data_dir_for(p)
        return {"exists": data_dir.exists(), "path": str(data_dir)}

    # === tag (metadata) checks ==========================================

    def check_tag_value(self, filepath: str, name: str, expected: str) -> dict:
        tags = self.get_tags(filepath)
        lookup = {k.lower(): v for k, v in tags.items()}
        actual = lookup.get(name.lower(), "")
        return {
            "match": str(actual) == str(expected),
            "name": name,
            "expected": expected,
            "actual": actual,
        }

    def check_tag_contains(self, filepath: str, name: str, substring: str) -> dict:
        tags = self.get_tags(filepath)
        lookup = {k.lower(): v for k, v in tags.items()}
        actual = lookup.get(name.lower(), "")
        return {
            "match": substring.lower() in str(actual).lower(),
            "name": name,
            "substring": substring,
            "actual": actual,
        }

    # === preference checks ==============================================

    def check_preference(self, section: str, key: str, expected: str,
                         cfg_path: str | None = None) -> dict:
        cfg, err = _load_cfg(Path(cfg_path) if cfg_path else None)
        if err:
            return {"match": False, "error": err}
        if not cfg.has_section(section):
            return {"match": False, "error": f"Section not found: {section}"}
        if not cfg.has_option(section, key):
            return {"match": False, "error": f"Key not found: {section}/{key}"}
        actual = cfg.get(section, key)
        return {
            "match": str(actual) == str(expected),
            "section": section, "key": key,
            "expected": expected, "actual": actual,
        }

    def check_preference_exists(self, section: str, key: str,
                                cfg_path: str | None = None) -> dict:
        cfg, err = _load_cfg(Path(cfg_path) if cfg_path else None)
        if err:
            return {"exists": False, "error": err}
        exists = cfg.has_section(section) and cfg.has_option(section, key)
        val = cfg.get(section, key) if exists else None
        return {"exists": exists, "section": section, "key": key, "value": val}

    # === export (ffprobe) checks ========================================

    def check_export_exists(self, filepath: str) -> dict:
        p = Path(filepath)
        if not p.exists():
            return {"valid": False, "error": f"File not found: {filepath}"}
        if p.stat().st_size == 0:
            return {"valid": False, "error": f"File is empty: {filepath}"}
        probe = _run_ffprobe(filepath)
        if "error" in probe:
            return {"valid": False, **probe}
        streams = probe.get("streams", [])
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        return {
            "valid": len(audio) >= 1,
            "path": str(filepath),
            "size": p.stat().st_size,
            "codec": audio[0].get("codec_name") if audio else None,
            "sample_rate": int(audio[0].get("sample_rate", 0)) if audio else 0,
            "channels": audio[0].get("channels") if audio else 0,
            "duration": probe.get("format", {}).get("duration"),
        }

    def check_export_codec(self, filepath: str, codec: str) -> dict:
        probe = _run_ffprobe(filepath)
        if "error" in probe:
            return {"match": False, **probe}
        for s in probe.get("streams", []):
            if s.get("codec_type") == "audio":
                actual = s.get("codec_name", "")
                return {"match": actual == codec,
                        "expected": codec, "actual": actual}
        return {"match": False, "error": "No audio stream found"}

    def check_export_sample_rate(self, filepath: str, sample_rate: int) -> dict:
        probe = _run_ffprobe(filepath)
        if "error" in probe:
            return {"match": False, **probe}
        for s in probe.get("streams", []):
            if s.get("codec_type") == "audio":
                try:
                    actual = int(s.get("sample_rate", 0))
                except (TypeError, ValueError):
                    actual = 0
                return {"match": actual == int(sample_rate),
                        "expected": int(sample_rate), "actual": actual}
        return {"match": False, "error": "No audio stream found"}

    def check_export_channels(self, filepath: str, channels: int) -> dict:
        probe = _run_ffprobe(filepath)
        if "error" in probe:
            return {"match": False, **probe}
        for s in probe.get("streams", []):
            if s.get("codec_type") == "audio":
                actual = s.get("channels", 0)
                return {"match": actual == int(channels),
                        "expected": int(channels), "actual": actual}
        return {"match": False, "error": "No audio stream found"}

    def check_export_duration_min(self, filepath: str, min_seconds: float) -> dict:
        probe = _run_ffprobe(filepath)
        if "error" in probe:
            return {"match": False, **probe}
        dur_str = probe.get("format", {}).get("duration", "0")
        try:
            dur = float(dur_str)
        except (TypeError, ValueError):
            dur = 0.0
        return {"match": dur >= float(min_seconds),
                "duration": dur, "min_seconds": float(min_seconds)}

    def check_export_format(self, filepath: str, format_name: str) -> dict:
        probe = _run_ffprobe(filepath)
        if "error" in probe:
            return {"match": False, **probe}
        actual = probe.get("format", {}).get("format_name", "")
        parts = [s.strip() for s in actual.split(",")]
        return {"match": format_name in parts,
                "expected": format_name, "actual": actual}

    # === audio content checks (PCM decode + analysis) ===================

    def check_export_peak_db(self, filepath: str, min_db: float, max_db: float) -> dict:
        samples, sr, err = _decode_region_mono_f32(filepath)
        if err:
            return {"match": False, "error": err}
        peak = _peak_db(samples)
        ok = float(min_db) <= peak <= float(max_db)
        return {"match": ok, "peak_db": peak,
                "min_db": float(min_db), "max_db": float(max_db)}

    def check_export_region_silent(self, filepath: str, start: float, end: float,
                                   max_rms_db: float) -> dict:
        samples, sr, err = _decode_region_mono_f32(filepath, float(start), float(end))
        if err:
            return {"match": False, "error": err}
        rms = _rms_db(samples)
        ok = rms <= float(max_rms_db)
        return {"match": ok, "rms_db": rms,
                "max_rms_db": float(max_rms_db),
                "start": float(start), "end": float(end)}

    def check_export_region_rms_db(self, filepath: str, start: float, end: float,
                                   min_db: float, max_db: float) -> dict:
        samples, sr, err = _decode_region_mono_f32(filepath, float(start), float(end))
        if err:
            return {"match": False, "error": err}
        rms = _rms_db(samples)
        ok = float(min_db) <= rms <= float(max_db)
        return {"match": ok, "rms_db": rms,
                "min_db": float(min_db), "max_db": float(max_db),
                "start": float(start), "end": float(end)}

    def check_export_dominant_freq(self, filepath: str, start: float, end: float,
                                   expected_hz: float, tolerance_pct: float) -> dict:
        samples, sr, err = _decode_region_mono_f32(filepath, float(start), float(end))
        if err:
            return {"match": False, "error": err}
        # Clamp scan range near expected for efficiency
        exp = float(expected_hz)
        tol = float(tolerance_pct)
        fmin = max(40.0, exp * (1.0 - tol / 100.0) * 0.5)
        fmax = min(sr / 2.0 - 100.0, exp * (1.0 + tol / 100.0) * 2.0)
        # Coarse step proportional to expected freq
        step = max(2.0, exp * 0.005)
        # Custom scan reusing helper
        f = fmin
        best_f = 0.0
        best_mag = -1.0
        while f <= fmax:
            m = _goertzel_mag(samples, sr, f)
            if m > best_mag:
                best_mag = m
                best_f = f
            f += step
        # Refine
        refine_lo = max(fmin, best_f - step)
        refine_hi = min(fmax, best_f + step)
        f = refine_lo
        while f <= refine_hi:
            m = _goertzel_mag(samples, sr, f)
            if m > best_mag:
                best_mag = m
                best_f = f
            f += 0.25
        diff_pct = abs(best_f - exp) / exp * 100.0 if exp > 0 else 100.0
        ok = diff_pct <= tol
        return {"match": ok, "dominant_hz": best_f,
                "expected_hz": exp, "tolerance_pct": tol,
                "diff_pct": diff_pct,
                "start": float(start), "end": float(end)}

    def check_export_band_energy_ratio_max(self, filepath: str, cutoff_hz: float,
                                           max_ratio: float) -> dict:
        """Fraction of energy above cutoff must be <= max_ratio."""
        samples, sr, err = _decode_region_mono_f32(filepath)
        if err:
            return {"match": False, "error": err}
        ratio = _band_energy_ratio(samples, sr, float(cutoff_hz))
        ok = ratio <= float(max_ratio)
        return {"match": ok, "ratio": ratio,
                "cutoff_hz": float(cutoff_hz),
                "max_ratio": float(max_ratio)}


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def _str2bool(v: str) -> bool:
    return str(v).lower() in ("1", "true", "yes", "y", "on")


COMMANDS = {
    # --- .aup queries ---
    "project-info":        ("Project info: attrs, counts, tags, data dir",  lambda v, a: v.get_project_info(a[0])),
    "project-attrs":       ("Top-level <project> attributes",                lambda v, a: v.get_project_attrs(a[0])),
    "tracks":              ("List wavetracks with attributes",               lambda v, a: v.get_tracks(a[0])),
    "track":               ("Single track by index or name",                 lambda v, a: v.get_track(a[0], a[1])),
    "label-tracks":        ("List label tracks",                             lambda v, a: v.get_label_tracks(a[0])),
    "labels":              ("Flat list of labels across all label tracks",   lambda v, a: v.get_labels(a[0])),
    "note-tracks":         ("List note tracks",                              lambda v, a: v.get_note_tracks(a[0])),
    "time-tracks":         ("List time tracks",                              lambda v, a: v.get_time_tracks(a[0])),
    "tags":                ("Project metadata tags",                         lambda v, a: v.get_tags(a[0])),
    "blockfile-count":     ("Count of block-file references",                lambda v, a: v.get_blockfile_count(a[0])),
    "data-dir-info":       ("Info about the <name>_data/ directory",         lambda v, a: v.get_data_dir_info(a[0])),

    # --- preferences ---
    "preferences":         ("All sections or one section",                   lambda v, a: v.get_preferences(a[0] if a else None)),
    "preference":          ("One preference value",                          lambda v, a: v.get_preference(a[0], a[1])),
    "preference-sections": ("All section names in audacity.cfg",             lambda v, a: v.list_preference_sections()),

    # --- plugins ---
    "plugins":             ("Parsed pluginregistry.cfg",                     lambda v, a: v.get_plugins()),

    # --- exports ---
    "export-info":         ("ffprobe JSON for an exported file",             lambda v, a: v.get_export_info(a[0])),

    # --- file checks ---
    "check-file-exists":   ("Check file exists",                              lambda v, a: v.check_file_exists(a[0])),
    "check-file-size-min": ("Check file size >= min_bytes",                   lambda v, a: v.check_file_size_min(a[0], int(a[1]))),

    # --- .aup checks ---
    "check-valid-aup":     ("Check .aup parses as an Audacity project",      lambda v, a: v.check_valid_aup(a[0])),
    "check-track-count":   ("Check wavetrack count",                          lambda v, a: v.check_track_count(a[0], int(a[1]))),
    "check-labeltrack-count": ("Check label track count",                     lambda v, a: v.check_labeltrack_count(a[0], int(a[1]))),
    "check-track-name":    ("Check a wavetrack with given name exists",       lambda v, a: v.check_track_name(a[0], a[1])),
    "check-track-rate":    ("Check at least one track has the given rate",    lambda v, a: v.check_track_rate(a[0], int(a[1]))),
    "check-project-rate":  ("Check <project rate=..> attribute",              lambda v, a: v.check_project_rate(a[0], int(a[1]))),
    "check-track-mute":    ("Check track mute state: idx true/false",         lambda v, a: v.check_track_mute(a[0], int(a[1]), _str2bool(a[2]))),
    "check-track-solo":    ("Check track solo state: idx true/false",         lambda v, a: v.check_track_solo(a[0], int(a[1]), _str2bool(a[2]))),
    "check-track-gain":    ("Check track gain (float)",                       lambda v, a: v.check_track_gain(a[0], int(a[1]), float(a[2]))),
    "check-track-pan":     ("Check track pan (float)",                        lambda v, a: v.check_track_pan(a[0], int(a[1]), float(a[2]))),
    "check-snapto":        ("Check <project snapto=..>",                      lambda v, a: v.check_snapto(a[0], a[1])),
    "check-selection-format": ("Check <project selectionformat=..>",          lambda v, a: v.check_selection_format(a[0], a[1])),
    "check-blockfile-count-min": ("Check block-file count >= min",            lambda v, a: v.check_blockfile_count_min(a[0], int(a[1]))),
    "check-label-exists":  ("Check a label with the given title exists",     lambda v, a: v.check_label_exists(a[0], a[1])),
    "check-label-count":   ("Check total label count across all label tracks", lambda v, a: v.check_label_count(a[0], int(a[1]))),
    "check-data-dir-exists": ("Check sibling <name>_data/ directory exists",  lambda v, a: v.check_data_dir_exists(a[0])),

    # --- tag (metadata) checks ---
    "check-tag-value":     ("Check tag has exact value",                      lambda v, a: v.check_tag_value(a[0], a[1], a[2])),
    "check-tag-contains":  ("Check tag value contains substring",             lambda v, a: v.check_tag_contains(a[0], a[1], a[2])),

    # --- preference checks ---
    "check-preference":    ("Check preference equals value",                  lambda v, a: v.check_preference(a[0], a[1], a[2])),
    "check-preference-exists": ("Check preference exists",                    lambda v, a: v.check_preference_exists(a[0], a[1])),

    # --- export checks ---
    "check-export-exists":       ("Check exported audio file is valid",      lambda v, a: v.check_export_exists(a[0])),
    "check-export-codec":        ("Check exported audio codec",               lambda v, a: v.check_export_codec(a[0], a[1])),
    "check-export-sample-rate":  ("Check exported sample rate",               lambda v, a: v.check_export_sample_rate(a[0], int(a[1]))),
    "check-export-channels":     ("Check exported channel count",             lambda v, a: v.check_export_channels(a[0], int(a[1]))),
    "check-export-duration-min": ("Check exported duration >= seconds",       lambda v, a: v.check_export_duration_min(a[0], float(a[1]))),
    "check-export-format":       ("Check exported container format",          lambda v, a: v.check_export_format(a[0], a[1])),

    # --- audio content checks (decoded PCM analysis) ---
    "check-export-peak-db":             ("Peak dBFS within [min,max]",                  lambda v, a: v.check_export_peak_db(a[0], float(a[1]), float(a[2]))),
    "check-export-region-silent":       ("Region RMS dBFS <= max",                      lambda v, a: v.check_export_region_silent(a[0], float(a[1]), float(a[2]), float(a[3]))),
    "check-export-region-rms-db":       ("Region RMS dBFS within [min,max]",            lambda v, a: v.check_export_region_rms_db(a[0], float(a[1]), float(a[2]), float(a[3]), float(a[4]))),
    "check-export-dominant-freq":       ("Dominant freq in region within tol%",         lambda v, a: v.check_export_dominant_freq(a[0], float(a[1]), float(a[2]), float(a[3]), float(a[4]))),
    "check-export-band-energy-ratio-max": ("Frac of energy above cutoff <= max_ratio",  lambda v, a: v.check_export_band_energy_ratio_max(a[0], float(a[1]), float(a[2]))),
}


def _print_usage():
    print("Audacity Verifier -- query Audacity 2.x project state for RL/eval reward signals.")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(n) for n in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. .aup files are XML; exports verified via ffprobe;")
    print("preferences live in ~/.audacity-data/audacity.cfg.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help."}))
        sys.exit(1)

    v = AudacityVerifier()
    _, handler = COMMANDS[cmd]
    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
