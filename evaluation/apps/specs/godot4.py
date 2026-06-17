from __future__ import annotations

from pathlib import Path

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("godot",),
    "name_tokens": ("project.godot", "godot", ".tscn"),
    "exact_name_penalty": ("godot project manager", "godot"),
}


def build_godot4_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        project_file = ctx.find_task_path(
            lambda file_entry: file_entry.get("sandbox_path", "").endswith("project.godot")
        )
        project_dir = str(Path(project_file).parent) if project_file else None
        if project_dir:
            command = build_command("godot4", "--editor", "--path", project_dir)
        else:
            command = build_command("godot4")
        return with_log_redirect(command, ctx.log_path("godot4"))

    return AppSpec(
        app_id="godot4",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="godot4",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "godot4"),
        save_shortcut="ctrl+s",
        save_window_name="Godot",
        save_window_hints=SAVE_WINDOW_HINTS,
    )
