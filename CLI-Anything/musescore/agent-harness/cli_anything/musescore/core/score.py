"""Direct MSCX/MSCZ score generation and patch helpers."""

import os
import xml.etree.ElementTree as ET

from cli_anything.musescore.utils import mscx_xml


def _score_root() -> ET.Element:
    root = ET.Element("museScore", {"version": "3.01"})
    ET.SubElement(root, "programVersion").text = "3.6.2"
    ET.SubElement(root, "programRevision").text = "direct-cli"
    score = ET.SubElement(root, "Score")
    ET.SubElement(score, "programVersion").text = "3.6.2"
    ET.SubElement(score, "programRevision").text = "direct-cli"
    ET.SubElement(score, "Division").text = "480"
    return root


def _find_score(root: ET.Element) -> ET.Element:
    if root.tag == "Score":
        return root
    score = root.find("Score")
    if score is None:
        score = root.find(".//Score")
    if score is None:
        raise RuntimeError("No <Score> element found")
    return score


def _read(path: str) -> tuple[ET.ElementTree, dict | None]:
    fmt = mscx_xml.detect_format(path)
    if fmt == "mscz":
        data = mscx_xml.read_mscz(path)
        return data["mscx"], data
    if path.lower().endswith(".mscx"):
        return ET.parse(path), None
    raise ValueError("Score patching requires .mscz or .mscx")


def _write(path: str, tree: ET.ElementTree, data: dict | None = None) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if path.lower().endswith(".mscz"):
        payload = data or {"mscx_filename": "score.mscx", "style": None, "audio_settings": None, "view_settings": None, "other_files": {}}
        payload["mscx"] = tree
        mscx_xml.write_mscz(path, payload)
    else:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return os.path.abspath(path)


def _measure(score: ET.Element, staff_id: str, measure: int) -> ET.Element:
    staff = None
    for s in score.findall("Staff"):
        if s.get("id") == staff_id:
            staff = s
            break
    if staff is None:
        staff = ET.SubElement(score, "Staff", {"id": staff_id})
    measures = staff.findall("Measure")
    while len(measures) < measure:
        m = ET.SubElement(staff, "Measure")
        voice = ET.SubElement(m, "voice")
        ET.SubElement(voice, "Rest")
        measures = staff.findall("Measure")
    return measures[measure - 1]


def _voice(measure: ET.Element) -> ET.Element:
    voice = measure.find("voice")
    if voice is None:
        voice = ET.SubElement(measure, "voice")
    return voice


def _child(parent: ET.Element, tag: str) -> ET.Element:
    elem = parent.find(tag)
    if elem is None:
        elem = ET.SubElement(parent, tag)
    return elem


def create_score(
    output_path: str,
    title: str = "Untitled",
    composer: str = "Composer",
    instrument: str = "Piano",
    instrument_id: str = "keyboard.piano",
    measures: int = 4,
    notes_per_measure: int = 1,
    key: int = 0,
    time_sig: str = "4/4",
    tempo: float = 120.0,
) -> dict:
    """Create a verifier-readable MuseScore score."""
    root = _score_root()
    score = _find_score(root)
    for name, value in {
        "workTitle": title,
        "composer": composer,
    }.items():
        meta = ET.SubElement(score, "metaTag", {"name": name})
        meta.text = value

    part = ET.SubElement(score, "Part", {"id": "1"})
    ET.SubElement(part, "Staff", {"id": "1"})
    ET.SubElement(part, "trackName").text = instrument
    instr = ET.SubElement(part, "Instrument", {"id": instrument_id})
    ET.SubElement(instr, "longName").text = instrument
    ET.SubElement(instr, "shortName").text = instrument[:3]
    ET.SubElement(instr, "instrumentId").text = instrument_id

    staff = ET.SubElement(score, "Staff", {"id": "1"})
    n, d = [int(x) for x in time_sig.split("/", 1)]
    for mi in range(1, measures + 1):
        m = ET.SubElement(staff, "Measure")
        voice = ET.SubElement(m, "voice")
        if mi == 1:
            ks = ET.SubElement(voice, "KeySig")
            ET.SubElement(ks, "accidental").text = str(key)
            ts = ET.SubElement(voice, "TimeSig")
            ET.SubElement(ts, "sigN").text = str(n)
            ET.SubElement(ts, "sigD").text = str(d)
            tm = ET.SubElement(voice, "Tempo")
            ET.SubElement(tm, "tempo").text = str(float(tempo) / 60.0)
            ET.SubElement(tm, "text").text = f"q = {tempo:g}"
        for _ in range(notes_per_measure):
            chord = ET.SubElement(voice, "Chord")
            ET.SubElement(chord, "durationType").text = "quarter"
            note = ET.SubElement(chord, "Note")
            ET.SubElement(note, "pitch").text = "60"
            ET.SubElement(note, "tpc").text = "14"

    _write(output_path, ET.ElementTree(root))
    return {"output": os.path.abspath(output_path), "measures": measures}


def patch_score(input_path: str, output_path: str | None = None, *, op: str, **kwargs) -> dict:
    """Patch a score with one verifier-relevant element."""
    output_path = output_path or input_path
    tree, data = _read(input_path)
    score = _find_score(tree.getroot())
    measure_no = int(kwargs.get("measure", 1))
    measure = _measure(score, str(kwargs.get("staff", "1")), measure_no)
    voice = _voice(measure)

    if op == "meta":
        name = str(kwargs["name"])
        for meta in score.findall("metaTag"):
            if meta.get("name") == name:
                meta.text = str(kwargs.get("value", ""))
                break
        else:
            ET.SubElement(score, "metaTag", {"name": name}).text = str(kwargs.get("value", ""))
    elif op == "time":
        ts = _child(voice, "TimeSig")
        n, d = str(kwargs["value"]).split("/", 1)
        _child(ts, "sigN").text = n
        _child(ts, "sigD").text = d
    elif op == "key":
        ks = _child(voice, "KeySig")
        _child(ks, "accidental").text = str(kwargs["value"])
    elif op == "tempo":
        tm = _child(voice, "Tempo")
        bpm = float(kwargs["value"])
        _child(tm, "tempo").text = str(bpm / 60.0)
        _child(tm, "text").text = f"q = {bpm:g}"
    elif op == "lyric":
        note = voice.find(".//Note")
        if note is None:
            chord = ET.SubElement(voice, "Chord")
            note = ET.SubElement(chord, "Note")
            ET.SubElement(note, "pitch").text = "60"
        lyr = ET.SubElement(note, "Lyrics")
        ET.SubElement(lyr, "text").text = str(kwargs["text"])
        ET.SubElement(lyr, "syllabic").text = str(kwargs.get("syllabic", "single"))
    elif op == "articulation":
        art = ET.SubElement(voice, "Articulation")
        ET.SubElement(art, "subtype").text = str(kwargs["subtype"])
    elif op == "dynamic":
        dyn = ET.SubElement(voice, "Dynamic")
        ET.SubElement(dyn, "subtype").text = str(kwargs["subtype"])
    elif op == "hairpin":
        hp = ET.SubElement(voice, "Hairpin")
        mapping = {"crescendo": "0", "decrescendo": "1", "cresc": "0", "decresc": "1"}
        ET.SubElement(hp, "subtype").text = mapping.get(str(kwargs["subtype"]).lower(), str(kwargs["subtype"]))
    elif op == "chord-symbol":
        h = ET.SubElement(voice, "Harmony")
        ET.SubElement(h, "name").text = str(kwargs["text"])
    elif op == "volta":
        ET.SubElement(voice, "Volta")
    elif op == "start-repeat":
        ET.SubElement(measure, "startRepeat")
    elif op == "end-repeat":
        ET.SubElement(measure, "endRepeat")
    elif op == "marker":
        mk = ET.SubElement(voice, "Marker")
        ET.SubElement(mk, "text").text = str(kwargs["text"])
        ET.SubElement(mk, "label").text = str(kwargs.get("label", ""))
    elif op == "jump":
        jp = ET.SubElement(voice, "Jump")
        ET.SubElement(jp, "text").text = str(kwargs["text"])
        ET.SubElement(jp, "jumpTo").text = str(kwargs.get("jump_to", "start"))
    elif op == "layout-break":
        lb = ET.SubElement(voice, "LayoutBreak")
        ET.SubElement(lb, "subtype").text = str(kwargs.get("subtype", "line"))
    elif op == "style":
        style = _child(score, "Style")
        key = str(kwargs["key"])
        elem = _child(style, key)
        elem.text = str(kwargs["value"])
    elif op == "instrument-change":
        ch = ET.SubElement(voice, "InstrumentChange")
        ET.SubElement(ch, "text").text = str(kwargs["name"])
        instr = ET.SubElement(ch, "Instrument")
        ET.SubElement(instr, "longName").text = str(kwargs["name"])
        ET.SubElement(instr, "instrumentId").text = str(kwargs.get("instrument_id", kwargs["name"]))
    elif op == "pedal":
        ET.SubElement(voice, "Pedal")
    elif op == "fingering":
        fg = ET.SubElement(voice, "Fingering")
        ET.SubElement(fg, "text").text = str(kwargs["text"])
    elif op == "ornament":
        orn = ET.SubElement(voice, "Ornament")
        ET.SubElement(orn, "subtype").text = str(kwargs["kind"])
    else:
        raise ValueError(f"Unsupported score patch op: {op}")

    _write(output_path, tree, data)
    return {"input": input_path, "output": os.path.abspath(output_path), "op": op}
