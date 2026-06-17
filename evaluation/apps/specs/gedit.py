from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, with_log_redirect


def build_gedit_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("gedit", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("gedit"))

    return AppSpec(
        app_id="gedit",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="gedit",
        build_launch_command=build_launch_command,
    )
