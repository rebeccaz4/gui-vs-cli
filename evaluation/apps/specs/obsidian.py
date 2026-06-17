from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_launcher_command, with_log_redirect


def build_obsidian_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        vault_root = None
        for path in ctx.list_task_paths():
            marker = "/.obsidian/"
            if marker in path:
                vault_root = path.split(marker, 1)[0]
                break
        if not vault_root:
            vault_root = ctx.common_parent(
                predicate=lambda file_entry: str(file_entry.get("sandbox_path", "")).endswith(".md")
            )
        command = build_launcher_command("/usr/local/bin/obsidian", vault_root)
        return with_log_redirect(command, ctx.log_path("obsidian"))

    return AppSpec(
        app_id="obsidian",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="obsidian",
        build_launch_command=build_launch_command,
    )
