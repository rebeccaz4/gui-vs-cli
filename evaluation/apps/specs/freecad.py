from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("freecad",),
    "name_tokens": (".fcstd", "freecad"),
    "exact_name_penalty": ("freecad",),
}


def build_freecad_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("freecad", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("freecad"))

    return AppSpec(
        app_id="freecad",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="freecad",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "freecad"),
        save_shortcut="ctrl+s",
        save_window_name="FreeCAD",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
