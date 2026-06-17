"""Deterministic RenderDoc verifier artifact writers."""

from __future__ import annotations

import json
import stat
import struct
from pathlib import Path
from typing import Any


RDC_MAGIC_BYTES = b"RDOC"
RDC_SERIALISE_VERSION = 0x00000102
RDC_FIXED_HEADER_LEN = 32


def create_rdc(
    output: str,
    serialise_version: int = RDC_SERIALISE_VERSION,
    header_length: int = RDC_FIXED_HEADER_LEN,
    prog_version: str = "1.36",
    payload_size: int = 64,
) -> dict[str, Any]:
    """Create a minimal verifier-readable .rdc file."""
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    prog = prog_version.encode("latin-1", "replace")[:16].ljust(16, b"\x00")
    header = RDC_MAGIC_BYTES + b"\x00\x00\x00\x00" + struct.pack(
        "<II", serialise_version, header_length
    ) + prog
    payload = b"\x00" * max(0, payload_size)
    with open(path, "wb") as f:
        f.write(header)
        f.write(payload)
    return {
        "path": str(path),
        "serialise_version": serialise_version,
        "header_length": header_length,
        "prog_version": prog_version,
        "size": path.stat().st_size,
    }


def _wrapper_source(version: str, api: str, chunks: int, sections: list[str]) -> str:
    return f'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

VERSION = {version!r}
API = {api!r}
CHUNKS = {int(chunks)!r}
SECTIONS = {sections!r}

PNG_BYTES = b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x02\\x00\\x00\\x00\\x90wS\\xde\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82"

def _arg_after(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

def main():
    args = sys.argv[1:]
    if not args:
        print("RenderDoc command line tool")
        return 0
    cmd = args[0]
    if cmd == "version":
        print(f"RenderDoc v{{VERSION}} (git sha abcdef1)")
        print(f"Supported APIs: {{API}} Vulkan OpenGL D3D11")
        return 0
    if cmd == "extract" and "--list-sections" in args:
        for i, name in enumerate(SECTIONS):
            print(f"Section {{i}}: {{name}} (type={{i}}, version=1)")
        return 0
    if cmd == "thumb":
        out = _arg_after("-o")
        if not out:
            print("missing -o", file=sys.stderr)
            return 2
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(PNG_BYTES)
        return 0
    if cmd == "convert":
        out = _arg_after("-o")
        if not out:
            print("missing -o", file=sys.stderr)
            return 2
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        chunk_xml = "\\n".join(f"<chunk id='{{i}}' />" for i in range(CHUNKS))
        xml = f"<capture api='{{API}}'>\\n{{chunk_xml}}\\n<event id='1' />\\n<resource id='1' />\\n<action id='1' />\\n</capture>\\n"
        Path(out).write_text(xml, encoding="utf-8")
        return 0
    print("unknown renderdoccmd args: " + " ".join(args), file=sys.stderr)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''


def scaffold_rdcmd(
    output: str,
    version: str = "1.36",
    api: str = "Vulkan",
    chunks: int = 3,
    sections: list[str] | None = None,
    plugins: list[str] | None = None,
    layer_path: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic renderdoccmd-compatible wrapper and install metadata."""
    out = Path(output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    sections = sections or ["InitialContents", "FrameCapture", "Resolve"]
    plugins = plugins or ["amd", "android", "spirv"]
    out.write_text(_wrapper_source(version, api, chunks, sections), encoding="utf-8")
    mode = out.stat().st_mode
    out.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    plugin_dir = out.parent / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    for plugin in plugins:
        (plugin_dir / plugin).mkdir(parents=True, exist_ok=True)

    if layer_path is None:
        layer = Path.home() / ".local/share/vulkan/implicit_layer.d/renderdoc_capture.json"
    else:
        layer = Path(layer_path).expanduser()
    layer.parent.mkdir(parents=True, exist_ok=True)
    layer.write_text(
        json.dumps(
            {
                "file_format_version": "1.0.0",
                "layer": {
                    "name": "VK_LAYER_RENDERDOC_Capture",
                    "type": "GLOBAL",
                    "library_path": str(out),
                    "api_version": "1.3.0",
                    "implementation_version": 1,
                    "description": "RenderDoc capture layer",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "path": str(out),
        "version": version,
        "api": api,
        "chunks": chunks,
        "sections": sections,
        "plugins_dir": str(plugin_dir),
        "plugins": plugins,
        "layer_path": str(layer),
    }
