from __future__ import annotations

from pathlib import Path

from ..base import AppContext, AppSpec
from ..utils import build_launcher_command, check_process_ready, with_log_redirect


def build_github_desktop_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        repo_head = ctx.find_task_path(
            lambda file_entry: str(file_entry.get("sandbox_path", "")).endswith("/.git/HEAD")
        )
        repo_dir = str(Path(repo_head).parent.parent) if repo_head else None
        command = build_launcher_command("/usr/local/bin/github-desktop", repo_dir)
        return with_log_redirect(command, ctx.log_path("github_desktop"))

    return AppSpec(
        app_id="github_desktop",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="github-desktop",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "github-desktop"),
    )
