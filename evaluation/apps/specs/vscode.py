from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_launcher_command, with_log_redirect


def build_vscode_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_launcher_command("/usr/local/bin/code", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("vscode"))

    return AppSpec(
        app_id="vscode",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="code",
        build_launch_command=build_launch_command,
    )
