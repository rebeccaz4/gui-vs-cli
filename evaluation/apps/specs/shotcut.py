from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("shotcut",),
    "name_tokens": (".mlt", " - shotcut", " — shotcut", "shotcut"),
    "exact_name_penalty": ("shotcut",),
}


def build_shotcut_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("shotcut", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("shotcut"))

    return AppSpec(
        app_id="shotcut",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="shotcut",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "shotcut"),
        save_shortcut="ctrl+s",
        save_window_name="Shotcut",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
