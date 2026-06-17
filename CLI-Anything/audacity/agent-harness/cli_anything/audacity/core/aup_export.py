"""Audacity CLI - .aup XML export module.

Converts CLI-Anything JSON projects to Audacity 2.x .aup XML format.
This enables compatibility with the verifier system which reads .aup files.
"""

import os
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
import uuid


AUP_NS = "http://audacity.sourceforge.net/xml/"


def export_to_aup(
    project: Dict[str, Any],
    output_path: str,
    create_data_dir: bool = True,
    audio_backend: Optional[str] = None
) -> str:
    """Export a CLI-Anything project to Audacity .aup XML format.

    Args:
        project: CLI-Anything project dict (from create_project/load_project)
        output_path: Path where .aup file should be written
        create_data_dir: If True, create the _data directory for blockfiles
        audio_backend: Optional backend for audio rendering ('sox', 'ffmpeg', or None)

    Returns:
        Path to the created .aup file

    Raises:
        ValueError: If project structure is invalid
        IOError: If file cannot be written
    """
    # Validate project
    if "settings" not in project:
        raise ValueError("Invalid project: missing 'settings' field")

    # Prepare paths
    output_path = os.path.abspath(output_path)
    if not output_path.endswith(".aup"):
        output_path += ".aup"

    proj_name = os.path.splitext(os.path.basename(output_path))[0]
    data_dir_path = os.path.splitext(output_path)[0] + "_data"

    # Create data directory if requested
    if create_data_dir:
        os.makedirs(data_dir_path, exist_ok=True)

    # Build XML structure
    root = _build_project_element(project, proj_name)
    tree = ET.ElementTree(root)

    # Write XML with proper declaration and namespace
    ET.register_namespace("", AUP_NS)
    _write_pretty_xml(tree, output_path)

    return output_path


def _build_project_element(project: Dict[str, Any], proj_name: str) -> ET.Element:
    """Build the root <project> element with all children."""
    settings = project.get("settings", {})
    tracks = project.get("tracks", [])
    labels = project.get("labels", [])
    metadata = project.get("metadata", {})

    # Create root element with namespace
    root = ET.Element(f"{{{AUP_NS}}}project")

    # Project attributes
    root.set("projname", proj_name + "_data")
    root.set("audacityversion", "2.4.2")
    root.set("version", "2.4.2")

    # Selection attributes (default to empty selection)
    selection = project.get("selection", {"start": 0.0, "end": 0.0})
    root.set("sel0", str(selection.get("start", 0.0)))
    root.set("sel1", str(selection.get("end", 0.0)))

    # Settings
    root.set("rate", str(settings.get("sample_rate", 44100)))
    root.set("snapto", project.get("snapto", "Off"))
    root.set("selectionformat", project.get("selectionformat", "hh:mm:ss"))

    # View attributes (defaults)
    root.set("vpos", "0")
    root.set("h", "0.0")
    root.set("zoom", "86.1328125")

    # Add metadata tags
    _add_tags_element(root, metadata)

    # Add tracks
    for track in tracks:
        track_type = track.get("type", "audio")
        if track_type == "audio":
            _add_wavetrack_element(root, track, settings)
        elif track_type == "label":
            _add_labeltrack_element(root, track)

    # Add project-level labels (if any)
    if labels:
        _add_project_level_labels(root, labels, settings.get("sample_rate", 44100))

    return root


def _add_tags_element(project_elem: ET.Element, metadata: Dict[str, str]):
    """Add <tags> element with metadata."""
    if not metadata:
        return

    tags = ET.SubElement(project_elem, "tags")

    # Map common metadata fields to tag names
    tag_mappings = {
        "title": "TITLE",
        "artist": "ARTIST",
        "album": "ALBUM",
        "year": "YEAR",
        "genre": "GENRE",
        "comments": "COMMENTS",
    }

    for field, tag_name in tag_mappings.items():
        value = metadata.get(field)
        if value:
            tag_elem = ET.SubElement(tags, "tag")
            tag_elem.set("name", tag_name)
            tag_elem.set("value", str(value))


def _add_wavetrack_element(project_elem: ET.Element, track: Dict[str, Any], project_settings: Dict):
    """Add a <wavetrack> element for an audio track."""
    wt = ET.SubElement(project_elem, "wavetrack")

    # Track attributes
    wt.set("name", track.get("name", "Audio Track"))
    wt.set("channel", str(track.get("channel", 0)))
    wt.set("linked", str(track.get("linked", 0)))
    wt.set("mute", str(int(track.get("mute", False))))
    wt.set("solo", str(int(track.get("solo", False))))

    # Use per-track rate if available, otherwise project rate
    rate = track.get("rate", project_settings.get("sample_rate", 44100))
    wt.set("rate", str(int(rate)))

    # Map CLI-Anything "volume" to Audacity "gain"
    gain = track.get("gain", track.get("volume", 1.0))
    wt.set("gain", str(float(gain)))
    wt.set("pan", str(track.get("pan", 0.0)))

    # Add height/default attributes
    wt.set("height", "150")

    # Add clips
    clips = track.get("clips", [])
    for clip in clips:
        _add_waveclip_element(wt, clip)


def _add_waveclip_element(wavetrack_elem: ET.Element, clip: Dict[str, Any]):
    """Add a <waveclip> element for a track clip."""
    wc = ET.SubElement(wavetrack_elem, "waveclip")

    # Clip attributes
    wc.set("offset", str(clip.get("start_time", 0.0)))
    wc.set("colorindex", "0")

    # Add sequence (audio data reference)
    seq = ET.SubElement(wc, "sequence")
    seq.set("maxsamples", "262144")
    seq.set("sampleformat", "262159")
    seq.set("numsamples", str(_calculate_clip_samples(clip)))

    # Add waveblock with blockfile reference
    block = ET.SubElement(seq, "waveblock")
    block.set("start", "0")

    # Generate blockfile reference
    source = clip.get("source", "")
    if source and os.path.exists(source):
        # Reference actual audio file
        blockfile = ET.SubElement(block, "simpleblockfile")
        blockfile.set("filename", os.path.basename(source))
        blockfile.set("len", str(_calculate_clip_samples(clip)))
        blockfile.set("min", "-1.0")
        blockfile.set("max", "1.0")
        blockfile.set("rms", "0.5")
    else:
        # Generate silence blockfile reference
        blockfile = ET.SubElement(block, "silentblockfile")
        blockfile.set("len", str(_calculate_clip_samples(clip)))

    # Add envelope (empty)
    env = ET.SubElement(wc, "envelope")
    env.set("numpoints", "0")


def _add_labeltrack_element(project_elem: ET.Element, track: Dict[str, Any]):
    """Add a <labeltrack> element for a label track."""
    lt = ET.SubElement(project_elem, "labeltrack")

    lt.set("name", track.get("name", "Label Track"))
    lt.set("numlabels", str(len(track.get("labels", []))))

    # Add labels
    for label in track.get("labels", []):
        label_elem = ET.SubElement(lt, "label")
        label_elem.set("t", str(label.get("start", 0.0)))
        label_elem.set("t1", str(label.get("end", label.get("start", 0.0))))
        label_elem.set("title", label.get("text", ""))


def _add_project_level_labels(project_elem: ET.Element, labels: List[Dict], sample_rate: int):
    """Add a label track for project-level labels."""
    if not labels:
        return

    lt = ET.SubElement(project_elem, "labeltrack")
    lt.set("name", "Labels")
    lt.set("numlabels", str(len(labels)))

    for label in labels:
        label_elem = ET.SubElement(lt, "label")
        label_elem.set("t", str(label.get("start", 0.0)))
        label_elem.set("t1", str(label.get("end", label.get("start", 0.0))))
        label_elem.set("title", label.get("text", ""))


def _calculate_clip_samples(clip: Dict[str, Any]) -> int:
    """Calculate number of samples in a clip."""
    duration = clip.get("end_time", 0.0) - clip.get("start_time", 0.0)
    # Default to 44100 if no rate specified
    rate = clip.get("sample_rate", 44100)
    return int(max(0, duration * rate))


def _write_pretty_xml(tree: ET.ElementTree, path: str):
    """Write XML file with proper formatting."""
    # Use ElementTree's write with XML declaration
    # Note: standalone parameter not supported in all Python versions
    try:
        tree.write(
            path,
            encoding="utf-8",
            xml_declaration=True
        )
    except TypeError:
        # Fallback for older Python versions
        import io
        output = io.StringIO()
        output.write('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n')
        tree.write(output, encoding="unicode")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(output.getvalue())


def import_from_aup(aup_path: str) -> Dict[str, Any]:
    """Import an Audacity .aup file into CLI-Anything project format.

    This is the inverse of export_to_aup - it reads .aup XML and creates
    a CLI-Anything project dict.

    Args:
        aup_path: Path to .aup file

    Returns:
        CLI-Anything project dict

    Raises:
        FileNotFoundError: If .aup file doesn't exist
        ValueError: If .aup format is invalid
    """
    if not os.path.exists(aup_path):
        raise FileNotFoundError(f".aup file not found: {aup_path}")

    tree = ET.parse(aup_path)
    root = tree.getroot()

    # Strip namespace for easier parsing
    def strip_ns(tag):
        return tag.split("}", 1)[1] if "}" in tag else tag

    # Parse project attributes
    project = {
        "version": "1.0",
        "name": os.path.splitext(os.path.basename(aup_path))[0],
        "settings": {
            "sample_rate": int(float(root.get("rate", 44100))),
            "bit_depth": 16,
            "channels": 2,
        },
        "snapto": root.get("snapto", "Off"),
        "selectionformat": root.get("selectionformat", "hh:mm:ss"),
        "selection": {
            "start": float(root.get("sel0", 0.0)),
            "end": float(root.get("sel1", 0.0)),
        },
        "tracks": [],
        "labels": [],
        "metadata": {},
    }

    # Parse tags/metadata
    for tags in root.iter():
        if strip_ns(tags.tag) == "tags":
            for tag in tags:
                if strip_ns(tag.tag) == "tag":
                    name = tag.get("name", "").lower()
                    value = tag.get("value", "")
                    # Map to metadata fields
                    if name == "title":
                        project["metadata"]["title"] = value
                    elif name == "artist":
                        project["metadata"]["artist"] = value
                    elif name == "album":
                        project["metadata"]["album"] = value
                    elif name == "year":
                        project["metadata"]["year"] = value
                    elif name == "genre":
                        project["metadata"]["genre"] = value
                    elif name == "comments":
                        project["metadata"]["comments"] = value

    # Parse tracks
    track_idx = 0
    for elem in root:
        tag_name = strip_ns(elem.tag)

        if tag_name == "wavetrack":
            track = _parse_wavetrack(elem, track_idx)
            project["tracks"].append(track)
            track_idx += 1

        elif tag_name == "labeltrack":
            track = _parse_labeltrack(elem, track_idx)
            project["tracks"].append(track)
            track_idx += 1

    return project


def _parse_wavetrack(wt_elem: ET.Element, index: int) -> Dict[str, Any]:
    """Parse a <wavetrack> element."""
    track = {
        "id": index,
        "name": wt_elem.get("name", f"Track {index}"),
        "type": "audio",
        "channel": int(wt_elem.get("channel", 0)),
        "linked": int(wt_elem.get("linked", 0)),
        "mute": bool(int(wt_elem.get("mute", 0))),
        "solo": bool(int(wt_elem.get("solo", 0))),
        "rate": int(float(wt_elem.get("rate", 44100))),
        "gain": float(wt_elem.get("gain", 1.0)),
        "pan": float(wt_elem.get("pan", 0.0)),
        "volume": float(wt_elem.get("gain", 1.0)),  # Alias for compatibility
        "clips": [],
        "effects": [],
    }

    # Parse clips
    for clip_elem in wt_elem:
        if strip_ns(clip_elem.tag) == "waveclip":
            clip = _parse_waveclip(clip_elem)
            track["clips"].append(clip)

    return track


def _parse_waveclip(wc_elem: ET.Element) -> Dict[str, Any]:
    """Parse a <waveclip> element."""
    offset = float(wc_elem.get("offset", 0.0))

    # Try to get duration from sequence
    duration = 1.0  # Default
    for seq in wc_elem:
        if strip_ns(seq.tag) == "sequence":
            numsamples = int(seq.get("numsamples", 44100))
            rate = 44100  # Default
            duration = numsamples / rate
            break

    return {
        "start_time": offset,
        "end_time": offset + duration,
        "source": "",  # Would need to parse blockfile refs
    }


def _parse_labeltrack(lt_elem: ET.Element, index: int) -> Dict[str, Any]:
    """Parse a <labeltrack> element."""
    track = {
        "id": index,
        "name": lt_elem.get("name", f"Label Track {index}"),
        "type": "label",
        "labels": [],
    }

    for label_elem in lt_elem:
        if strip_ns(label_elem.tag) == "label":
            label = {
                "start": float(label_elem.get("t", 0.0)),
                "end": float(label_elem.get("t1", label_elem.get("t", 0.0))),
                "text": label_elem.get("title", ""),
            }
            track["labels"].append(label)

    return track


def strip_ns(tag: str) -> str:
    """Strip namespace from tag name."""
    return tag.split("}", 1)[1] if "}" in tag else tag
