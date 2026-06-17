from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_lo_ready, with_log_redirect


def build_libreoffice_draw_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command(
            "soffice",
            "--draw",
            "--accept=socket,host=localhost,port=2002;urp;",
            "--norestore",
            "--nologo",
            ctx.first_task_path(),
        )
        return with_log_redirect(command, ctx.log_path("libreoffice_draw"))

    return AppSpec(
        app_id="libreoffice_draw",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="libreoffice_draw",
        build_launch_command=build_launch_command,
        ready_check=check_lo_ready,
    )
