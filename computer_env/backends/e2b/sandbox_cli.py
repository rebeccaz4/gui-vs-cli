"""
Unified script to open sandbox environments.

Usage:
    python -m computer_env.backends.e2b.sandbox_cli <id>
    python -m computer_env.backends.e2b.sandbox_cli <id> --view
    python -m computer_env.backends.e2b.sandbox_cli --list

Examples:
    python -m computer_env.backends.e2b.sandbox_cli slack
    python -m computer_env.backends.e2b.sandbox_cli slack --view
    python -m computer_env.backends.e2b.sandbox_cli slack --res 1920x1080
"""

import argparse
import json
import os
import sys
from pathlib import Path

from e2b_desktop import Sandbox
from dotenv import load_dotenv

load_dotenv()

SANDBOXES_ENV_VAR = "GUI_SYNTH_E2B_SANDBOXES_FILE"


def _default_sandboxes_file() -> Path:
    return Path.home() / ".config" / "gui-synth-env" / "e2b" / "sandboxes.json"


def _resolve_sandboxes_file() -> Path:
    override = os.getenv(SANDBOXES_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return _default_sandboxes_file()


SANDBOXES_FILE = _resolve_sandboxes_file()


def load_sandboxes() -> dict:
    if not SANDBOXES_FILE.exists():
        return {}
    with SANDBOXES_FILE.open() as f:
        return json.load(f)


def save_sandboxes(data: dict):
    SANDBOXES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SANDBOXES_FILE.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def list_sandboxes(data: dict):
    print(f"{'ID':<15} {'Base Template':<25} {'Snapshot'}")
    print("-" * 70)
    for name, info in data.items():
        snap = info.get("snapshot") or "(none)"
        print(f"{name:<15} {info['base_template']:<25} {snap}")


def main():
    parser = argparse.ArgumentParser(description="Open a sandbox environment")
    parser.add_argument("id", nargs="?", help="Sandbox ID from the sandbox registry")
    parser.add_argument("--view", action="store_true", help="Open without saving changes")
    parser.add_argument("--list", action="store_true", help="List available environments")
    parser.add_argument("--reset", action="store_true", help="Ignore snapshot, boot from base template")
    parser.add_argument("--res", type=str, default="1920x1080", help="Screen resolution, e.g. 1920x1080 (default: 1920x1080)")
    args = parser.parse_args()

    data = load_sandboxes()

    if args.list:
        list_sandboxes(data)
        return

    if not args.id:
        parser.print_help()
        print(f"\nSandbox registry: {SANDBOXES_FILE}")
        print(f"Available IDs: {', '.join(data.keys())}")
        sys.exit(1)

    if args.id not in data:
        print(f"Unknown ID '{args.id}'. Available: {', '.join(data.keys())}")
        sys.exit(1)

    entry = data[args.id]
    base = entry["base_template"]
    snapshot = entry.get("snapshot")

    if args.reset or not snapshot:
        template = base
        print(f"Booting from base template: {base}")
    else:
        template = snapshot
        print(f"Resuming from snapshot: {snapshot}")

    mode = "view-only" if args.view else "save-on-exit"
    print(f"Mode: {mode}")

    width, height = (int(x) for x in args.res.split("x"))
    sbx = Sandbox.create(template=template, timeout=3600, resolution=(width, height))
    print(f"Sandbox started: {sbx.sandbox_id}")

    try:
        sbx.stream.start()
    except RuntimeError:
        pass

    desktop_url = sbx.stream.get_url(resize="scale")
    print(f"\nDesktop URL: {desktop_url}")
    print("Open the URL above in your browser to interact with the desktop.")
    print(f"\nPress Ctrl+C when done. {'Changes will be saved.' if not args.view else 'Changes will NOT be saved.'}")

    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        if not args.view:
            print("\nSnapshotting current state...")
            info = sbx.create_snapshot()
            entry["snapshot"] = info.snapshot_id
            save_sandboxes(data)
            print(f"Snapshot saved: {info.snapshot_id}")
        else:
            print()

        print("Killing sandbox...")
        sbx.kill()
        print("Done.")


if __name__ == "__main__":
    main()
