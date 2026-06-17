from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_launcher_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("drawio",),
    "name_tokens": ("drawio", ".drawio", "diagrams.net"),
    "exact_name_penalty": (),
}


def build_drawio_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_launcher_command("/usr/local/bin/drawio", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("drawio"))

    return AppSpec(
        app_id="drawio",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="drawio",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "drawio"),
        save_shortcut="ctrl+s",
        save_window_name="draw.io",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
