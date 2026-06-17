from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WrapperSpec:
    name: str
    target: str
    base_args: tuple[str, ...] = ()


WRAPPER_SPECS = (
    WrapperSpec(
        "chrome",
        "/usr/bin/google-chrome",
        ("--no-sandbox", "--disable-gpu", "--password-store=basic"),
    ),
    WrapperSpec(
        "google-chrome",
        "/usr/bin/google-chrome",
        ("--no-sandbox", "--disable-gpu", "--password-store=basic"),
    ),
    WrapperSpec(
        "brave",
        "/usr/bin/brave-browser-stable",
        ("--no-sandbox", "--disable-gpu", "--password-store=basic"),
    ),
    WrapperSpec(
        "brave-browser",
        "/usr/bin/brave-browser-stable",
        ("--no-sandbox", "--disable-gpu", "--password-store=basic"),
    ),
    WrapperSpec("opera", "/usr/bin/opera", ("--no-sandbox", "--disable-gpu")),
    WrapperSpec("firefox", "/opt/firefox-esr/firefox", ("--no-remote",)),
    WrapperSpec("firefox-esr", "/opt/firefox-esr/firefox", ("--no-remote",)),
    WrapperSpec("vscode", "/usr/bin/code", ("--no-sandbox", "--password-store=basic")),
    WrapperSpec("code", "/usr/bin/code", ("--no-sandbox", "--password-store=basic")),
    WrapperSpec(
        "gimp",
        "/usr/bin/gimp",
        ('-b', '(plug-in-script-fu-server RUN-NONINTERACTIVE "127.0.0.1" 10008 "")'),
    ),
    WrapperSpec(
        "drawio",
        "/usr/bin/drawio",
        ("--no-sandbox", "--disable-gpu", "--password-store=basic"),
    ),
    WrapperSpec(
        "github_desktop",
        "/usr/bin/github-desktop",
        ("--no-sandbox", "--password-store=basic"),
    ),
    WrapperSpec(
        "github-desktop",
        "/usr/bin/github-desktop",
        ("--no-sandbox", "--password-store=basic"),
    ),
    WrapperSpec(
        "obsidian",
        "/opt/Obsidian/obsidian",
        ("--no-sandbox", "--password-store=basic"),
    ),
    WrapperSpec("sublime", "subl"),
    WrapperSpec("musescore3", "mscore3"),
    WrapperSpec("libreoffice_calc", "/usr/bin/soffice", ("--calc",)),
    WrapperSpec("libreoffice_writer", "/usr/bin/soffice", ("--writer",)),
    WrapperSpec("libreoffice_impress", "/usr/bin/soffice", ("--impress",)),
    WrapperSpec("libreoffice_draw", "/usr/bin/soffice", ("--draw",)),
)


def render_wrapper_script(spec: WrapperSpec) -> str:
    command = " ".join(shlex.quote(part) for part in (spec.target, *spec.base_args))
    return f"""#!/usr/bin/env bash
exec {command} "$@"
"""


def build_wrapper_install_commands(target_dir: str = "/usr/local/bin") -> list[str]:
    commands = []
    targets = []
    for spec in WRAPPER_SPECS:
        target_path = f"{target_dir}/{spec.name}"
        targets.append(shlex.quote(target_path))
        commands.append(
            f"cat > {shlex.quote(target_path)} <<'EOF'\n{render_wrapper_script(spec)}EOF"
        )
    commands.append(f"chmod +x {' '.join(targets)}")
    return commands
