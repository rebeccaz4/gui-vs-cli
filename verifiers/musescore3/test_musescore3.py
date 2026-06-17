"""
Test MuseScore 3 verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage
  - Error cases
  - Score queries (.mscz → .mscx XML)
  - Preference queries (MuseScore3.ini)
  - Check endpoints (positive + negative)
  - Export format checks (MIDI / MusicXML / WAV / PDF / PNG)
  - JSON validity sweep over every endpoint

Test fixtures are constructed inside the sandbox with stdlib-only code (no mscore3
invocation is required — we feed the verifier hand-crafted .mscz files and fake
exported artifacts).

Usage:
    python verifiers/musescore3/test_musescore3.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "musescore3.py"
VERIFIER_REMOTE = "/home/user/verifiers/musescore3.py"
V = f"python3 {VERIFIER_REMOTE}"


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


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    try:
        r = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(r.exit_code, r.stdout, r.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run(sandbox: Sandbox, cmd: str, timeout: int = 30):
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  — {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Fixture creation script (runs inside the sandbox)
# ---------------------------------------------------------------------------

SETUP_SCRIPT = r'''
import os
import struct
import wave
import zipfile

os.makedirs("/home/user", exist_ok=True)

# ---------- Rich .mscz fixture ----------
def measure_with_notes(pitches):
    chords = "\n     ".join(
        f'<Chord><durationType>quarter</durationType><Note><pitch>{p}</pitch><tpc>{p % 12 + 14}</tpc></Note></Chord>'
        for p in pitches
    )
    return f"""   <Measure>
    <voice>
     {chords}
    </voice>
   </Measure>"""

def measure_with_lyrics(pitch_lyric_pairs):
    items = []
    for p, text, syl in pitch_lyric_pairs:
        items.append(
            f'<Chord><durationType>quarter</durationType>'
            f'<Lyrics><text>{text}</text><syllabic>{syl}</syllabic></Lyrics>'
            f'<Note><pitch>{p}</pitch><tpc>{p % 12 + 14}</tpc></Note></Chord>'
        )
    return f"""   <Measure>
    <voice>
     <TimeSig>
      <sigN>3</sigN>
      <sigD>4</sigD>
     </TimeSig>
     <KeySig>
      <accidental>2</accidental>
     </KeySig>
     <Tempo>
      <tempo>2.0</tempo>
      <text>Allegro</text>
     </Tempo>
     {chr(10).join(items)}
    </voice>
   </Measure>"""

rich_mscx = f"""<?xml version="1.0" encoding="UTF-8"?>
<museScore version="3.02">
 <Score>
  <Division>480</Division>
  <metaTag name="workTitle">Sonatina</metaTag>
  <metaTag name="composer">Ada Lovelace</metaTag>
  <metaTag name="copyright">CC-BY</metaTag>
  <metaTag name="arranger">Test Arranger</metaTag>
  <Part>
   <Staff id="1"/>
   <Instrument>
    <longName>Piano</longName>
    <shortName>Pno.</shortName>
    <trackName>Piano</trackName>
    <instrumentId>keyboard.piano</instrumentId>
   </Instrument>
  </Part>
  <Part>
   <Staff id="2"/>
   <Instrument>
    <longName>Violin</longName>
    <shortName>Vln.</shortName>
    <trackName>Violin</trackName>
    <instrumentId>strings.violin</instrumentId>
   </Instrument>
  </Part>
  <Staff id="1">
{measure_with_lyrics([(60, 'hel', 'begin'), (62, 'lo', 'end'), (64, 'world', 'single')])}
{measure_with_notes([65, 67, 69])}
{measure_with_notes([71, 72, 74])}
{measure_with_notes([76, 77, 79])}
  </Staff>
  <Staff id="2">
{measure_with_notes([48, 50, 52])}
{measure_with_notes([53, 55, 57])}
{measure_with_notes([59, 60, 62])}
{measure_with_notes([64, 65, 67])}
  </Staff>
 </Score>
</museScore>
"""

with zipfile.ZipFile("/home/user/test_rich.mscz", "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("test_rich.mscx", rich_mscx)

# ---------- Alt .mscz fixture ----------
alt_mscx = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="3.02">
 <Score>
  <Division>480</Division>
  <metaTag name="workTitle">Etude</metaTag>
  <Part>
   <Staff id="1"/>
   <Instrument>
    <longName>Flute</longName>
    <shortName>Fl.</shortName>
    <trackName>Flute</trackName>
    <instrumentId>wind.flutes.flute</instrumentId>
   </Instrument>
  </Part>
  <Staff id="1">
   <Measure>
    <voice>
     <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
     <KeySig><accidental>0</accidental></KeySig>
     <Tempo><tempo>1.333333</tempo><text>Andante</text></Tempo>
     <Chord><Note><pitch>72</pitch></Note></Chord>
    </voice>
   </Measure>
   <Measure><voice><Chord><Note><pitch>74</pitch></Note></Chord></voice></Measure>
   <Measure><voice><Chord><Note><pitch>76</pitch></Note></Chord></voice></Measure>
  </Staff>
 </Score>
</museScore>
"""
with zipfile.ZipFile("/home/user/test_alt.mscz", "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("test_alt.mscx", alt_mscx)

# ---------- Invalid mscz ----------
with open("/home/user/test_invalid.mscz", "wb") as f:
    f.write(b"this is not a zip file")

# ---------- Prefs INI ----------
ini_text = """[application]
firstStart=false
autoSave=true
autoSaveInterval=5
language=en_US

[ui]
application\\startup\\showSplashScreen=false
application\\startup\\showStartCenter=false
theme=dark
"""
with open("/home/user/test_prefs.ini", "w", encoding="utf-8") as f:
    f.write(ini_text)

# ---------- Fake MIDI Format 1, 1 track, 2 note-on, 1 set-tempo ----------
def make_midi():
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 1, 480)
    events = bytearray()
    # Delta 0, meta set-tempo (0xFF 0x51 03 <3 bytes micros per quarter>)
    events += bytes([0x00, 0xFF, 0x51, 0x03]) + (500000).to_bytes(3, "big")  # 120 BPM
    # Delta 0, note-on ch0 note 60 vel 100
    events += bytes([0x00, 0x90, 60, 100])
    # Delta 480, note-off ch0 note 60 vel 0
    events += bytes([0x83, 0x60, 0x80, 60, 0])
    # Delta 0, note-on ch0 note 64 vel 90
    events += bytes([0x00, 0x90, 64, 90])
    # Delta 480, note-off
    events += bytes([0x83, 0x60, 0x80, 64, 0])
    # End of track meta
    events += bytes([0x00, 0xFF, 0x2F, 0x00])
    track = b"MTrk" + struct.pack(">I", len(events)) + bytes(events)
    return header + track

with open("/home/user/test_fake.mid", "wb") as f:
    f.write(make_midi())

# ---------- Fake MusicXML ----------
musicxml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
 <part-list>
  <score-part id="P1">
   <part-name>Piano</part-name>
  </score-part>
 </part-list>
 <part id="P1">
  <measure number="1">
   <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
   <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration></note>
  </measure>
  <measure number="2">
   <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration></note>
  </measure>
 </part>
</score-partwise>
"""
with open("/home/user/test_fake.musicxml", "w", encoding="utf-8") as f:
    f.write(musicxml)

# ---------- Fake WAV ----------
with wave.open("/home/user/test_fake.wav", "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(22050)
    silence_frames = 11025  # 0.5 sec
    wf.writeframes(b"\x00\x00" * silence_frames)

# ---------- Fake PDF (magic only) ----------
with open("/home/user/test_fake.pdf", "wb") as f:
    f.write(b"%PDF-1.4\n%...\n")

# ---------- Not a PDF ----------
with open("/home/user/not_a_pdf.bin", "wb") as f:
    f.write(b"NOPE not a pdf\n")

# ---------- Fake PNG (signature + minimal chunks) ----------
import zlib
def make_png():
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, data):
        crc = struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + t + data + crc
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend

with open("/home/user/test_fake.png", "wb") as f:
    f.write(make_png())

# ---------- Feature-rich .mscz fixture (all new extension endpoints) ----------
# Covers: articulations (staccato, accent, tenuto), ornaments (trill, mordent),
# dynamics (mf, ff), hairpin (crescendo), chord symbol (Cmaj7), volta, repeats
# (start+end), markers (Segno), jumps (D.C. al Fine), layout breaks (line + page),
# Style values, instrument change, pedal, fingering.
feat_mscx = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<museScore version=\"3.02\">
 <Score>
  <Division>480</Division>
  <Style>
   <pageWidth>8.5</pageWidth>
   <pageHeight>11.0</pageHeight>
   <staffUpperBorder>7</staffUpperBorder>
   <showFooter>1</showFooter>
   <concertPitch>0</concertPitch>
  </Style>
  <metaTag name=\"workTitle\">FeatureShowcase</metaTag>
  <Part>
   <Staff id=\"1\"/>
   <Instrument>
    <longName>Piano</longName>
    <shortName>Pno.</shortName>
    <trackName>Piano</trackName>
    <instrumentId>keyboard.piano</instrumentId>
   </Instrument>
  </Part>
  <Staff id=\"1\">
   <Measure>
    <startRepeat/>
    <voice>
     <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
     <KeySig><accidental>0</accidental></KeySig>
     <Tempo><tempo>2.0</tempo><text>Allegro</text></Tempo>
     <Marker><text>Segno</text><label>segno</label></Marker>
     <Dynamic><subtype>mf</subtype></Dynamic>
     <Harmony><name>Cmaj7</name></Harmony>
     <Chord>
      <durationType>quarter</durationType>
      <Articulation><subtype>staccato</subtype></Articulation>
      <Fingering><text>1</text></Fingering>
      <Note><pitch>60</pitch><tpc>14</tpc></Note>
     </Chord>
     <Chord>
      <durationType>quarter</durationType>
      <Articulation><subtype>accent</subtype></Articulation>
      <Note><pitch>62</pitch><tpc>16</tpc></Note>
     </Chord>
     <Chord>
      <durationType>quarter</durationType>
      <Ornament><subtype>trill</subtype></Ornament>
      <Note><pitch>64</pitch><tpc>18</tpc></Note>
     </Chord>
     <Chord>
      <durationType>quarter</durationType>
      <Articulation><subtype>tenuto</subtype></Articulation>
      <Note><pitch>65</pitch><tpc>13</tpc></Note>
     </Chord>
    </voice>
    <LayoutBreak><subtype>line</subtype></LayoutBreak>
   </Measure>
   <Measure>
    <voice>
     <Pedal/>
     <Volta/>
     <Dynamic><subtype>ff</subtype></Dynamic>
     <Hairpin><subtype>0</subtype></Hairpin>
     <Chord>
      <durationType>quarter</durationType>
      <Articulation><subtype>mordent</subtype></Articulation>
      <Note><pitch>67</pitch><tpc>15</tpc></Note>
     </Chord>
     <Chord>
      <durationType>quarter</durationType>
      <Fingering><text>3</text></Fingering>
      <Note><pitch>69</pitch><tpc>17</tpc></Note>
     </Chord>
    </voice>
    <endRepeat/>
   </Measure>
   <Measure>
    <voice>
     <InstrumentChange>
      <text>To Flute</text>
      <Instrument>
       <longName>Flute</longName>
       <instrumentId>wind.flutes.flute</instrumentId>
      </Instrument>
     </InstrumentChange>
     <Chord><durationType>quarter</durationType><Note><pitch>72</pitch></Note></Chord>
     <Chord><durationType>quarter</durationType><Note><pitch>74</pitch></Note></Chord>
    </voice>
    <LayoutBreak><subtype>page</subtype></LayoutBreak>
   </Measure>
   <Measure>
    <voice>
     <Jump><text>D.C. al Fine</text><jumpTo>start</jumpTo></Jump>
     <Chord><durationType>quarter</durationType><Note><pitch>76</pitch></Note></Chord>
    </voice>
   </Measure>
  </Staff>
 </Score>
</museScore>
"""
with zipfile.ZipFile("/home/user/test_feat.mscz", "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("test_feat.mscx", feat_mscx)

# ---------- Bare .mscz fixture (none of the new features) ----------
bare_mscx = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<museScore version=\"3.02\">
 <Score>
  <Division>480</Division>
  <Style>
   <pageWidth>8.27</pageWidth>
   <pageHeight>11.69</pageHeight>
   <concertPitch>1</concertPitch>
  </Style>
  <metaTag name=\"workTitle\">Bare</metaTag>
  <Part>
   <Staff id=\"1\"/>
   <Instrument>
    <longName>Piano</longName>
    <shortName>Pno.</shortName>
    <trackName>Piano</trackName>
    <instrumentId>keyboard.piano</instrumentId>
   </Instrument>
  </Part>
  <Staff id=\"1\">
   <Measure>
    <voice>
     <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
     <KeySig><accidental>0</accidental></KeySig>
     <Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>
     <Chord><durationType>quarter</durationType><Note><pitch>62</pitch></Note></Chord>
    </voice>
   </Measure>
   <Measure>
    <voice>
     <Chord><durationType>quarter</durationType><Note><pitch>64</pitch></Note></Chord>
     <Chord><durationType>quarter</durationType><Note><pitch>65</pitch></Note></Chord>
    </voice>
   </Measure>
  </Staff>
 </Score>
</museScore>
"""
with zipfile.ZipFile("/home/user/test_bare.mscz", "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("test_bare.mscx", bare_mscx)

print("All MuseScore 3 test fixtures created successfully")
'''


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

RICH = "/home/user/test_rich.mscz"
ALT = "/home/user/test_alt.mscz"
INVALID = "/home/user/test_invalid.mscz"
INI = "/home/user/test_prefs.ini"
MIDI = "/home/user/test_fake.mid"
MXML = "/home/user/test_fake.musicxml"
WAVF = "/home/user/test_fake.wav"
PDFF = "/home/user/test_fake.pdf"
NOTPDF = "/home/user/not_a_pdf.bin"
PNGF = "/home/user/test_fake.png"
FEAT = "/home/user/test_feat.mscz"
BARE = "/home/user/test_bare.mscz"


def test_help(sandbox: Sandbox):
    print("\n=== G1 Help ===")
    r = run_raw(sandbox, "--help")
    check("help exits 0", r.exit_code == 0, f"exit={r.exit_code}")
    check("help mentions Commands:", "Commands:" in r.stdout, r.stdout[:120])
    check("help mentions .mscz or MuseScore",
          ".mscz" in r.stdout or "MuseScore" in r.stdout, r.stdout[:120])


def test_errors(sandbox: Sandbox):
    print("\n=== G2 Errors ===")
    r = run_raw(sandbox, "nonexistent-cmd")
    check("unknown cmd exits 1", r.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    r = run_raw(sandbox, "score-info")
    check("missing arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    d = run(sandbox, "score-info /home/user/does_not_exist.mscz")
    check("nonexistent file returns error", "error" in d, str(d)[:100])

    d = run(sandbox, f"score-info {INVALID}")
    check("invalid mscz returns error", "error" in d, str(d)[:100])


def test_score_queries(sandbox: Sandbox):
    print("\n=== G3 Score queries ===")

    d = run(sandbox, f"score-info {RICH}")
    check("score-info museScoreVersion", d.get("museScoreVersion") == "3.02", str(d)[:120])
    check("score-info division", d.get("division") == "480", str(d)[:120])

    d = run(sandbox, f"metadata {RICH}")
    check("metadata workTitle", d.get("workTitle") == "Sonatina", str(d)[:120])
    check("metadata composer", d.get("composer") == "Ada Lovelace", str(d)[:120])
    check("metadata copyright", d.get("copyright") == "CC-BY", str(d)[:120])

    d = run(sandbox, f"parts {RICH}")
    check("parts is list of 2", isinstance(d, list) and len(d) == 2, str(d)[:120])
    if isinstance(d, list) and len(d) >= 2:
        names = {p.get("longName") for p in d}
        check("parts contains Piano+Violin", {"Piano", "Violin"}.issubset(names), str(names))

    d = run(sandbox, f"staves {RICH}")
    check("staves list length 2", isinstance(d, list) and len(d) == 2, str(d)[:120])
    if isinstance(d, list) and len(d) >= 2:
        check("staff 0 has 4 measures", d[0].get("measure_count") == 4, str(d[0]))
        check("staff 1 has 4 measures", d[1].get("measure_count") == 4, str(d[1]))

    d = run(sandbox, f"time-signature {RICH}")
    check("time-signature 3/4",
          d.get("numerator") == 3 and d.get("denominator") == 4, str(d))

    d = run(sandbox, f"key-signature {RICH}")
    check("key-signature 2 sharps", d.get("accidental") == 2, str(d))

    d = run(sandbox, f"tempo {RICH}")
    check("tempo 120 BPM", d.get("bpm") == 120.0, str(d))

    d = run(sandbox, f"measure-count {RICH}")
    check("measure-count 4", d.get("measure_count") == 4, str(d))

    d = run(sandbox, f"note-count {RICH}")
    # 3 lyric chords + 3 measures * 3 notes (staff 1) + 4 measures * 3 notes (staff 2) = 3 + 9 + 12 = 24
    check("note-count 24", d.get("note_count") == 24, str(d))

    d = run(sandbox, f"lyrics {RICH}")
    check("lyrics has 3 entries", isinstance(d, list) and len(d) == 3, str(d)[:120])
    check("lyrics first text 'hel'", d[0].get("text") == "hel" if d else False, str(d)[:120])

    d = run(sandbox, f"instruments {RICH}")
    check("instruments Piano+Violin", d == ["Piano", "Violin"], str(d))

    # Alt file
    d = run(sandbox, f"time-signature {ALT}")
    check("alt time-signature 4/4",
          d.get("numerator") == 4 and d.get("denominator") == 4, str(d))
    d = run(sandbox, f"key-signature {ALT}")
    check("alt key-signature 0", d.get("accidental") == 0, str(d))


def test_preferences(sandbox: Sandbox):
    print("\n=== G4 Preference queries ===")

    d = run(sandbox, f"preferences {INI}")
    check("preferences returns dict", isinstance(d, dict), str(type(d)))
    check("preferences has application section", "application" in d, str(d)[:120])
    check("preferences has ui section", "ui" in d, str(d)[:120])

    d = run(sandbox, f"preference application.firstStart {INI}")
    check("preference firstStart value", d.get("value") == "false", str(d)[:120])

    # Qt-style backslash key matched via slash-form
    d = run(sandbox, f"preference ui.application/startup/showSplashScreen {INI}")
    check("preference splash screen (slash-form)", d.get("value") == "false", str(d)[:120])

    d = run(sandbox, f"preference nothere.key {INI}")
    check("missing section returns error", "error" in d, str(d)[:120])


def test_checks_positive(sandbox: Sandbox):
    print("\n=== G5 Checks (positive) ===")

    d = run(sandbox, f"check-file-exists {RICH}")
    check("check-file-exists true", d.get("exists") is True, str(d)[:100])

    d = run(sandbox, f"check-meta-tag {RICH} workTitle Sonatina")
    check("check-meta-tag workTitle match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-has-meta-tag {RICH} composer")
    check("check-has-meta-tag composer true", d.get("exists") is True, str(d)[:120])

    d = run(sandbox, f"check-time-signature {RICH} 3 4")
    check("check-time-signature 3/4 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-key-signature {RICH} 2")
    check("check-key-signature 2 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-tempo {RICH} 120")
    check("check-tempo 120 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-measure-count {RICH} 4")
    check("check-measure-count 4 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-note-count {RICH} 24")
    check("check-note-count 24 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-note-count-at-least {RICH} 10")
    check("check-note-count-at-least 10 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-part-count {RICH} 2")
    check("check-part-count 2 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-instrument {RICH} Piano")
    check("check-instrument Piano exists", d.get("exists") is True, str(d)[:120])

    d = run(sandbox, f"check-has-lyrics {RICH}")
    check("check-has-lyrics true", d.get("has_lyrics") is True, str(d)[:120])

    d = run(sandbox, f"check-lyric-text {RICH} hel")
    check("check-lyric-text hel match", d.get("match") is True, str(d)[:120])


def test_checks_negative(sandbox: Sandbox):
    print("\n=== G6 Checks (negative) ===")

    d = run(sandbox, "check-file-exists /home/user/no_such_song.mscz")
    check("check-file-exists false", d.get("exists") is False, str(d)[:100])

    d = run(sandbox, f"check-meta-tag {RICH} workTitle Wrong")
    check("check-meta-tag wrong value false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-has-meta-tag {RICH} nonexistent_tag_xyz")
    check("check-has-meta-tag missing false", d.get("exists") is False, str(d)[:120])

    d = run(sandbox, f"check-time-signature {RICH} 6 8")
    check("check-time-signature wrong false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-key-signature {RICH} 0")
    check("check-key-signature wrong false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-tempo {RICH} 90")
    check("check-tempo wrong false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-measure-count {RICH} 99")
    check("check-measure-count wrong false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-note-count {RICH} 999")
    check("check-note-count wrong false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-part-count {RICH} 5")
    check("check-part-count wrong false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-instrument {RICH} Trombone")
    check("check-instrument missing false", d.get("exists") is False, str(d)[:120])

    d = run(sandbox, f"check-lyric-text {RICH} zzz_never")
    check("check-lyric-text missing false", d.get("match") is False, str(d)[:120])


def test_preference_checks(sandbox: Sandbox):
    print("\n=== G7 Preference checks ===")

    d = run(sandbox, f"check-preference application.firstStart false {INI}")
    check("check-preference firstStart=false match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-preference-exists application.firstStart {INI}")
    check("check-preference-exists firstStart true", d.get("exists") is True, str(d)[:120])

    d = run(sandbox, f"check-preference application.firstStart true {INI}")
    check("check-preference firstStart=true mismatch", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-preference-exists application.no_such_key {INI}")
    check("check-preference-exists missing false", d.get("exists") is False, str(d)[:120])


def test_exports(sandbox: Sandbox):
    print("\n=== G8 Exports ===")

    # MIDI
    d = run(sandbox, f"midi-info {MIDI}")
    check("midi-info format=1", d.get("format") == 1, str(d)[:120])
    check("midi-info track_count=1", d.get("track_count") == 1, str(d)[:120])
    check("midi-info note_on_count=2", d.get("note_on_count") == 2, str(d)[:120])
    check("midi-info tempo_bpm=120", d.get("tempo_bpm") == 120.0, str(d)[:120])

    d = run(sandbox, f"check-midi-track-count {MIDI} 1")
    check("check-midi-track-count 1 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-midi-track-count {MIDI} 5")
    check("check-midi-track-count 5 mismatch", d.get("match") is False, str(d)[:120])

    d = run(sandbox, f"check-midi-has-notes {MIDI} 2")
    check("check-midi-has-notes >=2 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-midi-has-notes {MIDI} 999")
    check("check-midi-has-notes >=999 mismatch", d.get("match") is False, str(d)[:120])

    # MusicXML
    d = run(sandbox, f"musicxml-info {MXML}")
    check("musicxml-info part_count=1", d.get("part_count") == 1, str(d)[:120])
    check("musicxml-info measure_count=2", d.get("measure_count") == 2, str(d)[:120])
    check("musicxml-info note_count=3", d.get("note_count") == 3, str(d)[:120])

    d = run(sandbox, f"check-musicxml-parts {MXML} 1")
    check("check-musicxml-parts 1 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-musicxml-parts {MXML} 5")
    check("check-musicxml-parts 5 mismatch", d.get("match") is False, str(d)[:120])

    # WAV
    d = run(sandbox, f"wav-info {WAVF}")
    check("wav-info sample_rate 22050", d.get("sample_rate") == 22050, str(d)[:120])
    check("wav-info channels 1", d.get("channels") == 1, str(d)[:120])

    d = run(sandbox, f"check-wav-duration {WAVF} 0.1")
    check("check-wav-duration >=0.1 match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-wav-duration {WAVF} 60")
    check("check-wav-duration >=60 mismatch", d.get("match") is False, str(d)[:120])

    # PDF
    d = run(sandbox, f"check-pdf-exists {PDFF}")
    check("check-pdf-exists true", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-pdf-exists {NOTPDF}")
    check("check-pdf-exists (not pdf) false", d.get("match") is False, str(d)[:120])

    # PNG
    d = run(sandbox, f"check-png-exists {PNGF}")
    check("check-png-exists true", d.get("match") is True, str(d)[:120])

    d = run(sandbox, f"check-png-exists {NOTPDF}")
    check("check-png-exists (wrong file) false", d.get("match") is False, str(d)[:120])


def test_extension_queries(sandbox: Sandbox):
    """G10a: query endpoints for every new family (positive via FEAT, empty via BARE)."""
    print("\n=== G10a Extension queries ===")

    # articulations (family)
    d = run(sandbox, f"articulations {FEAT}")
    check("articulations is list",
          isinstance(d, list), str(d)[:120])
    subs = {a.get("subtype") for a in d if isinstance(a, dict)}
    check("articulations contains staccato/accent/tenuto",
          {"staccato", "accent", "tenuto"}.issubset(subs), str(subs))
    d = run(sandbox, f"articulations {BARE}")
    check("articulations empty on bare", d == [], str(d)[:120])

    # dynamics (family)
    d = run(sandbox, f"dynamics {FEAT}")
    subs = {x.get("subtype") for x in d if isinstance(x, dict)}
    check("dynamics contains mf+ff", {"mf", "ff"}.issubset(subs), str(subs))
    d = run(sandbox, f"dynamics {BARE}")
    check("dynamics empty on bare", d == [], str(d)[:120])

    # hairpins (family)
    d = run(sandbox, f"hairpins {FEAT}")
    check("hairpins len>=1", isinstance(d, list) and len(d) >= 1, str(d)[:120])
    d = run(sandbox, f"hairpins {BARE}")
    check("hairpins empty on bare", d == [], str(d)[:120])

    # chord-symbols (family)
    d = run(sandbox, f"chord-symbols {FEAT}")
    texts = {x.get("text") for x in d if isinstance(x, dict)}
    check("chord-symbols contains Cmaj7", "Cmaj7" in texts, str(texts))

    # voltas (family)
    d = run(sandbox, f"voltas {FEAT}")
    check("voltas len>=1", isinstance(d, list) and len(d) >= 1, str(d)[:120])

    # repeats (family)
    d = run(sandbox, f"repeats {FEAT}")
    check("repeats starts contains 1", 1 in d.get("start_repeats", []), str(d)[:120])
    check("repeats ends contains 2", 2 in d.get("end_repeats", []), str(d)[:120])

    # jumps-markers (family)
    d = run(sandbox, f"jumps-markers {FEAT}")
    check("jumps-markers has 1 marker",
          isinstance(d, dict) and len(d.get("markers", [])) == 1, str(d)[:160])
    check("jumps-markers has 1 jump",
          isinstance(d, dict) and len(d.get("jumps", [])) == 1, str(d)[:160])

    # layout-breaks (family)
    d = run(sandbox, f"layout-breaks {FEAT}")
    subs = {b.get("subtype") for b in d if isinstance(b, dict)}
    check("layout-breaks contains line+page", {"line", "page"}.issubset(subs), str(subs))

    # style (family)
    d = run(sandbox, f"style {FEAT}")
    check("style has pageWidth 8.5",
          isinstance(d, dict) and d.get("pageWidth") == "8.5", str(d)[:160])

    # instrument-changes (family)
    d = run(sandbox, f"instrument-changes {FEAT}")
    check("instrument-changes len>=1",
          isinstance(d, list) and len(d) >= 1, str(d)[:160])

    # pedals (family)
    d = run(sandbox, f"pedals {FEAT}")
    check("pedals len>=1", isinstance(d, list) and len(d) >= 1, str(d)[:120])
    d = run(sandbox, f"pedals {BARE}")
    check("pedals empty on bare", d == [], str(d)[:120])

    # fingerings (family)
    d = run(sandbox, f"fingerings {FEAT}")
    check("fingerings len>=2", isinstance(d, list) and len(d) >= 2, str(d)[:120])

    # ornaments (family)
    d = run(sandbox, f"ornaments {FEAT}")
    kinds = " ".join(o.get("subtype", "") for o in d if isinstance(o, dict)).lower()
    check("ornaments contains trill", "trill" in kinds, kinds[:120])
    check("ornaments contains mordent", "mordent" in kinds, kinds[:120])


def test_extension_checks(sandbox: Sandbox):
    """G10b: positive + negative for every new check-* endpoint."""
    print("\n=== G10b Extension check-* endpoints ===")

    # check-articulation-in-measure
    d = run(sandbox, f"check-articulation-in-measure {FEAT} 1 staccato")
    check("art-in-measure staccato@1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-articulation-in-measure {FEAT} 1 fermata")
    check("art-in-measure fermata@1 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-articulation-in-measure {BARE} 1 staccato")
    check("art-in-measure @bare neg", d.get("match") is False, str(d)[:160])

    # check-articulation-count
    d = run(sandbox, f"check-articulation-count {FEAT} staccato 1")
    check("art-count staccato=1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-articulation-count {FEAT} staccato 99")
    check("art-count staccato=99 neg", d.get("match") is False, str(d)[:160])

    # check-dynamic-in-measure
    d = run(sandbox, f"check-dynamic-in-measure {FEAT} 1 mf")
    check("dynamic mf@1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-dynamic-in-measure {FEAT} 1 pp")
    check("dynamic pp@1 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-dynamic-in-measure {FEAT} 2 ff")
    check("dynamic ff@2 pos", d.get("match") is True, str(d)[:160])

    # check-has-hairpin
    d = run(sandbox, f"check-has-hairpin {FEAT} crescendo")
    check("has-hairpin crescendo pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-has-hairpin {FEAT} decrescendo")
    check("has-hairpin decrescendo neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-has-hairpin {BARE} crescendo")
    check("has-hairpin @bare neg", d.get("match") is False, str(d)[:160])

    # check-chord-symbol-in-measure
    d = run(sandbox, f"check-chord-symbol-in-measure {FEAT} 1 Cmaj7")
    check("chord-sym Cmaj7@1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-chord-symbol-in-measure {FEAT} 1 Dm7")
    check("chord-sym Dm7@1 neg", d.get("match") is False, str(d)[:160])

    # check-has-volta-at
    d = run(sandbox, f"check-has-volta-at {FEAT} 2")
    check("volta@2 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-has-volta-at {FEAT} 1")
    check("volta@1 neg", d.get("match") is False, str(d)[:160])

    # check-start-repeat-at / check-end-repeat-at
    d = run(sandbox, f"check-start-repeat-at {FEAT} 1")
    check("start-repeat@1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-start-repeat-at {FEAT} 3")
    check("start-repeat@3 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-end-repeat-at {FEAT} 2")
    check("end-repeat@2 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-end-repeat-at {FEAT} 1")
    check("end-repeat@1 neg", d.get("match") is False, str(d)[:160])

    # check-marker-text
    d = run(sandbox, f"check-marker-text {FEAT} Segno")
    check("marker Segno pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-marker-text {FEAT} Coda")
    check("marker Coda neg", d.get("match") is False, str(d)[:160])

    # check-jump-text
    d = run(sandbox, f"check-jump-text {FEAT} D.C.")
    check("jump D.C. pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-jump-text {FEAT} Coda")
    check("jump Coda neg", d.get("match") is False, str(d)[:160])

    # check-layout-break-at (with subtype)
    d = run(sandbox, f"check-layout-break-at {FEAT} 1 line")
    check("layout-break line@1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-layout-break-at {FEAT} 1 page")
    check("layout-break page@1 neg (wrong subtype)", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-layout-break-at {FEAT} 3 page")
    check("layout-break page@3 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-layout-break-at {FEAT} 4 line")
    check("layout-break line@4 neg", d.get("match") is False, str(d)[:160])

    # check-style-value (numeric + string)
    d = run(sandbox, f"check-style-value {FEAT} pageWidth 8.5")
    check("style pageWidth=8.5 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-style-value {FEAT} pageWidth 12.0")
    check("style pageWidth=12 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-style-value {FEAT} concertPitch 0")
    check("style concertPitch=0 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-style-value {BARE} concertPitch 1")
    check("style concertPitch=1 pos on bare", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-style-value {BARE} concertPitch 0")
    check("style concertPitch=0 neg on bare", d.get("match") is False, str(d)[:160])

    # check-instrument-change-at
    d = run(sandbox, f"check-instrument-change-at {FEAT} 3 Flute")
    check("instr-change Flute@3 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-instrument-change-at {FEAT} 3 Trombone")
    check("instr-change Trombone@3 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-instrument-change-at {FEAT} 1 Flute")
    check("instr-change Flute@1 neg (wrong measure)", d.get("match") is False, str(d)[:160])

    # check-has-pedal
    d = run(sandbox, f"check-has-pedal {FEAT}")
    check("has-pedal pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-has-pedal {BARE}")
    check("has-pedal @bare neg", d.get("match") is False, str(d)[:160])

    # check-fingering-count-in-measure
    d = run(sandbox, f"check-fingering-count-in-measure {FEAT} 1 1")
    check("fingering-count@1 >=1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-fingering-count-in-measure {FEAT} 1 5")
    check("fingering-count@1 >=5 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-fingering-count-in-measure {BARE} 1 1")
    check("fingering-count @bare neg", d.get("match") is False, str(d)[:160])

    # check-has-ornament
    d = run(sandbox, f"check-has-ornament {FEAT} 1 trill")
    check("ornament trill@1 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-has-ornament {FEAT} 2 mordent")
    check("ornament mordent@2 pos", d.get("match") is True, str(d)[:160])
    d = run(sandbox, f"check-has-ornament {FEAT} 1 turn")
    check("ornament turn@1 neg", d.get("match") is False, str(d)[:160])
    d = run(sandbox, f"check-has-ornament {BARE} 1 trill")
    check("ornament trill @bare neg", d.get("match") is False, str(d)[:160])


def test_json_sweep(sandbox: Sandbox):
    print("\n=== G9 JSON validity sweep ===")
    cases = [
        f"score-info {RICH}",
        f"metadata {RICH}",
        f"parts {RICH}",
        f"staves {RICH}",
        f"time-signature {RICH}",
        f"key-signature {RICH}",
        f"tempo {RICH}",
        f"measure-count {RICH}",
        f"note-count {RICH}",
        f"lyrics {RICH}",
        f"instruments {RICH}",
        f"preferences {INI}",
        f"preference application.firstStart {INI}",
        f"check-file-exists {RICH}",
        f"check-meta-tag {RICH} workTitle Sonatina",
        f"check-has-meta-tag {RICH} composer",
        f"check-time-signature {RICH} 3 4",
        f"check-key-signature {RICH} 2",
        f"check-tempo {RICH} 120",
        f"check-measure-count {RICH} 4",
        f"check-note-count {RICH} 24",
        f"check-note-count-at-least {RICH} 1",
        f"check-part-count {RICH} 2",
        f"check-instrument {RICH} Piano",
        f"check-has-lyrics {RICH}",
        f"check-lyric-text {RICH} hel",
        f"check-preference application.firstStart false {INI}",
        f"check-preference-exists application.firstStart {INI}",
        f"midi-info {MIDI}",
        f"check-midi-track-count {MIDI} 1",
        f"check-midi-has-notes {MIDI} 1",
        f"musicxml-info {MXML}",
        f"check-musicxml-parts {MXML} 1",
        f"wav-info {WAVF}",
        f"check-wav-duration {WAVF} 0.1",
        f"check-pdf-exists {PDFF}",
        f"check-png-exists {PNGF}",
        # Extension queries
        f"articulations {FEAT}",
        f"dynamics {FEAT}",
        f"hairpins {FEAT}",
        f"chord-symbols {FEAT}",
        f"voltas {FEAT}",
        f"repeats {FEAT}",
        f"jumps-markers {FEAT}",
        f"layout-breaks {FEAT}",
        f"style {FEAT}",
        f"instrument-changes {FEAT}",
        f"pedals {FEAT}",
        f"fingerings {FEAT}",
        f"ornaments {FEAT}",
        # Extension checks
        f"check-articulation-in-measure {FEAT} 1 staccato",
        f"check-articulation-count {FEAT} staccato 1",
        f"check-dynamic-in-measure {FEAT} 1 mf",
        f"check-has-hairpin {FEAT} crescendo",
        f"check-chord-symbol-in-measure {FEAT} 1 Cmaj7",
        f"check-has-volta-at {FEAT} 2",
        f"check-start-repeat-at {FEAT} 1",
        f"check-end-repeat-at {FEAT} 2",
        f"check-marker-text {FEAT} Segno",
        f"check-jump-text {FEAT} D.C.",
        f"check-layout-break-at {FEAT} 1 line",
        f"check-style-value {FEAT} pageWidth 8.5",
        f"check-instrument-change-at {FEAT} 3 Flute",
        f"check-has-pedal {FEAT}",
        f"check-fingering-count-in-measure {FEAT} 1 1",
        f"check-has-ornament {FEAT} 1 trill",
    ]
    for cmd in cases:
        r = run_raw(sandbox, cmd)
        ok = is_valid_json(r.stdout)
        check(f"JSON: {cmd.split()[0]}", ok,
              f"exit={r.exit_code} stdout={r.stdout[:80]}" if not ok else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("MuseScore 3 Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        print("Creating fixtures in sandbox...")
        sandbox.files.write("/home/user/setup_musescore3_fixtures.py", SETUP_SCRIPT)
        r = sandbox.commands.run(
            "python3 /home/user/setup_musescore3_fixtures.py", timeout=120
        )
        print(f"  {r.stdout.strip()}")
        if r.exit_code != 0:
            print(f"  setup stderr: {r.stderr}")
            raise RuntimeError(f"fixture setup failed: {r.stderr}")

        test_help(sandbox)
        test_errors(sandbox)
        test_score_queries(sandbox)
        test_preferences(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_preference_checks(sandbox)
        test_exports(sandbox)
        test_extension_queries(sandbox)
        test_extension_checks(sandbox)
        test_json_sweep(sandbox)

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
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
