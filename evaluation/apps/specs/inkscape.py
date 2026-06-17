from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("inkscape",),
    "name_tokens": (" - inkscape", ".svg", "inkscape"),
    "exact_name_penalty": ("org.inkscape.inkscape",),
}


def build_inkscape_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("inkscape", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("inkscape"))

    return AppSpec(
        app_id="inkscape",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="inkscape",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "inkscape"),
        save_shortcut="ctrl+s",
        save_window_name="Inkscape",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
