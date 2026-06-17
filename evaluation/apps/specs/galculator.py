from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect


def build_galculator_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("galculator")
        return with_log_redirect(command, ctx.log_path("galculator"))

    return AppSpec(
        app_id="galculator",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="galculator",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "galculator"),
    )
