#!/usr/bin/env python3
"""
MuseScore 3 CLI: Change Time Signature

This script modifies the time signature in a MuseScore .mscz file.
.mscz files are ZIP archives containing a .mscx file (XML format).

Usage:
    python change_time_signature.py <input.mscz> <output.mscz> <numerator> <denominator>

Example:
    python change_time_signature.py waltz_sketch.mscz waltz_sketch.mscz 3 4
"""

import sys
import zipfile
import tempfile
import os
import shutil
from xml.etree import ElementTree as ET


def change_time_signature(input_mscz, output_mscz, numerator, denominator):
    """
    Change the first time signature in a MuseScore score.

    Args:
        input_mscz: Path to input .mscz file
        output_mscz: Path to output .mscz file (can be same as input)
        numerator: Time signature numerator (e.g., 3 for 3/4)
        denominator: Time signature denominator (e.g., 4 for 3/4)
    """
    print(f"Changing time signature to {numerator}/{denominator}...")

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

        # Find the first TimeSig element
        # MuseScore XML structure: museScore > Score > Staff > Measure > voice > TimeSig
        timesig_found = False
        for timesig in root.iter('TimeSig'):
            # Modify the first time signature found
            sig_n = timesig.find('sigN')
            sig_d = timesig.find('sigD')

            if sig_n is not None:
                sig_n.text = str(numerator)
            if sig_d is not None:
                sig_d.text = str(denominator)

            timesig_found = True
            print(f"Modified time signature to {numerator}/{denominator}")
            break

        if not timesig_found:
            raise ValueError("No TimeSig element found in the score")

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

        print(f"Successfully updated time signature in {output_mscz}")


def main():
    if len(sys.argv) != 5:
        print("Usage: python change_time_signature.py <input.mscz> <output.mscz> <numerator> <denominator>")
        print("Example: python change_time_signature.py waltz_sketch.mscz waltz_sketch.mscz 3 4")
        sys.exit(1)

    input_mscz = sys.argv[1]
    output_mscz = sys.argv[2]
    numerator = sys.argv[3]
    denominator = sys.argv[4]

    # Validate inputs
    try:
        numerator_int = int(numerator)
        denominator_int = int(denominator)
    except ValueError:
        print("Error: numerator and denominator must be integers")
        sys.exit(1)

    if not os.path.exists(input_mscz):
        print(f"Error: Input file not found: {input_mscz}")
        sys.exit(1)

    try:
        change_time_signature(input_mscz, output_mscz, numerator_int, denominator_int)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
