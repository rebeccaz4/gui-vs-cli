#!/usr/bin/env python3
"""
MuseScore 3 CLI: Set Key Signature

This script modifies the key signature in a MuseScore .mscz file.
.mscz files are ZIP archives containing a .mscx file (XML format).

Usage:
    python set_key_signature.py <input.mscz> <output.mscz> <accidentals>

Example:
    python set_key_signature.py study_eb.mscz study_eb.mscz -3

Notes:
    - accidentals: Number of sharps (positive) or flats (negative)
    - E-flat major / C minor = -3 (three flats)
    - C major / A minor = 0 (no sharps or flats)
    - G major / E minor = 1 (one sharp)
    - F major / D minor = -1 (one flat)
"""

import sys
import zipfile
import tempfile
import os
from xml.etree import ElementTree as ET


def set_key_signature(input_mscz, output_mscz, accidentals):
    """
    Set the first key signature in a MuseScore score.

    Args:
        input_mscz: Path to input .mscz file
        output_mscz: Path to output .mscz file (can be same as input)
        accidentals: Number of sharps (positive) or flats (negative)
    """
    print(f"Setting key signature to {accidentals} accidentals...")

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

        # Find the first KeySig element
        # MuseScore XML structure: museScore > Score > Staff > Measure > voice > KeySig
        keysig_found = False
        for keysig in root.iter('KeySig'):
            # Modify the first key signature found
            accidental = keysig.find('accidental')
            if accidental is not None:
                accidental.text = str(accidentals)
                keysig_found = True
                print(f"Modified key signature to {accidentals} accidentals")
                break

        if not keysig_found:
            raise ValueError("No KeySig element found in the score")

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

        print(f"Successfully updated key signature in {output_mscz}")


def main():
    if len(sys.argv) != 4:
        print("Usage: python set_key_signature.py <input.mscz> <output.mscz> <accidentals>")
        print("Example: python set_key_signature.py study_eb.mscz study_eb.mscz -3")
        print("")
        print("Common key signatures:")
        print("  -3  = E-flat major / C minor (3 flats)")
        print("  -2  = B-flat major / G minor (2 flats)")
        print("  -1  = F major / D minor (1 flat)")
        print("   0  = C major / A minor (no sharps/flats)")
        print("   1  = G major / E minor (1 sharp)")
        print("   2  = D major / B minor (2 sharps)")
        print("   3  = A major / F-sharp minor (3 sharps)")
        sys.exit(1)

    input_mscz = sys.argv[1]
    output_mscz = sys.argv[2]
    accidentals_str = sys.argv[3]

    # Validate inputs
    try:
        accidentals = int(accidentals_str)
    except ValueError:
        print("Error: accidentals must be an integer")
        sys.exit(1)

    if not os.path.exists(input_mscz):
        print(f"Error: Input file not found: {input_mscz}")
        sys.exit(1)

    try:
        set_key_signature(input_mscz, output_mscz, accidentals)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
