from __future__ import annotations

import re
import shlex
import time

from .utils import list_windows, run_display_script

def _get_app_spec(app_name: str | None):
    if not app_name:
        return None
    from .registry import get_app_spec

    try:
        return get_app_spec(app_name)
    except ValueError:
        return None


def _get_save_window_hints(app_name: str | None) -> dict[str, tuple[str, ...]]:
    app_spec = _get_app_spec(app_name)
    if app_spec is None:
        return {}
    return app_spec.save_window_hints


def app_window_patterns(app_name: str | None) -> list[str]:
    if not app_name:
        return []
    app_spec = _get_app_spec(app_name)
    hints = _get_save_window_hints(app_name)
    patterns = {
        app_name,
        app_name.replace("_", "-"),
        app_name.replace("_", " "),
        *(hints.get("class_tokens", ())),
        *(hints.get("name_tokens", ())),
    }
    if app_spec and app_spec.save_window_name:
        patterns.add(app_spec.save_window_name)
    return [re.escape(pattern) for pattern in sorted(patterns) if pattern]


def pick_save_window(
    app_name: str,
    windows: list[dict[str, str]],
    save_window_hints: dict[str, tuple[str, ...]] | None = None,
):
    hints = save_window_hints or _get_save_window_hints(app_name)
    class_tokens = [token.lower() for token in hints.get("class_tokens", (app_name,))]
    name_tokens = [token.lower() for token in hints.get("name_tokens", (app_name,))]
    exact_name_penalty = {token.lower() for token in hints.get("exact_name_penalty", ())}

    best = None
    best_score = None
    for window in windows:
        name_lc = window["name"].lower()
        class_lc = window["class"].lower()
        score = 0

        for token in class_tokens:
            if token in class_lc:
                score += 5
        for token in name_tokens:
            if token in name_lc:
                score += 3

        if name_lc in exact_name_penalty:
            score -= 4

        if score <= 0:
            continue

        if best is None or score > best_score:
            best = window
            best_score = score

    return best


def _extract_status_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("__SAVE_STATUS__"):
            return line
    return stdout.strip()


def send_app_save_shortcut(
    sandbox,
    app_name: str,
    save_shortcut: str = "ctrl+s",
    save_window_hints: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, str | bool]:
    window = pick_save_window(
        app_name,
        list_windows(sandbox),
        save_window_hints=save_window_hints,
    )
    if not window:
        return {"ok": False, "message": f"__SAVE_STATUS__ no-window {app_name}", "stderr": ""}

    result = run_display_script(
        sandbox,
        (
            f'WID={shlex.quote(window["wid"])}; '
            'NAME=$(xdotool getwindowname "$WID" 2>/dev/null || true); '
            'xdotool windowactivate "$WID" 2>/dev/null || true; '
            'sleep 0.4; '
            'xdotool windowfocus "$WID" 2>/dev/null || true; '
            'sleep 0.8; '
            f'xdotool key --delay 120 --clearmodifiers {shlex.quote(save_shortcut)} 2>/dev/null || true; '
            'ACTIVE=$(xdotool getactivewindow 2>/dev/null || true); '
            'echo "__SAVE_STATUS__ sent wid=$WID active=$ACTIVE name=$NAME"; '
        ),
        timeout=15,
    )
    status_line = _extract_status_line(result.stdout)
    return {
        "ok": " sent " in f" {status_line} ",
        "message": status_line,
        "stderr": result.stderr.strip(),
    }


def send_named_window_shortcut(
    sandbox,
    window_name: str,
    shortcut: str,
) -> dict[str, str | bool]:
    result = run_display_script(
        sandbox,
        (
            f'WNAME={shlex.quote(window_name)}; '
            'WID=$(xdotool search --name "$WNAME" 2>/dev/null | head -n1 || true); '
            'if [ -z "$WID" ]; then '
            '  echo "__SAVE_STATUS__ no-window"; '
            '  exit 0; '
            "fi; "
            'xdotool windowactivate "$WID" >/dev/null 2>&1 || true; '
            'sleep 0.5; '
            'xdotool windowfocus "$WID" >/dev/null 2>&1 || true; '
            'sleep 0.8; '
            f'xdotool key --delay 120 --clearmodifiers {shlex.quote(shortcut)} >/dev/null 2>&1 || true; '
            'echo "__SAVE_STATUS__ sent wid=$WID name=$WNAME"; '
        ),
        timeout=15,
    )
    status_line = _extract_status_line(result.stdout)
    return {
        "ok": " sent " in f" {status_line} ",
        "message": status_line,
        "stderr": result.stderr.strip(),
    }


def auto_save_app(
    sandbox,
    app_name: str,
    save_shortcut: str,
    save_window_name: str | None = None,
) -> dict[str, str | bool]:
    save_window_hints = _get_save_window_hints(app_name)
    if save_window_hints:
        result = send_app_save_shortcut(
            sandbox,
            app_name,
            save_shortcut=save_shortcut,
            save_window_hints=save_window_hints,
        )
    else:
        result = send_named_window_shortcut(
            sandbox,
            save_window_name or app_name,
            save_shortcut,
        )
    time.sleep(3 if result["ok"] else 1)
    return result
