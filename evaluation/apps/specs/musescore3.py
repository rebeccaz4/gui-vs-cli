from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("mscore", "musescore"),
    "name_tokens": (".mscz", ".mscx", "musescore"),
    "exact_name_penalty": ("musescore", "musescore 3"),
}


def build_musescore3_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("mscore3", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("musescore3"))

    return AppSpec(
        app_id="musescore3",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="mscore3",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "mscore3"),
        save_shortcut="ctrl+s",
        save_window_name="MuseScore",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
