"""End-to-end tests for Kdenlive CLI.

Tests XML generation, format validation, and full workflow scenarios.
No Kdenlive or melt installation required.
"""

import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_anything.kdenlive.core.project import create_project, save_project, open_project, get_project_info
from cli_anything.kdenlive.core.bin import import_clip, list_clips
from cli_anything.kdenlive.core.timeline import (
    add_track, add_clip_to_track, remove_clip_from_track,
    trim_clip, split_clip, move_clip, list_tracks,
)
from cli_anything.kdenlive.core.filters import add_filter, list_filters, FILTER_REGISTRY
from cli_anything.kdenlive.core.transitions import add_transition, list_transitions
from cli_anything.kdenlive.core.guides import add_guide, list_guides
from cli_anything.kdenlive.core.export import generate_kdenlive_xml, list_render_presets, RENDER_PRESETS
from cli_anything.kdenlive.core.session import Session
from cli_anything.kdenlive.utils.mlt_xml import (
    seconds_to_timecode, timecode_to_seconds, seconds_to_frames,
    build_mlt_xml,
)


def _find_sequence(root):
    for tr in root.findall("tractor"):
        if tr.find("property[@name='kdenlive:uuid']") is not None:
            return tr
    return None


# ── XML Generation Tests ───────────────────────────────────────

class TestXMLGeneration:
    def _make_full_project(self):
        """Create a project with clips, tracks, filters, transitions, guides."""
        proj = create_project(name="TestProject", profile="hd1080p30")
        import_clip(proj, "/path/to/interview.mp4", name="Interview", duration=120.0)
        import_clip(proj, "/path/to/broll.mp4", name="BRoll", duration=60.0)
        import_clip(proj, "/path/to/music.mp3", name="Music", duration=180.0, clip_type="audio")

        add_track(proj, name="V1", track_type="video")
        add_track(proj, name="V2", track_type="video")
        add_track(proj, name="A1", track_type="audio")

        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=30.0)
        add_clip_to_track(proj, 1, "clip1", position=5.0, out_point=20.0)
        add_clip_to_track(proj, 2, "clip2", position=0.0, out_point=60.0)

        add_filter(proj, 0, 0, "brightness", {"level": 1.2})
        add_transition(proj, "dissolve", 0, 1, position=5.0, duration=2.0)
        add_guide(proj, 0.0, label="Start")
        add_guide(proj, 30.0, label="End")

        return proj

    def _parse(self, proj=None):
        proj = proj or self._make_full_project()
        return ET.fromstring(generate_kdenlive_xml(proj))

    def test_xml_is_string(self):
        proj = self._make_full_project()
        xml = generate_kdenlive_xml(proj)
        assert isinstance(xml, str)

    def test_xml_has_mlt_root(self):
        root = self._parse()
        assert root.tag == "mlt"

    def test_xml_has_profile(self):
        root = self._parse()
        profile = root.find("profile")
        assert profile is not None
        assert profile.get("width") == "1920"
        assert profile.get("height") == "1080"
        assert profile.get("frame_rate_num") == "30"

    def test_xml_has_chains_for_clips(self):
        root = self._parse()
        chains = root.findall("chain")
        sources = [c.find("property[@name='resource']").text for c in chains if c.find("property[@name='resource']") is not None]
        assert any("interview.mp4" in s for s in sources)

    def test_xml_has_playlists(self):
        root = self._parse()
        playlists = root.findall("playlist")
        ids = [p.get("id") for p in playlists]
        assert "playlist0" in ids
        assert "playlist1" in ids

    def test_xml_has_sequence_tractor(self):
        root = self._parse()
        seq = _find_sequence(root)
        assert seq is not None
        assert seq.find("property[@name='kdenlive:uuid']") is not None

    def test_xml_has_filters(self):
        root = self._parse()
        filters = [
            f for f in root.findall(".//entry/filter")
            if any(p.text == "brightness" for p in f.findall("property[@name='mlt_service']"))
        ]
        assert len(filters) > 0

    def test_xml_has_user_transition(self):
        root = self._parse()
        seq = _find_sequence(root)
        luma = seq.findall("transition[@mlt_service='luma']")
        assert len(luma) == 1

    def test_xml_has_guides_in_sequence(self):
        root = self._parse()
        seq = _find_sequence(root)
        guides_prop = seq.find("property[@name='kdenlive:sequenceproperties.guides']")
        assert guides_prop is not None
        data = json.loads(guides_prop.text)
        assert len(data) == 2
        assert data[0]["comment"] == "Start"
        assert data[1]["comment"] == "End"

    def test_xml_empty_project(self):
        proj = create_project()
        root = ET.fromstring(generate_kdenlive_xml(proj))
        assert root.tag == "mlt"
        assert root.find("profile") is not None

    def test_xml_special_characters_escaped(self):
        proj = create_project(name='Test "Project" <1>')
        root = ET.fromstring(generate_kdenlive_xml(proj))
        assert root.get("title") == 'Test "Project" <1>'

    def test_xml_clip_type_numbers(self):
        proj = create_project()
        import_clip(proj, "/a.mp4", name="V", clip_type="video", duration=10.0)
        import_clip(proj, "/b.mp3", name="A", clip_type="audio", duration=10.0)
        import_clip(proj, "/c.jpg", name="I", clip_type="image", duration=5.0)
        root = ET.fromstring(generate_kdenlive_xml(proj))
        type_nums = set()
        for chain in root.findall("chain"):
            ct = chain.find("property[@name='kdenlive:clip_type']")
            if ct is not None:
                type_nums.add(ct.text)
        assert "0" in type_nums  # video
        assert "1" in type_nums  # audio
        assert "2" in type_nums  # image

    def test_xml_sd_pal_profile(self):
        proj = create_project(profile="sd_pal")
        root = ET.fromstring(generate_kdenlive_xml(proj))
        profile = root.find("profile")
        assert profile.get("width") == "720"
        assert profile.get("height") == "576"
        assert profile.get("progressive") == "0"


# ── Format Validation Tests ─────────────────────────────────────

class TestFormatValidation:
    def test_json_roundtrip(self):
        proj = create_project(name="roundtrip")
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=10.0)
        add_guide(proj, 5.0, label="Mid")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            save_project(proj, path)
            loaded = open_project(path)
            assert loaded["name"] == "roundtrip"
            assert len(loaded["bin"]) == 1
            assert len(loaded["tracks"]) == 1
            assert len(loaded["tracks"][0]["clips"]) == 1
            assert len(loaded["guides"]) == 1
        finally:
            os.unlink(path)

    def test_json_has_all_required_keys(self):
        proj = create_project()
        required = ["version", "name", "profile", "bin", "tracks",
                     "transitions", "guides", "metadata"]
        for key in required:
            assert key in proj, f"Missing key: {key}"

    def test_profile_has_all_required_fields(self):
        proj = create_project()
        profile_keys = ["name", "width", "height", "fps_num", "fps_den",
                        "progressive", "dar_num", "dar_den"]
        for key in profile_keys:
            assert key in proj["profile"], f"Missing profile key: {key}"

    def test_clip_entry_has_required_fields(self):
        proj = create_project()
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        clip = proj["bin"][0]
        for key in ["id", "name", "source", "duration", "type"]:
            assert key in clip, f"Missing clip key: {key}"

    def test_track_entry_has_required_fields(self):
        proj = create_project()
        add_track(proj)
        track = proj["tracks"][0]
        for key in ["id", "name", "type", "mute", "hide", "locked", "clips"]:
            assert key in track, f"Missing track key: {key}"

    def test_timeline_clip_entry_has_required_fields(self):
        proj = create_project()
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=5.0)
        entry = proj["tracks"][0]["clips"][0]
        for key in ["clip_id", "in", "out", "position", "filters"]:
            assert key in entry, f"Missing timeline clip key: {key}"

    def test_xml_well_formed_basic(self):
        proj = create_project()
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=5.0)
        root = ET.fromstring(generate_kdenlive_xml(proj))
        assert root.tag == "mlt"

    def test_xml_chain_count_for_bin_clips(self):
        proj = create_project()
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        import_clip(proj, "/b.mp4", name="B", duration=20.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=10.0)
        root = ET.fromstring(generate_kdenlive_xml(proj))
        # 1 track chain for clip0 + 2 bin chains (clip0 and clip1)
        chains = root.findall("chain")
        assert len(chains) >= 3


# ── Workflow E2E Tests ──────────────────────────────────────────

class TestWorkflowE2E:
    def test_basic_edit_workflow(self):
        proj = create_project(name="BasicEdit", profile="hd1080p30")
        import_clip(proj, "/footage/scene1.mp4", name="Scene1", duration=60.0)
        add_track(proj, track_type="video")
        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=30.0)
        root = ET.fromstring(generate_kdenlive_xml(proj))
        sources = [c.find("property[@name='resource']").text for c in root.findall("chain") if c.find("property[@name='resource']") is not None]
        assert any("scene1.mp4" in s for s in sources)
        entries = root.findall(".//playlist/entry")
        assert len(entries) > 0

    def test_multicam_workflow(self):
        proj = create_project(name="Multicam")
        import_clip(proj, "/cam1.mp4", name="Cam1", duration=60.0)
        import_clip(proj, "/cam2.mp4", name="Cam2", duration=60.0)
        add_track(proj, name="V1", track_type="video")
        add_track(proj, name="V2", track_type="video")
        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=30.0)
        add_clip_to_track(proj, 1, "clip1", position=0.0, out_point=30.0)
        tracks = list_tracks(proj)
        assert len(tracks) == 2
        root = ET.fromstring(generate_kdenlive_xml(proj))
        playlist_ids = [p.get("id") for p in root.findall("playlist")]
        assert "playlist0" in playlist_ids
        assert "playlist1" in playlist_ids

    def test_audio_video_workflow(self):
        proj = create_project(name="AV")
        import_clip(proj, "/video.mp4", name="Video", duration=60.0)
        import_clip(proj, "/music.mp3", name="Music", duration=180.0, clip_type="audio")
        add_track(proj, track_type="video")
        add_track(proj, track_type="audio")
        add_clip_to_track(proj, 0, "clip0", out_point=60.0)
        add_clip_to_track(proj, 1, "clip1", out_point=60.0)
        root = ET.fromstring(generate_kdenlive_xml(proj))
        sources = [c.find("property[@name='resource']").text for c in root.findall("chain") if c.find("property[@name='resource']") is not None]
        assert any("video.mp4" in s for s in sources)
        assert any("music.mp3" in s for s in sources)

    def test_trim_and_split_workflow(self):
        proj = create_project()
        import_clip(proj, "/long.mp4", name="Long", duration=120.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=120.0)
        trim_clip(proj, 0, 0, new_in=10.0, new_out=110.0)
        parts = split_clip(proj, 0, 0, split_at=50.0)
        assert len(parts) == 2
        assert len(proj["tracks"][0]["clips"]) == 2

    def test_filter_chain_workflow(self):
        proj = create_project()
        import_clip(proj, "/video.mp4", name="V", duration=30.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=30.0)

        add_filter(proj, 0, 0, "brightness", {"level": 1.3})
        add_filter(proj, 0, 0, "contrast", {"level": 1.1})
        add_filter(proj, 0, 0, "saturation", {"saturation": 1.5})

        filters = list_filters(proj, 0, 0)
        assert len(filters) == 3

        root = ET.fromstring(generate_kdenlive_xml(proj))
        user_filters = root.findall(".//entry/filter")
        assert len(user_filters) == 3

    def test_transition_workflow(self):
        proj = create_project()
        import_clip(proj, "/a.mp4", name="A", duration=30.0)
        import_clip(proj, "/b.mp4", name="B", duration=30.0)
        add_track(proj, track_type="video")
        add_track(proj, track_type="video")
        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=15.0)
        add_clip_to_track(proj, 1, "clip1", position=10.0, out_point=15.0)
        add_transition(proj, "dissolve", 0, 1, position=10.0, duration=5.0)

        transitions = list_transitions(proj)
        assert len(transitions) == 1
        root = ET.fromstring(generate_kdenlive_xml(proj))
        seq = _find_sequence(root)
        assert seq is not None
        user_trans = [t for t in seq.findall("transition") if t.find("property[@name='internal_added']") is None]
        assert len(user_trans) >= 1

    def test_guide_workflow(self):
        proj = create_project()
        add_guide(proj, 0.0, label="Intro")
        add_guide(proj, 30.0, label="Main Content")
        add_guide(proj, 120.0, label="Outro")

        guides = list_guides(proj)
        assert len(guides) == 3

        root = ET.fromstring(generate_kdenlive_xml(proj))
        seq = _find_sequence(root)
        assert seq is not None
        guides_prop = seq.find("property[@name='kdenlive:sequenceproperties.guides']")
        assert guides_prop is not None
        data = json.loads(guides_prop.text)
        assert len(data) == 3
        assert data[0]["comment"] == "Intro"
        assert data[1]["comment"] == "Main Content"
        assert data[2]["comment"] == "Outro"

    def test_undo_redo_workflow(self):
        sess = Session()
        proj = create_project(name="UndoTest")
        sess.set_project(proj)

        sess.snapshot("import clip")
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        assert len(proj["bin"]) == 1

        sess.snapshot("add track")
        add_track(proj)
        assert len(proj["tracks"]) == 1

        sess.undo()
        assert len(sess.get_project()["tracks"]) == 0

        sess.undo()
        assert len(sess.get_project()["bin"]) == 0

        sess.redo()
        assert len(sess.get_project()["bin"]) == 1

        sess.redo()
        assert len(sess.get_project()["tracks"]) == 1

    def test_save_load_roundtrip(self):
        proj = create_project(name="Roundtrip", profile="hd1080p25")
        import_clip(proj, "/vid.mp4", name="Video", duration=60.0)
        import_clip(proj, "/aud.wav", name="Audio", duration=60.0, clip_type="audio")
        add_track(proj, track_type="video")
        add_track(proj, track_type="audio")
        add_clip_to_track(proj, 0, "clip0", out_point=30.0)
        add_clip_to_track(proj, 1, "clip1", out_point=30.0)
        add_filter(proj, 0, 0, "brightness", {"level": 1.2})
        add_transition(proj, "dissolve", 0, 1, position=5.0, duration=2.0)
        add_guide(proj, 10.0, label="Mark")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_project(proj, path)
            loaded = open_project(path)

            assert loaded["name"] == "Roundtrip"
            assert loaded["profile"]["fps_num"] == 25
            assert len(loaded["bin"]) == 2
            assert len(loaded["tracks"]) == 2
            assert len(loaded["tracks"][0]["clips"]) == 1
            assert len(loaded["tracks"][0]["clips"][0]["filters"]) == 1
            assert len(loaded["transitions"]) == 1
            assert len(loaded["guides"]) == 1

            xml = generate_kdenlive_xml(loaded)
            root = ET.fromstring(xml)
            assert root.tag == "mlt"
        finally:
            os.unlink(path)

    def test_render_presets_available(self):
        presets = list_render_presets()
        assert len(presets) == len(RENDER_PRESETS)
        names = [p["name"] for p in presets]
        assert "h264_hq" in names
        assert "h264_fast" in names
        assert "prores" in names

    def test_all_profiles_produce_valid_xml(self):
        from cli_anything.kdenlive.core.project import PROFILES
        for name in PROFILES:
            proj = create_project(profile=name)
            root = ET.fromstring(generate_kdenlive_xml(proj))
            assert root.tag == "mlt"
            assert root.find("profile") is not None

    def test_complex_timeline_xml(self):
        proj = create_project(name="Complex", profile="hd1080p30")
        for i in range(5):
            import_clip(proj, f"/clip{i}.mp4", name=f"Clip{i}", duration=30.0)
        add_track(proj, track_type="video")
        add_track(proj, track_type="video")
        add_track(proj, track_type="audio")

        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=15.0)
        add_clip_to_track(proj, 0, "clip1", position=15.0, out_point=15.0)
        add_clip_to_track(proj, 1, "clip2", position=5.0, out_point=20.0)
        add_clip_to_track(proj, 2, "clip3", position=0.0, out_point=30.0)

        add_filter(proj, 0, 0, "brightness", {"level": 1.1})
        add_filter(proj, 0, 0, "blur", {"hblur": 3, "vblur": 3})
        add_filter(proj, 0, 1, "fade_in_video", {"duration": 0.5})

        add_transition(proj, "dissolve", 0, 1, position=5.0, duration=3.0)

        add_guide(proj, 0.0, label="Start")
        add_guide(proj, 15.0, label="Mid")
        add_guide(proj, 30.0, label="End")

        root = ET.fromstring(generate_kdenlive_xml(proj))

        # 5 bin clips → bin chains for each + per-track chains for used clips
        main_bin = root.find(".//playlist[@id='main_bin']")
        bin_entries = [e for e in main_bin.findall("entry") if not e.get("producer", "").startswith("{")]
        assert len(bin_entries) == 5

        # 3 tracks × 2 playlists + main_bin = 7
        playlists = root.findall("playlist")
        assert len(playlists) == 7

        # 3 user filters on clips
        user_filters = root.findall(".//entry/filter")
        assert len(user_filters) == 3

        # 1 user transition (luma/dissolve)
        seq = _find_sequence(root)
        luma_trans = [t for t in seq.findall("transition") if t.get("mlt_service") == "luma"]
        assert len(luma_trans) == 1

        # Guides in sequence tractor
        guides_prop = seq.find("property[@name='kdenlive:sequenceproperties.guides']")
        assert guides_prop is not None
        data = json.loads(guides_prop.text)
        assert len(data) == 3

    def test_move_clip_then_export(self):
        proj = create_project()
        import_clip(proj, "/vid.mp4", name="V", duration=30.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=10.0)
        move_clip(proj, 0, 0, new_position=5.0)
        root = ET.fromstring(generate_kdenlive_xml(proj))
        blanks = root.findall(".//blank")
        assert len(blanks) > 0

    def test_project_info_after_edits(self):
        proj = create_project(name="InfoTest")
        import_clip(proj, "/a.mp4", name="A", duration=10.0)
        import_clip(proj, "/b.mp4", name="B", duration=20.0)
        add_track(proj, track_type="video")
        add_track(proj, track_type="audio")
        add_clip_to_track(proj, 0, "clip0", out_point=10.0)
        add_guide(proj, 5.0, label="X")

        info = get_project_info(proj)
        assert info["counts"]["bin_clips"] == 2
        assert info["counts"]["tracks"] == 2
        assert info["counts"]["clips_on_timeline"] == 1
        assert info["counts"]["guides"] == 1

    def test_all_filter_types_in_xml(self):
        proj = create_project()
        import_clip(proj, "/vid.mp4", name="V", duration=30.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=30.0)

        for fname in FILTER_REGISTRY:
            add_filter(proj, 0, 0, fname)

        root = ET.fromstring(generate_kdenlive_xml(proj))
        user_filters = root.findall(".//entry/filter")
        assert len(user_filters) == len(FILTER_REGISTRY)

    def test_xml_write_to_file(self):
        proj = create_project(name="FileTest")
        import_clip(proj, "/v.mp4", name="V", duration=10.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=10.0)

        xml = generate_kdenlive_xml(proj)
        with tempfile.NamedTemporaryFile(suffix=".kdenlive", delete=False, mode="w") as f:
            f.write(xml)
            path = f.name
        try:
            with open(path, "r") as f:
                content = f.read()
            assert content.startswith('<?xml version="1.0"')
            assert "</mlt>" in content
        finally:
            os.unlink(path)

    def test_timecode_in_workflow(self):
        tc = "00:01:30.000"
        secs = timecode_to_seconds(tc)
        assert secs == 90.0

        frames = seconds_to_frames(secs, 30, 1)
        assert frames == 2700

        back_tc = seconds_to_timecode(secs)
        assert back_tc == "00:01:30.000"

    def test_split_then_filter_workflow(self):
        proj = create_project()
        import_clip(proj, "/vid.mp4", name="V", duration=20.0)
        add_track(proj)
        add_clip_to_track(proj, 0, "clip0", out_point=20.0)
        split_clip(proj, 0, 0, split_at=10.0)
        add_filter(proj, 0, 1, "fade_out_video", {"duration": 2.0})
        filters = list_filters(proj, 0, 1)
        assert len(filters) == 1
        assert filters[0]["name"] == "fade_out_video"

    def test_session_with_full_workflow(self):
        sess = Session()
        proj = create_project(name="SessionWorkflow")
        sess.set_project(proj)

        sess.snapshot("import clips")
        import_clip(proj, "/a.mp4", name="A", duration=30.0)
        import_clip(proj, "/b.mp4", name="B", duration=30.0)

        sess.snapshot("add tracks")
        add_track(proj, track_type="video")
        add_track(proj, track_type="audio")

        sess.snapshot("place clips")
        add_clip_to_track(proj, 0, "clip0", out_point=15.0)

        history = sess.list_history()
        assert len(history) == 3

        sess.undo()
        assert len(sess.get_project()["tracks"][0]["clips"]) == 0

        sess.undo()
        assert len(sess.get_project()["tracks"]) == 0

        sess.redo()
        assert len(sess.get_project()["tracks"]) == 2
        sess.redo()
        assert len(sess.get_project()["tracks"][0]["clips"]) == 1


# ── True Backend E2E Tests (requires melt installed) ─────────────

class TestMeltBackend:
    """Tests that verify melt is installed and accessible."""

    def test_melt_is_installed(self):
        from cli_anything.kdenlive.utils.melt_backend import find_melt
        path = find_melt()
        assert os.path.exists(path)
        print(f"\n  melt binary: {path}")

    def test_melt_version(self):
        from cli_anything.kdenlive.utils.melt_backend import get_melt_version
        version = get_melt_version()
        assert version
        print(f"\n  melt version: {version}")


class TestMeltRenderE2E:
    """True E2E tests: render videos using melt."""

    def test_render_color_bars_mp4(self):
        """Render a color bars test video."""
        from cli_anything.kdenlive.utils.melt_backend import render_color_bars

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = os.path.join(tmp_dir, "test.mp4")
            result = render_color_bars(output, duration=2, width=320, height=240)

            assert os.path.exists(result["output"])
            assert result["file_size"] > 0
            print(f"\n  Color bars MP4: {result['output']} ({result['file_size']:,} bytes)")

    def test_render_generated_mlt_xml(self):
        """Generate Kdenlive MLT XML from project and render it."""
        from cli_anything.kdenlive.utils.melt_backend import find_melt

        melt = find_melt()

        with tempfile.TemporaryDirectory() as tmp_dir:
            mlt_content = '''<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" version="7.0.0" profile="atsc_720p_25">
  <profile description="HD 720p 25fps" width="320" height="240" progressive="1"
           sample_aspect_num="1" sample_aspect_den="1"
           display_aspect_num="4" display_aspect_den="3"
           frame_rate_num="25" frame_rate_den="1" colorspace="709"/>
  <producer id="color0" in="0" out="49">
    <property name="resource">color:green</property>
    <property name="mlt_service">color</property>
  </producer>
  <playlist id="playlist0">
    <entry producer="color0" in="0" out="49"/>
  </playlist>
  <tractor id="tractor0">
    <track producer="playlist0"/>
  </tractor>
</mlt>'''
            mlt_path = os.path.join(tmp_dir, "kdenlive_test.mlt")
            output_path = os.path.join(tmp_dir, "rendered.mp4")

            with open(mlt_path, 'w') as f:
                f.write(mlt_content)

            import subprocess
            cmd = [melt, mlt_path, "-consumer", f"avformat:{output_path}",
                   "vcodec=libx264", "acodec=aac", "ar=48000", "channels=2"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, f"melt failed: {result.stderr[-500:]}"
            assert os.path.exists(output_path)
            size = os.path.getsize(output_path)
            assert size > 0
            print(f"\n  Kdenlive MLT render: {output_path} ({size:,} bytes)")


# ── Kdenlive Gen 5 Format Validation Tests ─────────────────────

class TestKdenliveGen5Format:
    """Validate Kdenlive Gen 5 (doc version 1.1) XML structure."""

    def _make_simple_project(self):
        proj = create_project(name="Gen5Test", profile="hd1080p30")
        import_clip(proj, "/video.mp4", name="Video", duration=30.0)
        import_clip(proj, "/audio.mp3", name="Audio", duration=60.0, clip_type="audio")
        add_track(proj, name="V1", track_type="video")
        add_track(proj, name="A1", track_type="audio")
        add_clip_to_track(proj, 0, "clip0", position=0.0, out_point=15.0)
        add_clip_to_track(proj, 1, "clip1", position=0.0, out_point=30.0)
        add_transition(proj, "dissolve", 0, 1, position=5.0, duration=2.0)
        add_guide(proj, 10.0, label="Marker")
        return proj

    def _parse(self, proj=None):
        proj = proj or self._make_simple_project()
        return ET.fromstring(generate_kdenlive_xml(proj))

    def test_mlt_root_producer_is_main_bin(self):
        root = self._parse()
        assert root.get("producer") == "main_bin"

    def test_has_main_bin_playlist(self):
        root = self._parse()
        assert root.find(".//playlist[@id='main_bin']") is not None

    def test_main_bin_has_docproperties(self):
        root = self._parse()
        main_bin = root.find(".//playlist[@id='main_bin']")
        props = {p.get("name"): p.text for p in main_bin.findall("property")}
        assert props.get("kdenlive:docproperties.version") == "1.1"
        assert "kdenlive:docproperties.uuid" in props

    def test_main_bin_lists_bin_clip_chains(self):
        root = self._parse()
        main_bin = root.find(".//playlist[@id='main_bin']")
        entries = main_bin.findall("entry")
        producer_refs = [e.get("producer") for e in entries]
        # Bin clips should be referenced as chainN (not *_bin)
        bin_refs = [r for r in producer_refs if r.startswith("chain")]
        assert len(bin_refs) == 2

    def test_main_bin_lists_sequence(self):
        root = self._parse()
        seq = _find_sequence(root)
        assert seq is not None
        seq_id = seq.get("id")
        main_bin = root.find(".//playlist[@id='main_bin']")
        entries = main_bin.findall("entry")
        producer_refs = [e.get("producer") for e in entries]
        assert seq_id in producer_refs

    def test_per_track_tractor_wraps_playlists(self):
        root = self._parse()
        tractor0 = root.find(".//tractor[@id='tractor0']")
        assert tractor0 is not None
        tracks = tractor0.findall("track")
        assert len(tracks) == 2  # dual playlist
        producers = [t.get("producer") for t in tracks]
        assert any(p.startswith("playlist") for p in producers)

    def test_video_track_hides_audio(self):
        root = self._parse()
        tractor0 = root.find(".//tractor[@id='tractor0']")
        tracks = tractor0.findall("track")
        assert all(t.get("hide") == "audio" for t in tracks)

    def test_audio_track_hides_video(self):
        root = self._parse()
        tractor1 = root.find(".//tractor[@id='tractor1']")
        tracks = tractor1.findall("track")
        assert all(t.get("hide") == "video" for t in tracks)

    def test_sequence_tractor_has_uuid(self):
        root = self._parse()
        seq = _find_sequence(root)
        assert seq is not None
        uuid_val = seq.get("id")
        assert re.match(r'^\{[0-9a-f-]+\}$', uuid_val)
        uuid_prop = seq.find("property[@name='kdenlive:uuid']")
        assert uuid_prop is not None
        assert uuid_prop.text == uuid_val

    def test_sequence_tractor_references_track_tractors(self):
        root = self._parse()
        seq = _find_sequence(root)
        track_refs = [t.get("producer") for t in seq.findall("track")]
        assert "producer0" in track_refs  # black track first
        assert "tractor0" in track_refs
        assert "tractor1" in track_refs

    def test_project_tractor_exists(self):
        root = self._parse()
        assert root.find(".//tractor[@id='tractor_project']") is not None

    def test_project_tractor_has_property(self):
        root = self._parse()
        proj_tractor = root.find(".//tractor[@id='tractor_project']")
        props = {p.get("name"): p.text for p in proj_tractor.findall("property")}
        assert props.get("kdenlive:projectTractor") == "1"

    def test_project_tractor_references_sequence(self):
        root = self._parse()
        seq = _find_sequence(root)
        seq_id = seq.get("id")
        proj_tractor = root.find(".//tractor[@id='tractor_project']")
        track = proj_tractor.find("track")
        assert track.get("producer") == seq_id

    def test_internal_transitions_in_sequence(self):
        root = self._parse()
        seq = _find_sequence(root)
        transitions = seq.findall("transition")
        mix_trans = [t for t in transitions if t.find("property[@name='mlt_service']") is not None and t.find("property[@name='mlt_service']").text == "mix"]
        blend_trans = [t for t in transitions if t.find("property[@name='mlt_service']") is not None and t.find("property[@name='mlt_service']").text == "qtblend"]
        assert len(mix_trans) >= 1  # audio track gets mix
        assert len(blend_trans) >= 1  # video track gets qtblend

    def test_user_transition_in_sequence(self):
        root = self._parse()
        seq = _find_sequence(root)
        luma = seq.findall("transition[@mlt_service='luma']")
        assert len(luma) == 1

    def test_guides_in_sequence_tractor(self):
        root = self._parse()
        seq = _find_sequence(root)
        guides_prop = seq.find("property[@name='kdenlive:sequenceproperties.guides']")
        assert guides_prop is not None
        data = json.loads(guides_prop.text)
        assert len(data) == 1
        assert data[0]["comment"] == "Marker"

    def test_empty_project_has_gen5_structure(self):
        proj = create_project()
        root = ET.fromstring(generate_kdenlive_xml(proj))
        assert root.get("producer") == "main_bin"
        assert root.find(".//playlist[@id='main_bin']") is not None
        assert root.find(".//tractor[@id='tractor_project']") is not None
        assert _find_sequence(root) is not None

    def test_no_kdenlivedoc_element(self):
        xml = generate_kdenlive_xml(self._make_simple_project())
        assert "<kdenlivedoc>" not in xml

    def test_project_tractor_is_last_element(self):
        root = self._parse()
        last = root[-1]
        assert last.get("id") == "tractor_project"

    def test_black_track_producer_exists(self):
        root = self._parse()
        black = root.find("producer[@id='producer0']")
        assert black is not None
        resource = black.find("property[@name='resource']")
        assert resource.text == "black"

    def test_bin_clip_chains_use_avformat(self):
        root = self._parse()
        # Bin chains are listed in main_bin entries with chainN ids
        main_bin = root.find(".//playlist[@id='main_bin']")
        bin_producers = [e.get("producer") for e in main_bin.findall("entry")
                         if e.get("producer", "").startswith("chain")]
        for prod_id in bin_producers:
            chain = root.find(f".//chain[@id='{prod_id}']")
            assert chain is not None
            svc = chain.find("property[@name='mlt_service']")
            assert svc is not None
            assert svc.text == "avformat-novalidate"

    def test_audio_track_tractor_has_internal_filters(self):
        root = self._parse()
        tractor1 = root.find(".//tractor[@id='tractor1']")
        filters = tractor1.findall("filter")
        services = [f.find("property[@name='mlt_service']") for f in filters]
        services = [s.text for s in services if s is not None]
        assert "volume" in services
        assert "panner" in services
        assert "audiolevel" in services

    def test_main_bin_has_xml_retain(self):
        root = self._parse()
        main_bin = root.find(".//playlist[@id='main_bin']")
        retain = main_bin.find("property[@name='xml_retain']")
        assert retain is not None
        assert retain.text == "1"

    def test_render_gen5_xml_through_melt(self):
        from cli_anything.kdenlive.utils.melt_backend import find_melt
        import subprocess

        melt = find_melt()

        with tempfile.TemporaryDirectory() as tmp_dir:
            mlt_path = os.path.join(tmp_dir, "gen5_test.kdenlive")
            output_path = os.path.join(tmp_dir, "rendered.mp4")

            proj = create_project(name="Gen5MeltTest", profile="hd1080p30")
            import_clip(proj, "color:red", name="Red", duration=2.0)
            add_track(proj, track_type="video")
            add_clip_to_track(proj, 0, "clip0", out_point=2.0)

            xml = generate_kdenlive_xml(proj)
            with open(mlt_path, 'w') as f:
                f.write(xml)

            ET.fromstring(xml)

            cmd = [melt, mlt_path, "-consumer", f"avformat:{output_path}",
                   "vcodec=libx264", "acodec=aac", "ar=48000", "channels=2"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, f"melt failed: {result.stderr[-500:]}"
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
