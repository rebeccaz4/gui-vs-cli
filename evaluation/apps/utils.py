from __future__ import annotations

import re
import shlex
import time
from pathlib import Path

from computer_env.backends.base import CommandExitException
from .base import AppContext
from .launcher_contract import WRAPPER_SPECS

WINDOW_READY_TIMEOUT_SECONDS = 20.0
WINDOW_READY_POLL_SECONDS = 0.5
WINDOW_READY_STABLE_SAMPLES = 3
WINDOW_MIN_VISIBLE_WIDTH = 200
WINDOW_MIN_VISIBLE_HEIGHT = 120
WINDOW_MIN_VISIBLE_SIZE_OVERRIDES = {
    # darktable first-run performance prompt is a real modal app window, but its
    # height is ~111px in both Docker and E2B, so the default 120px threshold
    # incorrectly rejects it and prevents the agent from handling the dialog.
    "darktable": (200, 100),
}
WINDOW_TOKEN_ALIASES = {
    "audacity": ("audacity",),
    "blender": ("blender",),
    "brave": ("brave", "brave-browser"),
    "chrome": ("chrome", "google-chrome"),
    "cloudcompare": ("cloudcompare", "cloud compare"),
    "drawio": ("draw.io", "diagrams.net", "drawio"),
    "freecad": ("freecad",),
    "github_desktop": ("github desktop", "github-desktop"),
    "godot4": ("godot", "godot4"),
    "libreoffice_calc": ("libreoffice calc", "soffice"),
    "libreoffice_draw": ("libreoffice draw", "soffice"),
    "libreoffice_impress": ("libreoffice impress", "soffice"),
    "libreoffice_writer": ("libreoffice writer", "soffice"),
    "musescore3": ("musescore", "mscore3"),
    "obs": ("obs", "obs studio"),
    "obsidian": ("obsidian",),
    "pcmanfm": ("pcmanfm",),
    "renderdoc": ("renderdoc", "qrenderdoc"),
    "shotcut": ("shotcut",),
    "thunderbird": ("thunderbird",),
    "vlc": ("vlc",),
    "vscode": ("visual studio code", "vscode", "code"),
    "zoom": ("zoom",),
    "zotero": ("zotero",),
}

_WRAPPER_SPEC_BY_NAME = {spec.name: spec for spec in WRAPPER_SPECS}


def run_display_script(sandbox, script: str, timeout: int = 15):
    command = f"bash -lc {shlex.quote('export DISPLAY=:0; ' + script)}"
    return sandbox.commands.run(command, timeout=timeout)


def list_windows(sandbox) -> list[dict[str, str]]:
    result = run_display_script(
        sandbox,
        (
            "xdotool search --onlyvisible --class . 2>/dev/null | while read -r wid; do "
            '  [ -n "$wid" ] || continue; '
            '  name=$(xdotool getwindowname "$wid" 2>/dev/null || true); '
            '  class=$(xprop -id "$wid" WM_CLASS 2>/dev/null || true); '
            '  eval "$(xdotool getwindowgeometry --shell "$wid" 2>/dev/null || true)"; '
            '  printf "__WINDOW__\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n" '
            '    "$wid" "${X:-0}" "${Y:-0}" "${WIDTH:-0}" "${HEIGHT:-0}" "$name" "$class"; '
            "done"
        ),
        timeout=10,
    )
    windows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.startswith("__WINDOW__\t"):
            continue
        _, wid, x, y, width, height, name, class_text = line.split("\t", 7)
        windows.append(
            {
                "wid": wid,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "name": name,
                "class": class_text,
            }
        )
    return windows


def describe_windows(sandbox, patterns: list[str] | None = None) -> str:
    compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in patterns or []]
    lines = []
    for window in list_windows(sandbox):
        payload = f"{window['name']}\n{window['class']}"
        if compiled_patterns and not any(pattern.search(payload) for pattern in compiled_patterns):
            continue
        lines.append(
            " ".join(
                [
                    f"WID={window['wid']}",
                    f"XY={window['x']},{window['y']}",
                    f"WH={window['width']}x{window['height']}",
                    f"CLASS={window['class']}",
                    f"NAME={window['name']}",
                ]
            )
        )
    return "\n".join(lines)


def _normalized_window_tokens(app_context: AppContext) -> list[str]:
    app_spec = app_context.app_spec
    tokens: set[str] = set()

    def add(token: str | None) -> None:
        if not token:
            return
        cleaned = token.strip().lower()
        if not cleaned or cleaned in {"desktop", "window"}:
            return
        tokens.add(cleaned)

    add(app_spec.app_id)
    add(app_spec.app_id.replace("_", "-"))
    add(app_spec.app_id.replace("_", " "))
    launcher_name = Path(app_spec.canonical_launcher).name
    add(launcher_name)
    add(launcher_name.replace("_", " "))
    add(launcher_name.replace("_", "-"))
    if app_spec.save_window_name:
        add(app_spec.save_window_name)
    for key in ("class_tokens", "name_tokens"):
        for token in app_spec.save_window_hints.get(key, ()):
            add(token)
    for token in WINDOW_TOKEN_ALIASES.get(app_spec.app_id, ()):
        add(token)
    if app_spec.app_id.startswith("libreoffice_"):
        add("libreoffice")

    return sorted(tokens, key=len, reverse=True)


def _window_payload(window: dict[str, str]) -> str:
    return f"{window.get('name', '')}\n{window.get('class', '')}".lower()


def _window_size_ok(window: dict[str, str], app_id: str | None = None) -> bool:
    try:
        width = int(window.get("width", "0"))
        height = int(window.get("height", "0"))
    except ValueError:
        return False
    min_width, min_height = WINDOW_MIN_VISIBLE_SIZE_OVERRIDES.get(
        app_id or "",
        (WINDOW_MIN_VISIBLE_WIDTH, WINDOW_MIN_VISIBLE_HEIGHT),
    )
    return width >= min_width and height >= min_height


def _matching_windows(
    windows: list[dict[str, str]],
    tokens: list[str],
    app_id: str | None = None,
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for window in windows:
        if not _window_size_ok(window, app_id=app_id):
            continue
        payload = _window_payload(window)
        if tokens and not any(token in payload for token in tokens):
            continue
        matches.append(window)
    return matches


def wait_for_app_window_ready(app_context: AppContext) -> bool:
    tokens = _normalized_window_tokens(app_context)
    deadline = time.time() + WINDOW_READY_TIMEOUT_SECONDS
    stable_fingerprint: tuple[tuple[str, str, str, str, str, str, str], ...] | None = None
    stable_samples = 0

    while time.time() < deadline:
        windows = _matching_windows(
            list_windows(app_context.sandbox),
            tokens,
            app_id=app_context.app_spec.app_id,
        )
        if windows:
            fingerprint = tuple(
                sorted(
                    (
                        window["wid"],
                        window["x"],
                        window["y"],
                        window["width"],
                        window["height"],
                        window["name"],
                        window["class"],
                    )
                    for window in windows
                )
            )
            if fingerprint == stable_fingerprint:
                stable_samples += 1
            else:
                stable_fingerprint = fingerprint
                stable_samples = 1
            if stable_samples >= WINDOW_READY_STABLE_SAMPLES:
                time.sleep(WINDOW_READY_POLL_SECONDS)
                return True
        else:
            stable_fingerprint = None
            stable_samples = 0
        time.sleep(WINDOW_READY_POLL_SECONDS)

    return False


def build_command(binary: str, *args: object) -> str:
    parts = [binary]
    for arg in args:
        if arg is None:
            continue
        text = str(arg)
        if not text:
            continue
        parts.append(text)
    return " ".join(shlex.quote(part) for part in parts)


def build_launcher_command(binary: str, *args: object) -> str:
    wrapper_name = Path(binary).name
    wrapper_spec = _WRAPPER_SPEC_BY_NAME.get(wrapper_name)
    if wrapper_spec is None or not binary.startswith("/usr/local/bin/"):
        return build_command(binary, *args)

    wrapped_command = build_command(binary, *args)
    fallback_command = build_command(wrapper_spec.target, *wrapper_spec.base_args, *args)
    script = (
        f"if [ -x {shlex.quote(binary)} ]; then "
        f"exec {wrapped_command}; "
        f"else "
        f"exec {fallback_command}; "
        f"fi"
    )
    return f"bash -lc {shlex.quote(script)}"


def with_log_redirect(command: str, log_path: str) -> str:
    return f"{command} > {shlex.quote(log_path)} 2>&1"


def local_file_url(path: str) -> str:
    return f"file://{Path(path).as_posix()}"


def task_has_env_file(task: dict | None, remote_path: str) -> bool:
    if not task:
        return False
    for file_entry in task.get("env", {}).get("files", []):
        if file_entry.get("sandbox_path") == remote_path:
            return True
    return False


def check_cdp_ready(sandbox, _label: str = "Browser") -> bool:
    for _ in range(20):
        try:
            result = sandbox.commands.run("curl -s http://127.0.0.1:9222/json", timeout=3)
            if result.stdout.strip().startswith("["):
                return True
        except (CommandExitException, Exception):
            pass
        time.sleep(1)
    return False


def check_port_ready(sandbox, port: int, _label: str = "Service") -> bool:
    for _ in range(20):
        try:
            result = sandbox.commands.run(
                (
                    'python3 -c "'
                    "import socket; s = socket.socket(); s.settimeout(2); "
                    f"s.connect(('localhost', {port})); s.close(); print('OK')\""
                ),
                timeout=5,
            )
            if "OK" in result.stdout:
                return True
        except (CommandExitException, Exception):
            pass
        time.sleep(1)
    return False


def check_process_ready(sandbox, *process_names: str) -> bool:
    if not process_names:
        return True
    for _ in range(15):
        for process_name in process_names:
            try:
                result = sandbox.commands.run(f"pgrep -x {shlex.quote(process_name)}", timeout=3)
                if result.stdout.strip():
                    return True
            except (CommandExitException, Exception):
                pass
        time.sleep(1)
    return False


def check_lo_ready(sandbox) -> bool:
    return check_port_ready(sandbox, 2002, "LibreOffice UNO")
