#!/usr/bin/env python3
"""
MuseScore 3 CLI: Add Staccato Articulation

This script adds staccato articulations to notes in a MuseScore .mscz file.
.mscz files are ZIP archives containing a .mscx file (XML format).

Usage:
    python add_staccato.py <input.mscz> <output.mscz> [--measure <n>] [--count <n>]

Examples:
    python add_staccato.py staccato_etude.mscz staccato_etude.mscz --measure 1 --count 4
    python add_staccato.py input.mscz output.mscz  # Add to all notes

Notes:
    --measure: Only add staccato to notes in specific measure (1-indexed)
    --count: Maximum number of notes to add staccato to
"""

import sys
import zipfile
import tempfile
import os
import argparse
from xml.etree import ElementTree as ET


def add_staccato(input_mscz, output_mscz, measure_num=None, max_count=None):
    """
    Add staccato articulations to notes in a MuseScore score.

    Args:
        input_mscz: Path to input .mscz file
        output_mscz: Path to output .mscz file (can be same as input)
        measure_num: Only process this specific measure (1-indexed, None for all)
        max_count: Maximum number of notes to add staccato to (None for all)
    """
    print(f"Adding staccato articulations...")

    if measure_num:
        print(f"Limiting to measure {measure_num}")
    if max_count:
        print(f"Limiting to {max_count} notes")

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

        # Count measures to find the target one
        measures = list(root.iter('Measure'))
        print(f"Found {len(measures)} measures in score")

        # Find Chord elements (notes)
        chords = []
        current_measure = 0

        for measure in measures:
            current_measure += 1

            # Skip if we're targeting a specific measure
            if measure_num is not None and current_measure != measure_num:
                continue

            # Find all Chord elements in this measure
            for chord in measure.iter('Chord'):
                chords.append(chord)
                if max_count and len(chords) >= max_count:
                    break

            if max_count and len(chords) >= max_count:
                break

        print(f"Found {len(chords)} chords to add staccato to")

        # Add staccato articulation to each chord
        added_count = 0
        for chord in chords:
            # Create a new Articulation element
            articulation = ET.SubElement(chord, 'Articulation')

            # Create the staccato element
            staccato = ET.SubElement(articulation, 'Staccato')
            staccato.set('subtype', 'articulation')  # Default staccato type

            added_count += 1

        print(f"Added staccato to {added_count} notes")

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

        print(f"Successfully added staccato articulations in {output_mscz}")


def main():
    parser = argparse.ArgumentParser(
        description='Add staccato articulations to notes in a MuseScore score'
    )
    parser.add_argument('input_mscz', help='Input .mscz file')
    parser.add_argument('output_mscz', help='Output .mscz file')
    parser.add_argument('--measure', type=int, help='Only add staccato to notes in this measure (1-indexed)')
    parser.add_argument('--count', type=int, help='Maximum number of notes to add staccato to')

    args = parser.parse_args()

    if not os.path.exists(args.input_mscz):
        print(f"Error: Input file not found: {args.input_mscz}")
        sys.exit(1)

    try:
        add_staccato(args.input_mscz, args.output_mscz, args.measure, args.count)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
