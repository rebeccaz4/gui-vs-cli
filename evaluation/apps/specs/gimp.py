from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_launcher_command, check_port_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("gimp",),
    "name_tokens": ("gimp", ".xcf", ".png", ".jpg", "gnu image manipulation program"),
    "exact_name_penalty": (),
}


def build_gimp_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_launcher_command("/usr/local/bin/gimp", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("gimp"))

    return AppSpec(
        app_id="gimp",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="gimp",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_port_ready(sandbox, 10008, "GIMP Script-Fu"),
        save_shortcut="ctrl+s",
        save_window_name="GNU Image Manipulation Program",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
