#!/usr/bin/env python3
"""
MuseScore 3 CLI: Add Lyrics to Melody

This script adds lyrics to notes in a MuseScore .mscz file.
.mscz files are ZIP archives containing a .mscx file (XML format).

Usage:
    python add_lyrics.py <input.mscz> <output.mscz> <lyrics>

Example:
    python add_lyrics.py melody.mscz melody.mscz "hello world sing out"

Notes:
    - Lyrics are space-separated syllables
    - Each syllable is attached to a sequential note
    - The script adds lyrics to the first staff in the score
"""

import sys
import zipfile
import tempfile
import os
from xml.etree import ElementTree as ET


def add_lyrics(input_mscz, output_mscz, lyrics_text):
    """
    Add lyrics to the first notes in a MuseScore score.

    Args:
        input_mscz: Path to input .mscz file
        output_mscz: Path to output .mscz file (can be same as input)
        lyrics_text: Space-separated lyrics syllables
    """
    print(f"Adding lyrics: '{lyrics_text}'...")

    # Split lyrics into syllables
    syllables = lyrics_text.split()
    if not syllables:
        raise ValueError("No lyrics provided")

    print(f"Adding {len(syllables)} syllables to notes")

    # Create temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract the mscz file (it's a ZIP archive)
        print(f"Extracting {input_mscz}...")
        with zipfile.ZipFile(input_mscz, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # Find the .mscx file inside
        mscx_files = [f for f in os.listdir(temp_dir) if f.endswith('.mscx')]
        if not mscx_files:
            raise ValueError("No .mscx file found in the archive")
        if len(mscx_files) > 1:
            raise ValueError(f"Multiple .mscx files found: {mscx_files}")

        mscx_path = os.path.join(temp_dir, mscx_files[0])
        print(f"Processing {mscx_files[0]}...")

        # Parse the XML
        tree = ET.parse(mscx_path)
        root = tree.getroot()

        # Find all Chord elements (each Chord represents a note/rest in MuseScore)
        # and add lyrics to them
        chords = []
        for chord in root.iter('Chord'):
            chords.append(chord)

        if len(chords) < len(syllables):
            print(f"Warning: Only {len(chords)} notes available, but {len(syllables)} syllables provided")
            syllables = syllables[:len(chords)]

        # Add lyrics to the first N chords
        lyrics_added = 0
        for i, chord in enumerate(chords):
            if i >= len(syllables):
                break

            # Create a new Lyric element
            lyric = ET.SubElement(chord, 'Lyric')
            lyric.set('number', '1')  # Verse number

            # Create text element
            text = ET.SubElement(lyric, 'text')
            text.text = syllables[i]

            # Create syllabic element (single syllable)
            syllabic = ET.SubElement(lyric, 'syllabic')
            syllabic.text = 'single'

            lyrics_added += 1

        print(f"Added {lyrics_added} lyrics to notes")

        # Write the modified XML back
        tree.write(mscx_path, encoding='UTF-8', xml_declaration=True)

        # Create a new ZIP archive with the modified content
        print(f"Creating {output_mscz}...")
        with zipfile.ZipFile(output_mscz, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
            for root_dir, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root_dir, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zip_ref.write(file_path, arcname)

        print(f"Successfully added lyrics in {output_mscz}")


def main():
    if len(sys.argv) != 4:
        print("Usage: python add_lyrics.py <input.mscz> <output.mscz> <lyrics>")
        print("Example: python add_lyrics.py melody.mscz melody.mscz \"hello world sing out\"")
        print("")
        print("Notes:")
        print("  - Lyrics are space-separated syllables")
        print("  - Each syllable is attached to a sequential note")
        print("  - Use quotes around the lyrics text")
        sys.exit(1)

    input_mscz = sys.argv[1]
    output_mscz = sys.argv[2]
    lyrics = sys.argv[3]

    if not os.path.exists(input_mscz):
        print(f"Error: Input file not found: {input_mscz}")
        sys.exit(1)

    try:
        add_lyrics(input_mscz, output_mscz, lyrics)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
