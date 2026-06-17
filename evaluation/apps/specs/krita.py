from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("krita",),
    "name_tokens": (".kra", "krita"),
    "exact_name_penalty": (),
}


def build_krita_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("krita", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("krita"))

    return AppSpec(
        app_id="krita",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="krita",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "krita"),
        save_shortcut="ctrl+s",
        save_window_name="Krita",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
