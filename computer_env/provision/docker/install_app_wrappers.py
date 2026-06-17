#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

LAUNCHER_CONTRACT_PATH = Path("/usr/local/share/gui-synth/launcher_contract.py")
TARGET_DIR = Path("/usr/local/bin")


def _load_manifest():
    spec = importlib.util.spec_from_file_location(
        "gui_synth_app_launcher_contract",
        LAUNCHER_CONTRACT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load launcher contract from {LAUNCHER_CONTRACT_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register the module before execution so decorators such as dataclass
    # can resolve the module namespace during import-time processing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    manifest = _load_manifest()
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for wrapper_spec in manifest.WRAPPER_SPECS:
        target_path = TARGET_DIR / wrapper_spec.name
        target_path.write_text(manifest.render_wrapper_script(wrapper_spec))
        target_path.chmod(0o755)


if __name__ == "__main__":
    main()
