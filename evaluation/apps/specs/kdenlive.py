from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("kdenlive",),
    "name_tokens": (".kdenlive", " - kdenlive", " — kdenlive", "kdenlive"),
    "exact_name_penalty": ("kdenlive", "incorrect project file — kdenlive"),
}


def build_kdenlive_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("kdenlive", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("kdenlive"))

    return AppSpec(
        app_id="kdenlive",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="kdenlive",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "kdenlive"),
        save_shortcut="ctrl+s",
        save_window_name="Kdenlive",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
