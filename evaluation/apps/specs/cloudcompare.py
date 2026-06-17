from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("cloudcompare",),
    "name_tokens": (".ply", ".obj", ".xyz", ".asc", "cloudcompare"),
    "exact_name_penalty": ("cloudcompare",),
}


def build_cloudcompare_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("CloudCompare", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("cloudcompare"))

    return AppSpec(
        app_id="cloudcompare",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="CloudCompare",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "CloudCompare"),
        save_shortcut="ctrl+s",
        save_window_name="CloudCompare",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
