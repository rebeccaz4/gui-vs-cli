from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("blender",),
    "name_tokens": (".blend", " - blender", " — blender", "blender"),
    "exact_name_penalty": ("blender",),
}


def build_blender_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("blender", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("blender"))

    return AppSpec(
        app_id="blender",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="blender",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "blender"),
        save_shortcut="ctrl+s",
        save_window_name="Blender",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
