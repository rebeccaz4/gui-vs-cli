"""
Test Audacity verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing file, bad args, unknown command, wrong extension, malformed XML)
  - .aup XML query endpoints (project-info, tracks, labels, tags, ...)
  - Preferences (audacity.cfg) + plugin registry
  - Check endpoints (positive and negative cases)
  - Minimal fixture edge cases
  - Export endpoints using ffmpeg-generated WAV and MP3 fixtures
  - JSON validity sweep

Fixtures are written inside the sandbox as plain .aup XML files (Audacity 2.x
format). The installed Audacity version is 2.4.2 which writes .aup/.aup_data,
so we do not use the .aup3/SQLite format.

Usage:
    python verifiers/audacity/test_audacity.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "audacity.py"
VERIFIER_REMOTE = "/home/user/verifiers/audacity.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

RICH_AUP = "/home/user/rich.aup"
RICH_DATA = "/home/user/rich_data"
BROKEN_AUP = "/home/user/broken.aup"
MIN_AUP = "/home/user/min.aup"
MALFORMED_AUP = "/home/user/malformed.aup"
NOT_PROJECT_AUP = "/home/user/notproject.aup"
TINY_TXT = "/tmp/tiny.txt"
CFG_PATH = "/home/user/.audacity-data/audacity.cfg"
PLUGREG_PATH = "/home/user/.audacity-data/pluginregistry.cfg"
OUT_WAV = "/home/user/out.wav"
OUT_MP3 = "/home/user/out.mp3"

# Synthetic audio fixtures for content-analysis endpoints
SINE440_LOUD = "/home/user/sine440_loud.wav"       # 440Hz, amp=0.8, 2s mono 44.1k
SINE440_QUIET = "/home/user/sine440_quiet.wav"     # 440Hz, amp=0.05, 2s mono 44.1k
SINE880 = "/home/user/sine880.wav"                 # 880Hz, amp=0.6, 2s mono 44.1k
SILENCE = "/home/user/silence.wav"                 # 2s of silence
MIXED = "/home/user/mixed.wav"                     # 0-1s silence, 1-2s sine 440 @0.5
LOWFREQ = "/home/user/lowfreq.wav"                 # 200Hz sine, amp 0.5
HIGHFREQ = "/home/user/highfreq.wav"               # 8000Hz sine, amp 0.5

# Script generating fixtures inside the sandbox (pure stdlib: math+wave+struct)
AUDIO_GEN_SCRIPT = r"""
import math, struct, wave, os

SR = 44100

def write_wav(path, samples):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        pcm = bytearray()
        for s in samples:
            v = max(-1.0, min(1.0, s))
            i = int(v * 32767)
            pcm += struct.pack('<h', i)
        w.writeframes(bytes(pcm))

def sine(freq, dur, amp):
    n = int(SR * dur)
    return [amp * math.sin(2*math.pi*freq*i/SR) for i in range(n)]

def silence(dur):
    return [0.0] * int(SR * dur)

# 2s sine 440Hz loud  (peak ~ -1.94 dBFS)
write_wav('/home/user/sine440_loud.wav', sine(440, 2.0, 0.8))
# 2s sine 440Hz quiet (peak ~ -26 dBFS)
write_wav('/home/user/sine440_quiet.wav', sine(440, 2.0, 0.05))
# 2s sine 880Hz
write_wav('/home/user/sine880.wav', sine(880, 2.0, 0.6))
# 2s silence
write_wav('/home/user/silence.wav', silence(2.0))
# mixed: 0-1s silent, 1-2s sine 440 @ 0.5
write_wav('/home/user/mixed.wav', silence(1.0) + sine(440, 1.0, 0.5))
# 200Hz sine
write_wav('/home/user/lowfreq.wav', sine(200, 2.0, 0.5))
# 8000Hz sine
write_wav('/home/user/highfreq.wav', sine(8000, 2.0, 0.5))
print('ok')
"""

# ---------------------------------------------------------------------------
# Fixture contents
# ---------------------------------------------------------------------------

RICH_AUP_XML = """\
<?xml version="1.0" standalone="no" ?>
<!DOCTYPE project PUBLIC "-//audacityproject-1.3.0//DTD//EN" "http://audacity.sourceforge.net/xml/audacityproject-1.3.0.dtd" >
<project xmlns="http://audacity.sourceforge.net/xml/" projname="rich_data" version="1.3.0" audacityversion="2.4.2" sel0="0.0" sel1="2.0" selectionformat="hh:mm:ss" vpos="0" h="0.0" zoom="86.1328125" rate="44100.0" snapto="Off">
  <tags>
    <tag name="TITLE" value="Sunset Melody"/>
    <tag name="ARTIST" value="Demo Artist"/>
    <tag name="ALBUM" value="Test Album"/>
    <tag name="YEAR" value="2024"/>
    <tag name="GENRE" value="Ambient"/>
    <tag name="COMMENTS" value="A test project fixture"/>
  </tags>
  <wavetrack name="Vocal" channel="0" linked="0" mute="0" solo="0" height="150" minimized="0" isSelected="1" rate="44100" gain="1.0" pan="0.0">
    <waveclip offset="0.0" colorindex="0">
      <sequence maxsamples="262144" sampleformat="262159" numsamples="88200">
        <waveblock start="0">
          <simpleblockfile filename="e000001.au" len="88200" min="-0.8" max="0.8" rms="0.5"/>
        </waveblock>
      </sequence>
      <envelope numpoints="0"/>
    </waveclip>
  </wavetrack>
  <wavetrack name="Drums" channel="1" linked="0" mute="1" solo="0" height="100" minimized="0" isSelected="0" rate="44100" gain="0.5" pan="0.25">
    <waveclip offset="0.5" colorindex="2">
      <sequence maxsamples="262144" sampleformat="262159" numsamples="44100">
        <waveblock start="0">
          <simpleblockfile filename="e000002.au" len="44100" min="-0.9" max="0.9" rms="0.6"/>
        </waveblock>
        <waveblock start="44100">
          <simpleblockfile filename="e000003.au" len="44100" min="-0.7" max="0.7" rms="0.4"/>
        </waveblock>
      </sequence>
      <envelope numpoints="0"/>
    </waveclip>
  </wavetrack>
  <labeltrack name="Markers" numlabels="2" height="73" minimized="0" isSelected="0">
    <label t="0.5" t1="0.5" title="Intro"/>
    <label t="1.5" t1="1.5" title="Chorus"/>
  </labeltrack>
  <notetrack name="Notes" height="73" minimized="0" isSelected="0" visiblechannels="65535" offset="0.0" length="0.0"/>
  <timetrack name="Time Track" height="100" minimized="0" isSelected="0" rangelower="0.1" rangeupper="2.0" displaylog="0" interpolatelog="0"/>
</project>
"""

MIN_AUP_XML = """\
<?xml version="1.0" standalone="no" ?>
<project xmlns="http://audacity.sourceforge.net/xml/" projname="min_data" audacityversion="2.4.2" sel0="0.0" sel1="0.0" selectionformat="samples" vpos="0" h="0.0" zoom="100.0" rate="48000.0" snapto="Off">
  <wavetrack name="Track 1" channel="0" linked="0" mute="0" solo="0" rate="48000" gain="1.0" pan="0.0"/>
</project>
"""

MALFORMED_AUP_XML = "<?xml version='1.0'?><project rate='44100'"  # truncated
NOT_PROJECT_AUP_XML = "<?xml version='1.0'?><foo/>"

AUDACITY_CFG = """\
[Audacity]
Version=2.4.2

[AudioIO]
PlaybackDevice=default
RecordingDevice=
Host=ALSA

[Quality]
DefaultSampleRate=48000
DefaultSampleFormat=262159

[Warnings]
FirstProjectSave=1
SaveCompressed=0

[Theme]
Name=light

[QualityInternal]
SampleRate=44100
"""

PLUGIN_REGISTRY_CFG = """\
[audacity_builtin_AutoDuck]
id=builtin:auto-duck
name=Auto Duck
type=Effect
enabled=1

[audacity_builtin_Amplify]
id=builtin:amplify
name=Amplify
type=Effect
enabled=1
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"exit={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions audacity", "Audacity" in result.stdout, result.stdout[:100])


def test_errors(sandbox: Sandbox):
    print("\n=== Errors ===")

    r = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", r.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    r = run_raw(sandbox, "project-info")
    check("missing arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    data = run(sandbox, "project-info /nonexistent/path.aup")
    check("missing file returns error", "error" in data, str(data)[:120])

    data = run(sandbox, f"project-info {TINY_TXT}")
    check("wrong extension returns error", "error" in data, str(data)[:120])

    data = run(sandbox, f"project-info {MALFORMED_AUP}")
    check("malformed XML returns error", "error" in data, str(data)[:120])

    data = run(sandbox, f"project-info {NOT_PROJECT_AUP}")
    check("wrong root element returns error", "error" in data, str(data)[:120])

    data = run(sandbox, f"check-valid-aup {BROKEN_AUP}")
    check("missing data dir makes project invalid", data.get("valid") is False, str(data))
    check("missing data dir error surfaced", "data directory" in data.get("error", "").lower(), str(data))


def test_project_info(sandbox: Sandbox):
    print("\n=== project-info (rich) ===")
    data = run(sandbox, f"project-info {RICH_AUP}")
    check("dict", isinstance(data, dict), str(type(data)))
    check("wavetrack_count=2", data.get("wavetrack_count") == 2, str(data.get("wavetrack_count")))
    check("labeltrack_count=1", data.get("labeltrack_count") == 1, str(data.get("labeltrack_count")))
    check("notetrack_count=1", data.get("notetrack_count") == 1, str(data.get("notetrack_count")))
    check("timetrack_count=1", data.get("timetrack_count") == 1, str(data.get("timetrack_count")))
    check("total_track_count=5", data.get("total_track_count") == 5, str(data.get("total_track_count")))
    check("track_names contains Vocal", "Vocal" in (data.get("track_names") or []), str(data.get("track_names")))
    check("blockfile_count=3", data.get("blockfile_count") == 3, str(data.get("blockfile_count")))
    check("tag_count=6", data.get("tag_count") == 6, str(data.get("tag_count")))
    check("data_dir set", data.get("data_dir", "").endswith("rich_data"),
          data.get("data_dir", ""))
    check("data_dir_exists True", data.get("data_dir_exists") is True,
          str(data.get("data_dir_exists")))


def test_project_attrs(sandbox: Sandbox):
    print("\n=== project-attrs ===")
    data = run(sandbox, f"project-attrs {RICH_AUP}")
    check("attrs dict", isinstance(data, dict))
    check("rate=44100.0", data.get("rate") == "44100.0", str(data.get("rate")))
    check("snapto=Off", data.get("snapto") == "Off", str(data.get("snapto")))
    check("selectionformat=hh:mm:ss", data.get("selectionformat") == "hh:mm:ss",
          str(data.get("selectionformat")))
    check("audacityversion=2.4.2", data.get("audacityversion") == "2.4.2",
          str(data.get("audacityversion")))


def test_tracks_and_track(sandbox: Sandbox):
    print("\n=== tracks / track ===")
    data = run(sandbox, f"tracks {RICH_AUP}")
    check("tracks list", isinstance(data, list))
    check("tracks len=2", len(data) == 2, str(len(data)))
    if len(data) >= 2:
        t0 = data[0]
        check("track0 name=Vocal", t0.get("name") == "Vocal", str(t0.get("name")))
        check("track0 mute=0", t0.get("mute") == "0", str(t0.get("mute")))
        check("track0 gain=1.0", t0.get("gain") == "1.0", str(t0.get("gain")))
        check("track0 _clip_count=1", t0.get("_clip_count") == 1, str(t0.get("_clip_count")))
        t1 = data[1]
        check("track1 name=Drums", t1.get("name") == "Drums", str(t1.get("name")))
        check("track1 mute=1", t1.get("mute") == "1", str(t1.get("mute")))

    data = run(sandbox, f"track {RICH_AUP} 0")
    check("track by index=Vocal", data.get("name") == "Vocal", str(data.get("name")))

    data = run(sandbox, f"track {RICH_AUP} Drums")
    check("track by name=Drums", data.get("name") == "Drums", str(data.get("name")))

    data = run(sandbox, f"track {RICH_AUP} Nonexistent")
    check("track missing returns error", "error" in data, str(data)[:100])


def test_labels_and_aux(sandbox: Sandbox):
    print("\n=== labels / aux tracks ===")
    data = run(sandbox, f"label-tracks {RICH_AUP}")
    check("label-tracks list", isinstance(data, list))
    check("label-tracks len=1", len(data) == 1, str(len(data)))
    if data:
        check("label_count=2", data[0].get("_label_count") == 2,
              str(data[0].get("_label_count")))

    data = run(sandbox, f"labels {RICH_AUP}")
    check("labels list", isinstance(data, list))
    check("labels len=2", len(data) == 2, str(len(data)))
    titles = [l.get("title") for l in data] if isinstance(data, list) else []
    check("labels contains Intro", "Intro" in titles, str(titles))
    check("labels contains Chorus", "Chorus" in titles, str(titles))

    data = run(sandbox, f"note-tracks {RICH_AUP}")
    check("note-tracks len=1", isinstance(data, list) and len(data) == 1, str(data))

    data = run(sandbox, f"time-tracks {RICH_AUP}")
    check("time-tracks len=1", isinstance(data, list) and len(data) == 1, str(data))


def test_tags(sandbox: Sandbox):
    print("\n=== tags ===")
    data = run(sandbox, f"tags {RICH_AUP}")
    check("tags dict", isinstance(data, dict))
    check("TITLE=Sunset Melody", data.get("TITLE") == "Sunset Melody", str(data.get("TITLE")))
    check("ARTIST=Demo Artist", data.get("ARTIST") == "Demo Artist", str(data.get("ARTIST")))
    check("YEAR=2024", data.get("YEAR") == "2024", str(data.get("YEAR")))
    check("tag count=6", len(data) == 6, str(len(data)))


def test_preferences(sandbox: Sandbox):
    print("\n=== preferences ===")
    data = run(sandbox, "preferences")
    check("preferences dict", isinstance(data, dict))
    check("has AudioIO", "AudioIO" in data, str(list(data.keys())[:10]) if isinstance(data, dict) else str(data))

    data = run(sandbox, "preferences AudioIO")
    check("AudioIO.PlaybackDevice=default",
          isinstance(data, dict) and data.get("PlaybackDevice") == "default",
          str(data))

    data = run(sandbox, "preference AudioIO PlaybackDevice")
    check("preference value=default", data.get("value") == "default", str(data))

    data = run(sandbox, "preference-sections")
    check("sections list", isinstance(data, list))
    check("includes Quality", isinstance(data, list) and "Quality" in data, str(data))

    data = run(sandbox, "preferences NonExistentSection")
    check("missing section error", "error" in data, str(data)[:120])

    data = run(sandbox, "preference NonExistent Key")
    check("missing key error", "error" in data, str(data)[:120])


def test_plugins(sandbox: Sandbox):
    print("\n=== plugins ===")
    data = run(sandbox, "plugins")
    check("plugins dict", isinstance(data, dict), str(type(data)))
    check("has amplify entry",
          isinstance(data, dict) and "audacity_builtin_Amplify" in data,
          str(list(data.keys())[:5]) if isinstance(data, dict) else str(data))


def test_data_dir_info(sandbox: Sandbox):
    print("\n=== data-dir-info ===")
    data = run(sandbox, f"data-dir-info {RICH_AUP}")
    check("exists=True", data.get("exists") is True, str(data))
    check("file_count present", "file_count" in data, str(data))


def test_checks_positive(sandbox: Sandbox):
    print("\n=== Checks (positive) ===")
    def p(cmd, key, pretty):
        data = run(sandbox, cmd)
        val = data.get(key)
        check(pretty, val is True, f"{cmd} -> {data}")

    p(f"check-valid-aup {RICH_AUP}", "valid", "valid-aup rich")
    p(f"check-track-count {RICH_AUP} 2", "match", "track-count 2")
    p(f"check-labeltrack-count {RICH_AUP} 1", "match", "labeltrack-count 1")
    p(f"check-track-name {RICH_AUP} Vocal", "match", "track-name Vocal")
    p(f"check-track-rate {RICH_AUP} 44100", "match", "track-rate 44100")
    p(f"check-project-rate {RICH_AUP} 44100", "match", "project-rate 44100")
    p(f"check-track-mute {RICH_AUP} 1 true", "match", "track-mute 1 true")
    p(f"check-track-solo {RICH_AUP} 0 false", "match", "track-solo 0 false")
    p(f"check-track-gain {RICH_AUP} 0 1.0", "match", "track-gain 0 1.0")
    p(f"check-track-pan {RICH_AUP} 1 0.25", "match", "track-pan 1 0.25")
    p(f"check-snapto {RICH_AUP} Off", "match", "snapto Off")
    p(f"check-selection-format {RICH_AUP} hh:mm:ss", "match", "selection-format hh:mm:ss")
    p(f"check-blockfile-count-min {RICH_AUP} 1", "match", "blockfile-count-min 1")
    p(f"check-label-exists {RICH_AUP} Chorus", "match", "label-exists Chorus")
    p(f"check-label-count {RICH_AUP} 2", "match", "label-count 2")
    p(f"check-data-dir-exists {RICH_AUP}", "exists", "data-dir-exists")
    p(f"check-tag-value {RICH_AUP} TITLE 'Sunset Melody'", "match", "tag TITLE=Sunset Melody")
    p(f"check-tag-contains {RICH_AUP} COMMENTS project", "match", "tag COMMENTS contains 'project'")
    p(f"check-preference AudioIO PlaybackDevice default", "match", "pref AudioIO.PlaybackDevice")
    p(f"check-preference-exists Quality DefaultSampleRate", "exists", "pref Quality.DefaultSampleRate")
    p(f"check-file-exists {RICH_AUP}", "exists", "file-exists rich.aup")


def test_checks_negative(sandbox: Sandbox):
    print("\n=== Checks (negative) ===")

    def n(cmd, key, pretty):
        data = run(sandbox, cmd)
        val = data.get(key)
        check(pretty, val is False, f"{cmd} -> {data}")

    n(f"check-track-count {RICH_AUP} 99", "match", "track-count 99")
    n(f"check-track-name {RICH_AUP} NonExistent", "match", "track-name NonExistent")
    n(f"check-track-rate {RICH_AUP} 1000", "match", "track-rate 1000")
    n(f"check-project-rate {RICH_AUP} 48000", "match", "project-rate 48000")
    n(f"check-track-mute {RICH_AUP} 0 true", "match", "track0 mute true")
    n(f"check-track-solo {RICH_AUP} 1 true", "match", "track1 solo true")
    n(f"check-track-gain {RICH_AUP} 1 2.0", "match", "track1 gain 2.0")
    n(f"check-snapto {RICH_AUP} On", "match", "snapto On")
    n(f"check-label-exists {RICH_AUP} Bridge", "match", "label-exists Bridge")
    n(f"check-label-count {RICH_AUP} 99", "match", "label-count 99")
    n(f"check-tag-value {RICH_AUP} TITLE OtherTitle", "match", "tag TITLE=Other")
    n(f"check-preference AudioIO PlaybackDevice other", "match", "pref AudioIO wrong value")
    n(f"check-preference-exists Foo Bar", "exists", "pref Foo.Bar missing")
    n(f"check-file-exists /no/such/file.aup", "exists", "file-exists missing")
    n(f"check-file-size-min {TINY_TXT} 10000", "match", "file-size-min too large")


def test_min_fixture(sandbox: Sandbox):
    print("\n=== Minimal fixture ===")
    data = run(sandbox, f"project-info {MIN_AUP}")
    check("min wavetrack_count=1", data.get("wavetrack_count") == 1, str(data))
    check("min tag_count=0", data.get("tag_count") == 0, str(data))
    check("min blockfile=0", data.get("blockfile_count") == 0, str(data))

    data = run(sandbox, f"check-track-count {MIN_AUP} 1")
    check("min check-track-count=1", data.get("match") is True, str(data))

    data = run(sandbox, f"check-blockfile-count-min {MIN_AUP} 1")
    check("min check-blockfile-count-min 1 False",
          data.get("match") is False, str(data))

    data = run(sandbox, f"tags {MIN_AUP}")
    check("min tags empty", data == {}, str(data))


def test_exports(sandbox: Sandbox):
    print("\n=== Exports (ffprobe) ===")

    data = run(sandbox, f"export-info {OUT_WAV}")
    check("export-info dict", isinstance(data, dict))
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    check("export-info has audio stream", has_audio, str(data)[:200])

    data = run(sandbox, f"check-export-exists {OUT_WAV}")
    check("export-exists wav valid=True", data.get("valid") is True, str(data))

    data = run(sandbox, f"check-export-codec {OUT_WAV} pcm_s16le")
    check("export-codec wav pcm_s16le", data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-sample-rate {OUT_WAV} 44100")
    check("export-sample-rate wav 44100", data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-channels {OUT_WAV} 1")
    check("export-channels wav 1", data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-duration-min {OUT_WAV} 1.5")
    check("export-duration-min wav 1.5", data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-format {OUT_WAV} wav")
    check("export-format wav", data.get("match") is True, str(data))

    # Negative cases
    data = run(sandbox, f"check-export-codec {OUT_WAV} mp3")
    check("neg codec mp3", data.get("match") is False, str(data))
    data = run(sandbox, f"check-export-sample-rate {OUT_WAV} 48000")
    check("neg sample rate", data.get("match") is False, str(data))
    data = run(sandbox, f"check-export-channels {OUT_WAV} 2")
    check("neg channels", data.get("match") is False, str(data))
    data = run(sandbox, f"check-export-duration-min {OUT_WAV} 100")
    check("neg duration-min", data.get("match") is False, str(data))

    data = run(sandbox, f"check-export-codec {OUT_MP3} mp3")
    check("mp3 codec", data.get("match") is True, str(data))
    data = run(sandbox, f"check-export-channels {OUT_MP3} 2")
    check("mp3 channels=2", data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-exists /no/file.wav")
    check("export-exists missing valid=False", data.get("valid") is False, str(data))


def test_audio_content_checks(sandbox: Sandbox):
    print("\n=== Audio content checks (peak/rms/freq/band) ===")

    # --- check-export-peak-db ---
    # Loud sine 440 @ 0.8 -> peak ~ -1.94 dBFS
    data = run(sandbox, f"check-export-peak-db {SINE440_LOUD} -3 0")
    check("peak-db loud in [-3,0] positive",
          data.get("match") is True, str(data))
    check("peak-db reports numeric peak",
          isinstance(data.get("peak_db"), (int, float)), str(data))

    # Negative: claim it's inside a low range [-40,-20] (actual ~ -1.94)
    data = run(sandbox, f"check-export-peak-db {SINE440_LOUD} -40 -20")
    check("peak-db loud in [-40,-20] negative",
          data.get("match") is False, str(data))

    # Positive on quiet sine (amp 0.05 -> peak ~ -26 dBFS) in [-30,-20]
    data = run(sandbox, f"check-export-peak-db {SINE440_QUIET} -30 -20")
    check("peak-db quiet in [-30,-20] positive",
          data.get("match") is True, str(data))

    # Negative: quiet sine claimed in [-3,0]
    data = run(sandbox, f"check-export-peak-db {SINE440_QUIET} -3 0")
    check("peak-db quiet in [-3,0] negative",
          data.get("match") is False, str(data))

    # --- check-export-region-silent ---
    # Silent file for 0-2s with max_rms_db=-60 -> True
    data = run(sandbox, f"check-export-region-silent {SILENCE} 0 2 -60")
    check("region-silent silence.wav positive",
          data.get("match") is True, str(data))

    # Mixed: 0-1s is silent (True); 1-2s is loud sine (False)
    data = run(sandbox, f"check-export-region-silent {MIXED} 0 1 -60")
    check("region-silent mixed 0-1s silent positive",
          data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-region-silent {MIXED} 1 2 -60")
    check("region-silent mixed 1-2s loud negative",
          data.get("match") is False, str(data))

    # Negative case 2: loud sine flagged as silent -> False
    data = run(sandbox, f"check-export-region-silent {SINE440_LOUD} 0 2 -60")
    check("region-silent loud sine negative",
          data.get("match") is False, str(data))

    # --- check-export-region-rms-db ---
    # Full-amplitude sine 0.8 -> RMS = 0.8/sqrt(2) ~ 0.566 -> ~ -4.94 dB
    data = run(sandbox, f"check-export-region-rms-db {SINE440_LOUD} 0 2 -7 -3")
    check("region-rms-db loud in [-7,-3] positive",
          data.get("match") is True, str(data))

    # Negative: loud sine claimed in [-40,-20]
    data = run(sandbox, f"check-export-region-rms-db {SINE440_LOUD} 0 2 -40 -20")
    check("region-rms-db loud in [-40,-20] negative",
          data.get("match") is False, str(data))

    # Positive: quiet sine (amp 0.05 -> RMS ~ 0.0354 -> ~-29 dB) in [-32,-26]
    data = run(sandbox, f"check-export-region-rms-db {SINE440_QUIET} 0 2 -32 -26")
    check("region-rms-db quiet in [-32,-26] positive",
          data.get("match") is True, str(data))

    # --- check-export-dominant-freq (Goertzel) ---
    data = run(sandbox, f"check-export-dominant-freq {SINE440_LOUD} 0 2 440 2")
    check("dominant-freq 440 positive",
          data.get("match") is True, str(data))

    data = run(sandbox, f"check-export-dominant-freq {SINE880} 0 2 880 2")
    check("dominant-freq 880 positive",
          data.get("match") is True, str(data))

    # Negative: claim 440Hz sine is at 1000Hz
    data = run(sandbox, f"check-export-dominant-freq {SINE440_LOUD} 0 2 1000 2")
    check("dominant-freq 440 vs claim 1000 negative",
          data.get("match") is False, str(data))

    # Negative: 880Hz sine claimed at 440
    data = run(sandbox, f"check-export-dominant-freq {SINE880} 0 2 440 2")
    check("dominant-freq 880 vs claim 440 negative",
          data.get("match") is False, str(data))

    # --- check-export-band-energy-ratio-max (one-pole HP) ---
    # 200Hz sine, cutoff=2000Hz -> almost all energy is below cutoff ->
    # ratio near 0, <= 0.1 True
    data = run(sandbox, f"check-export-band-energy-ratio-max {LOWFREQ} 2000 0.1")
    check("band-energy low-freq ratio <=0.1 positive",
          data.get("match") is True, str(data))

    # 8kHz sine, cutoff=2000Hz -> most energy is above cutoff -> ratio near 1
    # Claim max_ratio=0.1 -> should be False
    data = run(sandbox, f"check-export-band-energy-ratio-max {HIGHFREQ} 2000 0.1")
    check("band-energy high-freq vs 0.1 negative",
          data.get("match") is False, str(data))

    # Positive on high-freq: ratio <= 1.0 (trivially)
    data = run(sandbox, f"check-export-band-energy-ratio-max {HIGHFREQ} 2000 1.0")
    check("band-energy high-freq vs 1.0 positive",
          data.get("match") is True, str(data))

    # Negative on low-freq: claim ratio <= 0.0 strict
    # (small but nonzero HP energy due to one-pole filter startup/leakage)
    # So this might actually pass; instead test missing file
    data = run(sandbox, f"check-export-band-energy-ratio-max /no/file.wav 2000 0.5")
    check("band-energy missing file returns match=False",
          data.get("match") is False, str(data))


def test_all_json_validity(sandbox: Sandbox):
    print("\n=== JSON validity sweep ===")
    cmds = [
        f"project-info {RICH_AUP}",
        f"project-attrs {RICH_AUP}",
        f"tracks {RICH_AUP}",
        f"track {RICH_AUP} 0",
        f"label-tracks {RICH_AUP}",
        f"labels {RICH_AUP}",
        f"note-tracks {RICH_AUP}",
        f"time-tracks {RICH_AUP}",
        f"tags {RICH_AUP}",
        f"blockfile-count {RICH_AUP}",
        f"data-dir-info {RICH_AUP}",
        "preferences",
        "preferences AudioIO",
        "preference AudioIO PlaybackDevice",
        "preference-sections",
        "plugins",
        f"check-valid-aup {RICH_AUP}",
        f"check-track-count {RICH_AUP} 2",
        f"check-track-name {RICH_AUP} Vocal",
        f"check-track-rate {RICH_AUP} 44100",
        f"check-project-rate {RICH_AUP} 44100",
        f"check-track-mute {RICH_AUP} 1 true",
        f"check-track-solo {RICH_AUP} 0 false",
        f"check-track-gain {RICH_AUP} 0 1.0",
        f"check-track-pan {RICH_AUP} 0 0.0",
        f"check-snapto {RICH_AUP} Off",
        f"check-selection-format {RICH_AUP} hh:mm:ss",
        f"check-blockfile-count-min {RICH_AUP} 1",
        f"check-label-exists {RICH_AUP} Intro",
        f"check-label-count {RICH_AUP} 2",
        f"check-data-dir-exists {RICH_AUP}",
        f"check-tag-value {RICH_AUP} YEAR 2024",
        f"check-tag-contains {RICH_AUP} ARTIST Demo",
        "check-preference AudioIO PlaybackDevice default",
        "check-preference-exists Quality DefaultSampleRate",
        f"check-file-exists {RICH_AUP}",
        f"check-file-size-min {RICH_AUP} 100",
        f"export-info {OUT_WAV}",
        f"check-export-exists {OUT_WAV}",
        f"check-export-codec {OUT_WAV} pcm_s16le",
        f"check-export-sample-rate {OUT_WAV} 44100",
        f"check-export-channels {OUT_WAV} 1",
        f"check-export-duration-min {OUT_WAV} 1.0",
        f"check-export-format {OUT_WAV} wav",
        f"check-export-peak-db {SINE440_LOUD} -3 0",
        f"check-export-region-silent {SILENCE} 0 2 -60",
        f"check-export-region-rms-db {SINE440_LOUD} 0 2 -7 -3",
        f"check-export-dominant-freq {SINE440_LOUD} 0 2 440 2",
        f"check-export-band-energy-ratio-max {LOWFREQ} 2000 0.1",
    ]
    for cmd in cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"JSON: {cmd.split()[0]}", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Error-path commands should also return JSON
    error_cmds = [
        "project-info /nonexistent.aup",
        "project-info /tmp/tiny.txt",
        f"project-info {MALFORMED_AUP}",
        f"check-export-exists /nope.wav",
    ]
    for cmd in error_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"JSON(err): {cmd.split()[0]}", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Sandbox setup
# ---------------------------------------------------------------------------

def write_fixtures(sandbox: Sandbox):
    print("\nWriting fixtures...")

    sandbox.commands.run("mkdir -p /home/user/verifiers", timeout=10)
    with open(VERIFIER_LOCAL) as f:
        sandbox.files.write(VERIFIER_REMOTE, f.read())

    # .aup XML fixtures
    sandbox.files.write(RICH_AUP, RICH_AUP_XML)
    sandbox.files.write(BROKEN_AUP, RICH_AUP_XML.replace("rich_data", "broken_data"))
    sandbox.files.write(MIN_AUP, MIN_AUP_XML)
    sandbox.files.write(MALFORMED_AUP, MALFORMED_AUP_XML)
    sandbox.files.write(NOT_PROJECT_AUP, NOT_PROJECT_AUP_XML)
    sandbox.commands.run(f"mkdir -p {RICH_DATA}/d00", timeout=5)
    sandbox.commands.run(f"echo 'fake audio block' > {RICH_DATA}/d00/e000001.au", timeout=5)

    # Tiny text file (for error/size tests)
    sandbox.files.write(TINY_TXT, "ab")

    # Preferences + plugin registry
    sandbox.commands.run("mkdir -p /home/user/.audacity-data", timeout=5)
    sandbox.files.write(CFG_PATH, AUDACITY_CFG)
    sandbox.files.write(PLUGREG_PATH, PLUGIN_REGISTRY_CFG)

    # ffmpeg-generated audio exports
    sandbox.commands.run(
        f'ffmpeg -y -f lavfi -i "sine=frequency=440:duration=2" '
        f'-ac 1 -ar 44100 -acodec pcm_s16le {OUT_WAV} > /dev/null 2>&1',
        timeout=30,
    )
    sandbox.commands.run(
        f'ffmpeg -y -f lavfi -i "sine=frequency=440:duration=2" '
        f'-ac 2 -ar 44100 -b:a 128k -acodec libmp3lame {OUT_MP3} > /dev/null 2>&1',
        timeout=30,
    )

    # Synthetic WAVs for content-analysis endpoints (pure stdlib)
    sandbox.files.write("/home/user/_gen_audio.py", AUDIO_GEN_SCRIPT)
    r = sandbox.commands.run("python3 /home/user/_gen_audio.py", timeout=60)
    if r.exit_code != 0:
        print(f"  WARN: audio fixture generation: exit={r.exit_code} stderr={r.stderr[:200]}")


def main():
    global passed, failed

    print("=" * 60)
    print("Audacity Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        write_fixtures(sandbox)

        test_help(sandbox)
        test_errors(sandbox)
        test_project_info(sandbox)
        test_project_attrs(sandbox)
        test_tracks_and_track(sandbox)
        test_labels_and_aux(sandbox)
        test_tags(sandbox)
        test_preferences(sandbox)
        test_plugins(sandbox)
        test_data_dir_info(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_min_fixture(sandbox)
        test_exports(sandbox)
        test_audio_content_checks(sandbox)
        test_all_json_validity(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors[:30]:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
