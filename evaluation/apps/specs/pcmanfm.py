from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, with_log_redirect


def build_pcmanfm_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        target = ctx.common_parent() or "/home/user/Documents"
        command = build_command("pcmanfm", target)
        return with_log_redirect(command, ctx.log_path("pcmanfm"))

    return AppSpec(
        app_id="pcmanfm",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="pcmanfm",
        build_launch_command=build_launch_command,
    )
