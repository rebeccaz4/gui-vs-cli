from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

RENDERDOC_UI_CONFIG = "/home/user/.local/share/qrenderdoc/UI.config"
SAVE_WINDOW_HINTS = {
    "class_tokens": ("gedit",),
    "name_tokens": ("ui.config", "gedit"),
    "exact_name_penalty": ("gedit",),
}


def build_renderdoc_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("gedit", RENDERDOC_UI_CONFIG)
        return with_log_redirect(command, ctx.log_path("renderdoc"))

    return AppSpec(
        app_id="renderdoc",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="renderdoc",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "gedit"),
        save_shortcut="ctrl+s",
        save_window_name="gedit",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
