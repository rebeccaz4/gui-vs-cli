"""
MuseScore 3 Verifier — programmatic state inspection for MuseScore 3 files in E2B sandbox.

Verification channels:
  1. .mscz ZIP archive parsing — a .mscz is a ZIP containing a .mscx XML score file
     (and optional thumbnail / embedded fonts). We unzip and parse the inner XML.
  2. .mscx direct XML parsing — raw MuseScore XML scores can be parsed the same way.
  3. INI parsing — ~/.config/MuseScore/MuseScore3.ini (Qt-style .ini with backslash keys)
     exposes user preferences: theme, language, autosave, etc.
  4. Exported file parsing:
       - MIDI: stdlib byte-level parsing for track count, tempo, note count
       - MusicXML (.xml / .musicxml): ElementTree parsing
       - WAV: stdlib `wave` module for duration / channels / sample rate
       - PDF / PNG: file existence + basic header sniff

All public methods return dicts/lists serializable as JSON. The CLI prints JSON to
stdout for easy parsing by a check agent. Errors are reported as {"error": "..."}.

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/musescore3.py score-info /home/user/Documents/song.mscz")
    sandbox.commands.run("python3 /home/user/verifiers/musescore3.py check-tempo /home/user/Documents/song.mscz 120")

Dependencies: standard library only (zipfile, xml.etree.ElementTree, configparser,
wave, struct, os, sys, json).
"""

import configparser
import json
import os
import re
import struct
import sys
import wave
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

MUSESCORE_INI_DEFAULT = os.path.expanduser("~/.config/MuseScore/MuseScore3.ini")


def _read_mscx_from_mscz(mscz_path: str) -> bytes | None:
    """Return the bytes of the inner .mscx XML file inside a .mscz archive."""
    try:
        with zipfile.ZipFile(mscz_path, "r") as zf:
            # Find the first .mscx at archive root or in META-INF listing
            candidates = [n for n in zf.namelist() if n.endswith(".mscx")]
            if not candidates:
                return None
            # Prefer the one at archive root (no slash) if possible
            root_level = [n for n in candidates if "/" not in n]
            pick = root_level[0] if root_level else candidates[0]
            return zf.read(pick)
    except (zipfile.BadZipFile, FileNotFoundError, KeyError, OSError):
        return None


def _parse_score_xml(path: str) -> ET.Element | None:
    """Parse a MuseScore score from a .mscz or .mscx file. Returns root element."""
    if not os.path.isfile(path):
        return None
    try:
        if path.lower().endswith(".mscz"):
            data = _read_mscx_from_mscz(path)
            if data is None:
                return None
            return ET.fromstring(data)
        elif path.lower().endswith(".mscx"):
            with open(path, "rb") as f:
                return ET.fromstring(f.read())
        else:
            # Try mscz first, then mscx
            data = _read_mscx_from_mscz(path)
            if data is not None:
                return ET.fromstring(data)
            with open(path, "rb") as f:
                return ET.fromstring(f.read())
    except (ET.ParseError, OSError):
        return None


def _find_score_element(root: ET.Element) -> ET.Element | None:
    """Return the <Score> element (handles both <museScore><Score>... and direct <Score>).

    Must match the local tag exactly 'Score' — 'museScore' ends with 'Score' too.
    """
    root_local = _local(root.tag)
    if root_local == "Score":
        return root
    # Prefer direct child Score
    for child in root:
        if _local(child.tag) == "Score":
            return child
    # Fall back to any descendant whose local tag is exactly 'Score'
    for elem in root.iter():
        if _local(elem.tag) == "Score":
            return elem
    return None


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _get_first_child_text(parent: ET.Element, tag_name: str) -> str | None:
    for child in parent:
        if _local(child.tag) == tag_name:
            return (child.text or "").strip() if child.text else ""
    return None


def _iter_children(parent: ET.Element, tag_name: str):
    for child in parent:
        if _local(child.tag) == tag_name:
            yield child


# ---------------------------------------------------------------------------
# MuseScoreVerifier
# ---------------------------------------------------------------------------

class MuseScoreVerifier:
    """Stateless verifier for MuseScore 3 scores, config, and exports."""

    # === Score query endpoints ===

    def get_score_info(self, path: str) -> dict:
        """Return top-level score info: MuseScore version, program version, division."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        score = _find_score_element(root)
        if score is None:
            return {"error": "No <Score> element found"}

        info: dict[str, Any] = {
            "museScoreVersion": root.attrib.get("version", ""),
            "program_version": _get_first_child_text(score, "programVersion") or "",
            "program_revision": _get_first_child_text(score, "programRevision") or "",
            "division": _get_first_child_text(score, "Division") or "",
        }
        layer_tags = _get_first_child_text(score, "LayerTag")
        if layer_tags:
            info["layer_tag"] = layer_tags
        return info

    def get_metadata(self, path: str) -> dict:
        """Return metaTag values (workTitle, composer, etc.)."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        score = _find_score_element(root)
        if score is None:
            return {"error": "No <Score> element found"}

        meta: dict[str, str] = {}
        for child in score:
            if _local(child.tag) != "metaTag":
                continue
            name = child.attrib.get("name", "")
            value = (child.text or "").strip() if child.text else ""
            if name:
                meta[name] = value
        return meta

    def get_parts(self, path: str) -> list[dict]:
        """Return a list of Parts (instruments) with their instrument info."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        score = _find_score_element(root)
        if score is None:
            return [{"error": "No <Score> element found"}]

        parts: list[dict] = []
        for i, part in enumerate(_iter_children(score, "Part")):
            part_info: dict[str, Any] = {"index": i}
            # trackName on <Part> level
            tn = _get_first_child_text(part, "trackName")
            if tn is not None:
                part_info["trackName"] = tn
            # <Staff> children
            staves = []
            for staff in _iter_children(part, "Staff"):
                staves.append({"id": staff.attrib.get("id", "")})
            part_info["staff_count"] = len(staves)
            # <Instrument> child with longName / shortName / instrumentId
            for instr in _iter_children(part, "Instrument"):
                ln = _get_first_child_text(instr, "longName")
                sn = _get_first_child_text(instr, "shortName")
                iid = _get_first_child_text(instr, "instrumentId")
                tn2 = _get_first_child_text(instr, "trackName")
                if ln is not None:
                    part_info["longName"] = ln
                if sn is not None:
                    part_info["shortName"] = sn
                if iid is not None:
                    part_info["instrumentId"] = iid
                if tn2 is not None and "trackName" not in part_info:
                    part_info["trackName"] = tn2
            parts.append(part_info)
        return parts

    def get_staves(self, path: str) -> list[dict]:
        """Return the top-level <Staff> elements under <Score> (the playable staves).

        Each entry has the staff id and the count of <Measure> children in that staff.
        """
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        score = _find_score_element(root)
        if score is None:
            return [{"error": "No <Score> element found"}]

        staves: list[dict] = []
        for staff in _iter_children(score, "Staff"):
            sid = staff.attrib.get("id", "")
            measures = list(_iter_children(staff, "Measure"))
            staves.append({
                "id": sid,
                "measure_count": len(measures),
            })
        return staves

    def get_time_signature(self, path: str) -> dict:
        """Return the first TimeSig (sigN/sigD) encountered in the score."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        for elem in root.iter():
            if _local(elem.tag) != "TimeSig":
                continue
            sig_n = _get_first_child_text(elem, "sigN")
            sig_d = _get_first_child_text(elem, "sigD")
            return {
                "numerator": int(sig_n) if sig_n and sig_n.isdigit() else sig_n,
                "denominator": int(sig_d) if sig_d and sig_d.isdigit() else sig_d,
            }
        return {"error": "No TimeSig element found"}

    def get_key_signature(self, path: str) -> dict:
        """Return the first KeySig accidental count encountered in the score.

        Positive = sharps, negative = flats, 0 = C major / A minor.
        """
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        for elem in root.iter():
            if _local(elem.tag) != "KeySig":
                continue
            accidental = _get_first_child_text(elem, "accidental")
            if accidental is None:
                # Sometimes encoded as <concertKey> or direct text
                ck = _get_first_child_text(elem, "concertKey")
                if ck is not None:
                    try:
                        return {"accidental": int(ck)}
                    except ValueError:
                        return {"accidental": ck}
                continue
            try:
                return {"accidental": int(accidental)}
            except ValueError:
                return {"accidental": accidental}
        return {"error": "No KeySig element found"}

    def get_tempo(self, path: str) -> dict:
        """Return the first Tempo marking's BPM (derived from <tempo> which is beats/sec).

        MuseScore stores tempo as beats-per-second float. We multiply by 60 to get BPM.
        """
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        for elem in root.iter():
            if _local(elem.tag) != "Tempo":
                continue
            t = _get_first_child_text(elem, "tempo")
            text = _get_first_child_text(elem, "text") or ""
            if t is None:
                continue
            try:
                bps = float(t)
                bpm = round(bps * 60.0, 2)
                return {"bpm": bpm, "beats_per_second": bps, "text": text}
            except ValueError:
                return {"bpm": None, "raw": t, "text": text}
        return {"error": "No Tempo element found"}

    def get_measure_count(self, path: str) -> dict:
        """Return the number of <Measure> elements in the first staff (the bar count)."""
        staves = self.get_staves(path)
        if staves and isinstance(staves[0], dict) and "error" in staves[0]:
            return staves[0]
        if not staves:
            return {"measure_count": 0}
        return {"measure_count": staves[0].get("measure_count", 0)}

    def get_note_count(self, path: str) -> dict:
        """Return total count of <Note> elements across the whole score."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}

        count = 0
        for elem in root.iter():
            if _local(elem.tag) == "Note":
                count += 1
        return {"note_count": count}

    def get_lyrics(self, path: str) -> list[dict]:
        """Return all <Lyrics> text entries in the score."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]

        lyrics: list[dict] = []
        for elem in root.iter():
            if _local(elem.tag) != "Lyrics":
                continue
            text = _get_first_child_text(elem, "text") or ""
            syllabic = _get_first_child_text(elem, "syllabic") or ""
            lyrics.append({"text": text, "syllabic": syllabic})
        return lyrics

    def get_instruments(self, path: str) -> list[str]:
        """Return a simple list of instrument names (longName if present, else trackName)."""
        parts = self.get_parts(path)
        if parts and isinstance(parts[0], dict) and "error" in parts[0]:
            return parts
        names: list[str] = []
        for p in parts:
            name = p.get("longName") or p.get("trackName") or p.get("shortName") or ""
            names.append(name)
        return names

    # === Gap-coverage endpoints (articulations, dynamics, chord symbols,
    # hairpins, voltas, jumps/markers, layout, style, instrument changes,
    # pedal, fingerings) ===

    def _iter_measures_by_staff(self, root: ET.Element):
        """Yield (staff_index, measure_index_1based, measure_element)."""
        score = _find_score_element(root)
        if score is None:
            return
        for si, staff in enumerate(_iter_children(score, "Staff")):
            mi = 0
            for measure in _iter_children(staff, "Measure"):
                mi += 1
                yield si, mi, measure

    def get_articulations(self, path: str) -> list[dict]:
        """Return list of {measure, subtype} for every <Articulation> in the score."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for art in measure.iter():
                if _local(art.tag) != "Articulation":
                    continue
                sub = _get_first_child_text(art, "subtype") or ""
                out.append({"staff": si, "measure": mi, "subtype": sub})
        return out

    def check_articulation_in_measure(self, path: str, measure: int, subtype: str) -> dict:
        arts = self.get_articulations(path)
        if arts and isinstance(arts[0], dict) and "error" in arts[0]:
            return arts[0]
        found = any(a["measure"] == measure and subtype.lower() in a["subtype"].lower()
                    for a in arts)
        return {"match": found, "measure": measure, "subtype": subtype, "found": [a for a in arts if a["measure"] == measure]}

    def check_articulation_count(self, path: str, subtype: str, count: int) -> dict:
        arts = self.get_articulations(path)
        if arts and isinstance(arts[0], dict) and "error" in arts[0]:
            return arts[0]
        n = sum(1 for a in arts if subtype.lower() in a["subtype"].lower())
        return {"match": n == count, "expected": count, "actual": n, "subtype": subtype}

    def get_dynamics(self, path: str) -> list[dict]:
        """Return list of {measure, subtype} for <Dynamic> elements."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for dyn in measure.iter():
                if _local(dyn.tag) != "Dynamic":
                    continue
                sub = _get_first_child_text(dyn, "subtype") or ""
                out.append({"staff": si, "measure": mi, "subtype": sub})
        return out

    def check_dynamic_in_measure(self, path: str, measure: int, subtype: str) -> dict:
        dyns = self.get_dynamics(path)
        if dyns and isinstance(dyns[0], dict) and "error" in dyns[0]:
            return dyns[0]
        found = any(d["measure"] == measure and d["subtype"].lower() == subtype.lower()
                    for d in dyns)
        return {"match": found, "measure": measure, "subtype": subtype, "all": dyns}

    def get_hairpins(self, path: str) -> list[dict]:
        """Return list of hairpin spanners with subtype (0=crescendo, 1=decrescendo)."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for elem in root.iter():
            if _local(elem.tag) != "Hairpin":
                continue
            sub = _get_first_child_text(elem, "subtype") or ""
            out.append({"subtype": sub})
        return out

    def check_has_hairpin(self, path: str, subtype: str) -> dict:
        """subtype: 'crescendo' or 'decrescendo' (or numeric '0'/'1')."""
        hps = self.get_hairpins(path)
        if hps and isinstance(hps[0], dict) and "error" in hps[0]:
            return hps[0]
        target = subtype.lower()
        mapping = {"crescendo": "0", "decrescendo": "1", "cresc": "0", "decresc": "1"}
        num = mapping.get(target, target)
        found = any(h["subtype"] == num for h in hps)
        return {"match": found, "expected_subtype": subtype, "found_count": len(hps)}

    def get_chord_symbols(self, path: str) -> list[dict]:
        """Return list of {measure, text} for <Harmony>/chord-symbol elements."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for h in measure.iter():
                if _local(h.tag) != "Harmony":
                    continue
                name = _get_first_child_text(h, "name") or ""
                # Fallback: build from root + extension tags
                if not name:
                    root_tpc = _get_first_child_text(h, "root") or ""
                    name = root_tpc
                out.append({"staff": si, "measure": mi, "text": name})
        return out

    def check_chord_symbol_in_measure(self, path: str, measure: int, text: str) -> dict:
        syms = self.get_chord_symbols(path)
        if syms and isinstance(syms[0], dict) and "error" in syms[0]:
            return syms[0]
        found = any(s["measure"] == measure and s["text"].strip() == text.strip()
                    for s in syms)
        return {"match": found, "measure": measure, "expected": text,
                "all": [s for s in syms if s["measure"] == measure]}

    def get_voltas(self, path: str) -> list[dict]:
        """Return list of voltas as {measure} where the volta begins. Voltas are
        spanners; MuseScore stores them as <Volta> inside a measure."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for elem in measure.iter():
                if _local(elem.tag) == "Volta":
                    out.append({"staff": si, "measure": mi})
        return out

    def check_has_volta_at(self, path: str, measure: int) -> dict:
        vs = self.get_voltas(path)
        if vs and isinstance(vs[0], dict) and "error" in vs[0]:
            return vs[0]
        found = any(v["measure"] == measure for v in vs)
        return {"match": found, "measure": measure, "all": vs}

    def get_repeats(self, path: str) -> dict:
        """Return repeat information: start/end repeat counts and measures."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"} if not os.path.isfile(path) else {"error": "parse"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        starts = []
        ends = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            # startRepeat as a child element
            for child in measure:
                lt = _local(child.tag)
                if lt == "startRepeat":
                    starts.append(mi)
                elif lt == "endRepeat":
                    ends.append(mi)
                elif lt == "BarLine":
                    sub = _get_first_child_text(child, "subtype") or ""
                    if sub == "start-repeat":
                        starts.append(mi)
                    elif sub == "end-repeat":
                        ends.append(mi)
        return {"start_repeats": starts, "end_repeats": ends}

    def check_start_repeat_at(self, path: str, measure: int) -> dict:
        r = self.get_repeats(path)
        if "error" in r:
            return r
        return {"match": measure in r.get("start_repeats", []), "measure": measure, "all": r}

    def check_end_repeat_at(self, path: str, measure: int) -> dict:
        r = self.get_repeats(path)
        if "error" in r:
            return r
        return {"match": measure in r.get("end_repeats", []), "measure": measure, "all": r}

    def get_jumps_and_markers(self, path: str) -> dict:
        """Return list of Marker and Jump elements with their text/label."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        markers = []
        jumps = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for child in measure.iter():
                lt = _local(child.tag)
                if lt == "Marker":
                    text = _get_first_child_text(child, "text") or ""
                    label = _get_first_child_text(child, "label") or ""
                    markers.append({"measure": mi, "text": text, "label": label})
                elif lt == "Jump":
                    text = _get_first_child_text(child, "text") or ""
                    jumpTo = _get_first_child_text(child, "jumpTo") or ""
                    jumps.append({"measure": mi, "text": text, "jumpTo": jumpTo})
        return {"markers": markers, "jumps": jumps}

    def check_marker_text(self, path: str, text: str) -> dict:
        data = self.get_jumps_and_markers(path)
        if "error" in data:
            return data
        found = any(text.lower() in (m.get("text", "").lower()) for m in data["markers"])
        return {"match": found, "expected": text, "markers": data["markers"]}

    def check_jump_text(self, path: str, text: str) -> dict:
        data = self.get_jumps_and_markers(path)
        if "error" in data:
            return data
        found = any(text.lower() in (j.get("text", "").lower()) for j in data["jumps"])
        return {"match": found, "expected": text, "jumps": data["jumps"]}

    def get_layout_breaks(self, path: str) -> list[dict]:
        """Return list of LayoutBreak elements {measure, subtype}."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for child in measure.iter():
                if _local(child.tag) == "LayoutBreak":
                    sub = _get_first_child_text(child, "subtype") or ""
                    out.append({"measure": mi, "subtype": sub})
        return out

    def check_layout_break_at(self, path: str, measure: int, subtype: str = "line") -> dict:
        lbs = self.get_layout_breaks(path)
        if lbs and isinstance(lbs[0], dict) and "error" in lbs[0]:
            return lbs[0]
        found = any(b["measure"] == measure and b["subtype"].lower() == subtype.lower()
                    for b in lbs)
        return {"match": found, "measure": measure, "subtype": subtype, "all": lbs}

    def get_style(self, path: str) -> dict:
        """Return the <Style> block children as a flat dict."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        root = _parse_score_xml(path)
        if root is None:
            return {"error": f"Cannot parse MuseScore XML in {path}"}
        score = _find_score_element(root)
        if score is None:
            return {"error": "No Score element"}
        style_elem = None
        for c in score:
            if _local(c.tag) == "Style":
                style_elem = c
                break
        if style_elem is None:
            return {}
        out = {}
        for child in style_elem:
            out[_local(child.tag)] = (child.text or "").strip() if child.text else ""
        return out

    def check_style_value(self, path: str, key: str, expected: str, tolerance: float = 0.05) -> dict:
        st = self.get_style(path)
        if "error" in st:
            return st
        actual = st.get(key, "")
        match = False
        # Try numeric comparison within tolerance
        try:
            match = abs(float(actual) - float(expected)) <= tolerance
        except (ValueError, TypeError):
            match = str(actual).strip() == str(expected).strip()
        return {"match": match, "key": key, "expected": expected, "actual": actual}

    def get_instrument_changes(self, path: str) -> list[dict]:
        """Return list of InstrumentChange elements as {measure, text}."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for child in measure.iter():
                if _local(child.tag) == "InstrumentChange":
                    text = _get_first_child_text(child, "text") or ""
                    # Also look for nested Instrument/longName/instrumentId
                    instr_id = ""
                    long_name = ""
                    for sub in child.iter():
                        lt = _local(sub.tag)
                        if lt == "instrumentId":
                            instr_id = (sub.text or "").strip()
                        elif lt == "longName":
                            long_name = (sub.text or "").strip()
                    out.append({"measure": mi, "text": text,
                                "instrumentId": instr_id, "longName": long_name})
        return out

    def check_instrument_change_at(self, path: str, measure: int, name: str) -> dict:
        changes = self.get_instrument_changes(path)
        if changes and isinstance(changes[0], dict) and "error" in changes[0]:
            return changes[0]
        target = name.lower()
        found = any(
            c["measure"] == measure and (
                target in c.get("text", "").lower()
                or target in c.get("longName", "").lower()
                or target in c.get("instrumentId", "").lower()
            )
            for c in changes
        )
        return {"match": found, "measure": measure, "name": name, "all": changes}

    def get_pedals(self, path: str) -> list[dict]:
        """Return list of <Pedal> spanner elements attached to measures."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for child in measure.iter():
                if _local(child.tag) == "Pedal":
                    out.append({"staff": si, "measure": mi})
        return out

    def check_has_pedal(self, path: str) -> dict:
        ps = self.get_pedals(path)
        if ps and isinstance(ps[0], dict) and "error" in ps[0]:
            return ps[0]
        return {"match": len(ps) > 0, "count": len(ps), "pedals": ps}

    def get_fingerings(self, path: str) -> list[dict]:
        """Return list of <Fingering> elements with their text."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for child in measure.iter():
                if _local(child.tag) == "Fingering":
                    text = _get_first_child_text(child, "text") or ""
                    out.append({"staff": si, "measure": mi, "text": text})
        return out

    def check_fingering_count_in_measure(self, path: str, measure: int, count: int) -> dict:
        fgs = self.get_fingerings(path)
        if fgs and isinstance(fgs[0], dict) and "error" in fgs[0]:
            return fgs[0]
        n = sum(1 for f in fgs if f["measure"] == measure)
        return {"match": n >= count, "measure": measure, "expected_min": count, "actual": n, "all": fgs}

    def get_ornaments(self, path: str) -> list[dict]:
        """Return list of ornament elements (trills, mordents, turns) by searching
        both <Ornament> elements and articulation subtypes containing 'trill'/'mordent'/'turn'."""
        if not os.path.isfile(path):
            return [{"error": f"File not found: {path}"}]
        root = _parse_score_xml(path)
        if root is None:
            return [{"error": f"Cannot parse MuseScore XML in {path}"}]
        out = []
        for si, mi, measure in self._iter_measures_by_staff(root):
            for child in measure.iter():
                lt = _local(child.tag)
                if lt in ("Ornament", "Trill"):
                    sub = _get_first_child_text(child, "subtype") or lt.lower()
                    out.append({"staff": si, "measure": mi, "subtype": sub})
                elif lt == "Articulation":
                    sub = _get_first_child_text(child, "subtype") or ""
                    if any(k in sub.lower() for k in ["trill", "mordent", "turn"]):
                        out.append({"staff": si, "measure": mi, "subtype": sub})
        return out

    def check_has_ornament(self, path: str, measure: int, kind: str) -> dict:
        orns = self.get_ornaments(path)
        if orns and isinstance(orns[0], dict) and "error" in orns[0]:
            return orns[0]
        k = kind.lower()
        found = any(o["measure"] == measure and (k in o["subtype"].lower() or o["subtype"].lower() == k)
                    for o in orns)
        return {"match": found, "measure": measure, "kind": kind, "all": orns}

    # === Preferences / INI endpoints ===

    def _read_ini(self, ini_path: str | None = None) -> configparser.ConfigParser | dict:
        path = ini_path or MUSESCORE_INI_DEFAULT
        if not os.path.isfile(path):
            return {"error": f"INI file not found: {path}"}
        cp = configparser.ConfigParser()
        cp.optionxform = str  # preserve case
        try:
            cp.read(path, encoding="utf-8")
        except configparser.Error as e:
            return {"error": f"INI parse error: {e}"}
        return cp

    def get_preferences(self, ini_path: str | None = None) -> dict:
        """Return the full parsed MuseScore3.ini as a nested dict."""
        cp = self._read_ini(ini_path)
        if isinstance(cp, dict):
            return cp
        out: dict[str, dict[str, str]] = {}
        for section in cp.sections():
            out[section] = {k: v for k, v in cp.items(section)}
        return out

    def get_preference(self, key: str, ini_path: str | None = None) -> dict:
        """Return a single key's value. `key` uses dotted form: 'section.key_name'.

        Inside MuseScore3.ini keys contain backslashes (Qt style). We accept both
        'section.key\\subkey' and 'section.key/subkey' styles, and fall back to
        a case-insensitive substring match across all keys in the section.
        """
        cp = self._read_ini(ini_path)
        if isinstance(cp, dict):
            return cp

        if "." not in key:
            return {"error": "Key must be in 'section.key' form"}
        section, _, k = key.partition(".")
        if section not in cp:
            return {"error": f"Section not found: {section}", "available_sections": cp.sections()}

        # Exact match (case sensitive, as stored)
        if k in cp[section]:
            return {"section": section, "key": k, "value": cp[section][k]}

        # Qt ini keys often have backslashes. Try the literal-in-file form.
        backslash_form = k.replace("/", "\\")
        if backslash_form in cp[section]:
            return {"section": section, "key": backslash_form, "value": cp[section][backslash_form]}

        # Case-insensitive / slash/backslash-insensitive match
        def norm(s: str) -> str:
            return s.lower().replace("\\", "/")
        target = norm(k)
        for actual_key, val in cp[section].items():
            if norm(actual_key) == target:
                return {"section": section, "key": actual_key, "value": val}

        return {
            "error": f"Key not found: {key}",
            "available_keys": list(cp[section].keys()),
        }

    # === Check endpoints ===

    def check_file_exists(self, path: str) -> dict:
        exists = os.path.isfile(path)
        result: dict[str, Any] = {"exists": exists, "path": path}
        if exists:
            result["size_bytes"] = os.path.getsize(path)
        return result

    def check_meta_tag(self, path: str, name: str, expected: str) -> dict:
        """Check that metaTag[name] == expected."""
        meta = self.get_metadata(path)
        if "error" in meta:
            return meta
        actual = meta.get(name, "")
        return {
            "match": actual == expected,
            "name": name,
            "expected": expected,
            "actual": actual,
        }

    def check_has_meta_tag(self, path: str, name: str) -> dict:
        """Check that metaTag[name] exists and is non-empty."""
        meta = self.get_metadata(path)
        if "error" in meta:
            return meta
        val = meta.get(name, "")
        return {
            "exists": bool(val),
            "name": name,
            "value": val,
        }

    def check_time_signature(self, path: str, numerator: int, denominator: int) -> dict:
        ts = self.get_time_signature(path)
        if "error" in ts:
            return ts
        return {
            "match": ts.get("numerator") == numerator and ts.get("denominator") == denominator,
            "expected": [numerator, denominator],
            "actual": [ts.get("numerator"), ts.get("denominator")],
        }

    def check_key_signature(self, path: str, accidental: int) -> dict:
        ks = self.get_key_signature(path)
        if "error" in ks:
            return ks
        return {
            "match": ks.get("accidental") == accidental,
            "expected": accidental,
            "actual": ks.get("accidental"),
        }

    def check_tempo(self, path: str, bpm: float, tolerance: float = 0.5) -> dict:
        t = self.get_tempo(path)
        if "error" in t:
            return t
        actual = t.get("bpm")
        if actual is None:
            return {"match": False, "expected": bpm, "actual": None}
        return {
            "match": abs(float(actual) - float(bpm)) <= tolerance,
            "expected": float(bpm),
            "actual": float(actual),
        }

    def check_measure_count(self, path: str, count: int) -> dict:
        m = self.get_measure_count(path)
        if "error" in m:
            return m
        actual = m.get("measure_count", 0)
        return {
            "match": actual == count,
            "expected": count,
            "actual": actual,
        }

    def check_note_count(self, path: str, count: int) -> dict:
        n = self.get_note_count(path)
        if "error" in n:
            return n
        actual = n.get("note_count", 0)
        return {
            "match": actual == count,
            "expected": count,
            "actual": actual,
        }

    def check_note_count_at_least(self, path: str, count: int) -> dict:
        """Check that the score has AT LEAST the given number of notes."""
        n = self.get_note_count(path)
        if "error" in n:
            return n
        actual = n.get("note_count", 0)
        return {
            "match": actual >= count,
            "expected_min": count,
            "actual": actual,
        }

    def check_part_count(self, path: str, count: int) -> dict:
        parts = self.get_parts(path)
        if parts and isinstance(parts[0], dict) and "error" in parts[0]:
            return parts[0]
        actual = len(parts)
        return {"match": actual == count, "expected": count, "actual": actual}

    def check_instrument(self, path: str, name: str) -> dict:
        """Check that an instrument with the given longName / trackName exists in the score."""
        parts = self.get_parts(path)
        if parts and isinstance(parts[0], dict) and "error" in parts[0]:
            return parts[0]
        lname = name.strip().lower()
        found = False
        matched_on: str | None = None
        for p in parts:
            for k in ("longName", "trackName", "shortName", "instrumentId"):
                v = p.get(k, "")
                if isinstance(v, str) and v.strip().lower() == lname:
                    found = True
                    matched_on = k
                    break
            if found:
                break
        return {
            "exists": found,
            "instrument": name,
            "matched_on": matched_on,
            "available_instruments": [
                p.get("longName") or p.get("trackName") or p.get("shortName") or ""
                for p in parts
            ],
        }

    def check_has_lyrics(self, path: str) -> dict:
        lyrics = self.get_lyrics(path)
        if lyrics and isinstance(lyrics[0], dict) and "error" in lyrics[0]:
            return lyrics[0]
        return {"has_lyrics": len(lyrics) > 0, "count": len(lyrics)}

    def check_lyric_text(self, path: str, text: str) -> dict:
        """Check that at least one lyric syllable contains the given text (substring)."""
        lyrics = self.get_lyrics(path)
        if lyrics and isinstance(lyrics[0], dict) and "error" in lyrics[0]:
            return lyrics[0]
        needle = text.strip()
        found = any(needle in l.get("text", "") for l in lyrics)
        return {
            "match": found,
            "needle": needle,
            "lyric_count": len(lyrics),
        }

    def check_preference(self, key: str, expected: str, ini_path: str | None = None) -> dict:
        """Check that a preference (e.g. 'application.autoSaveInterval') equals expected.

        String comparison against the raw INI value. Booleans are stored as 'true'/'false'.
        """
        pref = self.get_preference(key, ini_path)
        if "error" in pref:
            return pref
        actual = pref.get("value", "")
        # Strip surrounding quotes if present (Qt sometimes quotes strings)
        actual_stripped = actual.strip()
        if len(actual_stripped) >= 2 and actual_stripped[0] == actual_stripped[-1] == '"':
            actual_stripped = actual_stripped[1:-1]
        return {
            "match": actual_stripped == expected or actual == expected,
            "key": key,
            "expected": expected,
            "actual": actual,
        }

    def check_preference_exists(self, key: str, ini_path: str | None = None) -> dict:
        pref = self.get_preference(key, ini_path)
        if "error" in pref:
            return {"exists": False, "key": key, "error": pref["error"]}
        return {"exists": True, "key": key, "value": pref.get("value", "")}

    # === Export format endpoints ===

    def get_midi_info(self, path: str) -> dict:
        """Parse a Standard MIDI File and return header + track + note counts.

        Stdlib-only byte parser. Returns:
          {
            "format": 0|1|2,
            "track_count": N,
            "division": int,
            "note_on_count": N (total across all tracks),
            "tempo_bpm": first set-tempo as BPM (or null),
          }
        """
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            return {"error": str(e)}

        if len(data) < 14 or data[:4] != b"MThd":
            return {"error": "Not a Standard MIDI File (missing MThd)"}

        header_len = struct.unpack(">I", data[4:8])[0]
        fmt = struct.unpack(">H", data[8:10])[0]
        ntrks = struct.unpack(">H", data[10:12])[0]
        division = struct.unpack(">H", data[12:14])[0]

        pos = 8 + header_len
        note_on_count = 0
        tempo_bpm: float | None = None
        tracks_parsed = 0

        def read_var_len(p: int) -> tuple[int, int]:
            val = 0
            while True:
                if p >= len(data):
                    return val, p
                b = data[p]
                p += 1
                val = (val << 7) | (b & 0x7F)
                if not (b & 0x80):
                    return val, p

        while pos + 8 <= len(data) and tracks_parsed < ntrks:
            if data[pos:pos + 4] != b"MTrk":
                break
            tlen = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            tstart = pos + 8
            tend = tstart + tlen
            p = tstart
            running_status = 0
            while p < tend:
                _, p = read_var_len(p)
                if p >= tend:
                    break
                b = data[p]
                if b == 0xFF:  # meta
                    p += 1
                    if p >= tend:
                        break
                    meta_type = data[p]; p += 1
                    mlen, p = read_var_len(p)
                    meta_end = p + mlen
                    if meta_type == 0x51 and mlen == 3 and p + 3 <= tend:  # set tempo
                        micros = (data[p] << 16) | (data[p + 1] << 8) | data[p + 2]
                        if tempo_bpm is None and micros > 0:
                            tempo_bpm = round(60_000_000.0 / micros, 2)
                    p = meta_end
                elif b in (0xF0, 0xF7):  # sysex
                    p += 1
                    slen, p = read_var_len(p)
                    p += slen
                else:
                    if b & 0x80:
                        status = b
                        running_status = status
                        p += 1
                    else:
                        status = running_status
                    high = status & 0xF0
                    if high == 0x90:  # note on
                        if p + 2 <= tend:
                            velocity = data[p + 1]
                            if velocity > 0:
                                note_on_count += 1
                            p += 2
                        else:
                            break
                    elif high in (0x80, 0xA0, 0xB0, 0xE0):
                        p += 2
                    elif high in (0xC0, 0xD0):
                        p += 1
                    else:
                        p += 1
            pos = tend
            tracks_parsed += 1

        return {
            "format": fmt,
            "track_count": ntrks,
            "division": division,
            "note_on_count": note_on_count,
            "tempo_bpm": tempo_bpm,
        }

    def check_midi_track_count(self, path: str, count: int) -> dict:
        info = self.get_midi_info(path)
        if "error" in info:
            return info
        return {
            "match": info.get("track_count") == count,
            "expected": count,
            "actual": info.get("track_count"),
        }

    def check_midi_has_notes(self, path: str, min_notes: int = 1) -> dict:
        info = self.get_midi_info(path)
        if "error" in info:
            return info
        actual = info.get("note_on_count", 0)
        return {
            "match": actual >= min_notes,
            "expected_min": min_notes,
            "actual": actual,
        }

    def get_musicxml_info(self, path: str) -> dict:
        """Parse an exported MusicXML file. Returns part / measure / note counts."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            return {"error": f"MusicXML parse error: {e}"}
        root = tree.getroot()
        parts = [e for e in root.iter() if _local(e.tag) == "part"]
        measures = [e for e in root.iter() if _local(e.tag) == "measure"]
        notes = [e for e in root.iter() if _local(e.tag) == "note"]
        part_names: list[str] = []
        for p in root.iter():
            if _local(p.tag) == "score-part":
                pn_elem = None
                for child in p:
                    if _local(child.tag) == "part-name":
                        pn_elem = child
                        break
                if pn_elem is not None and pn_elem.text:
                    part_names.append(pn_elem.text.strip())
        return {
            "part_count": len(parts),
            "measure_count": len(measures),
            "note_count": len(notes),
            "part_names": part_names,
        }

    def check_musicxml_parts(self, path: str, count: int) -> dict:
        info = self.get_musicxml_info(path)
        if "error" in info:
            return info
        return {
            "match": info.get("part_count") == count,
            "expected": count,
            "actual": info.get("part_count"),
        }

    def get_wav_info(self, path: str) -> dict:
        """Return WAV duration / channels / sample rate via stdlib wave module."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        try:
            with wave.open(path, "rb") as wf:
                nframes = wf.getnframes()
                rate = wf.getframerate()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                duration = nframes / float(rate) if rate else 0.0
            return {
                "duration_sec": round(duration, 3),
                "sample_rate": rate,
                "channels": channels,
                "sample_width_bytes": sampwidth,
                "frames": nframes,
            }
        except (wave.Error, EOFError) as e:
            return {"error": f"WAV parse error: {e}"}

    def check_wav_duration(self, path: str, min_seconds: float) -> dict:
        info = self.get_wav_info(path)
        if "error" in info:
            return info
        actual = info.get("duration_sec", 0.0)
        return {
            "match": actual >= float(min_seconds),
            "expected_min": float(min_seconds),
            "actual": actual,
        }

    def check_pdf_exists(self, path: str) -> dict:
        """Check that a file exists and begins with %PDF- (basic PDF sniff)."""
        if not os.path.isfile(path):
            return {"match": False, "exists": False, "path": path}
        try:
            with open(path, "rb") as f:
                head = f.read(5)
            is_pdf = head == b"%PDF-"
            return {
                "match": is_pdf,
                "exists": True,
                "is_pdf": is_pdf,
                "size_bytes": os.path.getsize(path),
            }
        except OSError as e:
            return {"error": str(e)}

    def check_png_exists(self, path: str) -> dict:
        """Check that a file exists and begins with the PNG signature."""
        if not os.path.isfile(path):
            return {"match": False, "exists": False, "path": path}
        try:
            with open(path, "rb") as f:
                head = f.read(8)
            is_png = head == b"\x89PNG\r\n\x1a\n"
            return {
                "match": is_png,
                "exists": True,
                "is_png": is_png,
                "size_bytes": os.path.getsize(path),
            }
        except OSError as e:
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS: dict[str, tuple[str, Any]] = {
    # Score queries
    "score-info":       ("Top-level score info",                       lambda v, a: v.get_score_info(a[0])),
    "metadata":         ("metaTag values (title, composer, etc.)",     lambda v, a: v.get_metadata(a[0])),
    "parts":            ("Parts/instruments list",                     lambda v, a: v.get_parts(a[0])),
    "staves":           ("Top-level staves with measure counts",       lambda v, a: v.get_staves(a[0])),
    "time-signature":   ("First TimeSig numerator/denominator",        lambda v, a: v.get_time_signature(a[0])),
    "key-signature":    ("First KeySig accidental count",              lambda v, a: v.get_key_signature(a[0])),
    "tempo":            ("First Tempo marking in BPM",                 lambda v, a: v.get_tempo(a[0])),
    "measure-count":    ("Measure count of the first staff",           lambda v, a: v.get_measure_count(a[0])),
    "note-count":       ("Total Note element count in the score",      lambda v, a: v.get_note_count(a[0])),
    "lyrics":           ("All Lyrics text entries",                    lambda v, a: v.get_lyrics(a[0])),
    "instruments":      ("Simple instrument name list",                lambda v, a: v.get_instruments(a[0])),
    # Preferences
    "preferences":      ("Full MuseScore3.ini as nested dict",         lambda v, a: v.get_preferences(a[0] if a else None)),
    "preference":       ("Read one preference: section.key",           lambda v, a: v.get_preference(a[0], a[1] if len(a) > 1 else None)),
    # Checks: score
    "check-file-exists":        ("File exists at path",                lambda v, a: v.check_file_exists(a[0])),
    "check-meta-tag":           ("metaTag[name] == expected",          lambda v, a: v.check_meta_tag(a[0], a[1], " ".join(a[2:]))),
    "check-has-meta-tag":       ("metaTag[name] exists and non-empty", lambda v, a: v.check_has_meta_tag(a[0], a[1])),
    "check-time-signature":     ("TimeSig matches N/D",                lambda v, a: v.check_time_signature(a[0], int(a[1]), int(a[2]))),
    "check-key-signature":      ("KeySig accidental count matches",    lambda v, a: v.check_key_signature(a[0], int(a[1]))),
    "check-tempo":              ("Tempo matches BPM (tolerance 0.5)",  lambda v, a: v.check_tempo(a[0], float(a[1]))),
    "check-measure-count":      ("Measure count matches",              lambda v, a: v.check_measure_count(a[0], int(a[1]))),
    "check-note-count":         ("Exact note count",                   lambda v, a: v.check_note_count(a[0], int(a[1]))),
    "check-note-count-at-least":("Note count >= expected",             lambda v, a: v.check_note_count_at_least(a[0], int(a[1]))),
    "check-part-count":         ("Number of parts/instruments",        lambda v, a: v.check_part_count(a[0], int(a[1]))),
    "check-instrument":         ("Instrument with given name exists",  lambda v, a: v.check_instrument(a[0], " ".join(a[1:]))),
    "check-has-lyrics":         ("Score has at least one lyric",       lambda v, a: v.check_has_lyrics(a[0])),
    "check-lyric-text":         ("At least one lyric contains text",   lambda v, a: v.check_lyric_text(a[0], " ".join(a[1:]))),
    # Gap-coverage queries
    "articulations":                ("List articulations",                 lambda v, a: v.get_articulations(a[0])),
    "check-articulation-in-measure":("Articulation subtype present in measure", lambda v, a: v.check_articulation_in_measure(a[0], int(a[1]), a[2])),
    "check-articulation-count":     ("Articulation subtype count matches", lambda v, a: v.check_articulation_count(a[0], a[1], int(a[2]))),
    "dynamics":                     ("List dynamics",                      lambda v, a: v.get_dynamics(a[0])),
    "check-dynamic-in-measure":     ("Dynamic subtype at measure",         lambda v, a: v.check_dynamic_in_measure(a[0], int(a[1]), a[2])),
    "hairpins":                     ("List hairpins",                      lambda v, a: v.get_hairpins(a[0])),
    "check-has-hairpin":            ("Score has hairpin of subtype",       lambda v, a: v.check_has_hairpin(a[0], a[1])),
    "chord-symbols":                ("List chord symbols",                 lambda v, a: v.get_chord_symbols(a[0])),
    "check-chord-symbol-in-measure":("Chord symbol text at measure",       lambda v, a: v.check_chord_symbol_in_measure(a[0], int(a[1]), a[2])),
    "voltas":                       ("List voltas",                        lambda v, a: v.get_voltas(a[0])),
    "check-has-volta-at":           ("Volta exists at measure",            lambda v, a: v.check_has_volta_at(a[0], int(a[1]))),
    "repeats":                      ("Repeat barlines (start/end)",        lambda v, a: v.get_repeats(a[0])),
    "check-start-repeat-at":        ("Start-repeat at measure",            lambda v, a: v.check_start_repeat_at(a[0], int(a[1]))),
    "check-end-repeat-at":          ("End-repeat at measure",              lambda v, a: v.check_end_repeat_at(a[0], int(a[1]))),
    "jumps-markers":                ("Jumps and markers",                  lambda v, a: v.get_jumps_and_markers(a[0])),
    "check-marker-text":            ("Marker with text substring exists",  lambda v, a: v.check_marker_text(a[0], " ".join(a[1:]))),
    "check-jump-text":              ("Jump with text substring exists",    lambda v, a: v.check_jump_text(a[0], " ".join(a[1:]))),
    "layout-breaks":                ("List LayoutBreak elements",          lambda v, a: v.get_layout_breaks(a[0])),
    "check-layout-break-at":        ("LayoutBreak at measure",             lambda v, a: v.check_layout_break_at(a[0], int(a[1]), a[2] if len(a) > 2 else "line")),
    "style":                        ("Style block as dict",                lambda v, a: v.get_style(a[0])),
    "check-style-value":            ("Style[key] ~= expected",             lambda v, a: v.check_style_value(a[0], a[1], a[2])),
    "instrument-changes":           ("Mid-score instrument changes",       lambda v, a: v.get_instrument_changes(a[0])),
    "check-instrument-change-at":   ("InstrumentChange at measure matches",lambda v, a: v.check_instrument_change_at(a[0], int(a[1]), " ".join(a[2:]))),
    "pedals":                       ("List Pedal spanners",                lambda v, a: v.get_pedals(a[0])),
    "check-has-pedal":              ("Score has >=1 Pedal",                lambda v, a: v.check_has_pedal(a[0])),
    "fingerings":                   ("List Fingering annotations",         lambda v, a: v.get_fingerings(a[0])),
    "check-fingering-count-in-measure":("Fingerings at measure >= count",  lambda v, a: v.check_fingering_count_in_measure(a[0], int(a[1]), int(a[2]))),
    "ornaments":                    ("List ornaments (trill/mordent/turn)",lambda v, a: v.get_ornaments(a[0])),
    "check-has-ornament":           ("Ornament kind at measure",           lambda v, a: v.check_has_ornament(a[0], int(a[1]), a[2])),
    # Checks: preferences
    "check-preference":         ("Preference == expected",             lambda v, a: v.check_preference(a[0], a[1], a[2] if len(a) > 2 else None)),
    "check-preference-exists":  ("Preference key exists",              lambda v, a: v.check_preference_exists(a[0], a[1] if len(a) > 1 else None)),
    # Exports
    "midi-info":                ("Parse MIDI file header/tracks/notes",lambda v, a: v.get_midi_info(a[0])),
    "check-midi-track-count":   ("MIDI track count matches",           lambda v, a: v.check_midi_track_count(a[0], int(a[1]))),
    "check-midi-has-notes":     ("MIDI note_on count >= min",          lambda v, a: v.check_midi_has_notes(a[0], int(a[1]) if len(a) > 1 else 1)),
    "musicxml-info":            ("MusicXML parts/measures/notes",      lambda v, a: v.get_musicxml_info(a[0])),
    "check-musicxml-parts":     ("MusicXML part count matches",        lambda v, a: v.check_musicxml_parts(a[0], int(a[1]))),
    "wav-info":                 ("WAV duration / channels / rate",     lambda v, a: v.get_wav_info(a[0])),
    "check-wav-duration":       ("WAV duration >= min_seconds",        lambda v, a: v.check_wav_duration(a[0], float(a[1]))),
    "check-pdf-exists":         ("File exists and has %PDF- header",   lambda v, a: v.check_pdf_exists(a[0])),
    "check-png-exists":         ("File exists and has PNG header",     lambda v, a: v.check_png_exists(a[0])),
}


def _print_usage():
    print("MuseScore 3 Verifier — inspect .mscz/.mscx scores, INI preferences, and exports")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(n) for n in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. Score files are parsed by unzipping .mscz and reading inner .mscx XML.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = MuseScoreVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": f"Bad argument for '{cmd}': {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
