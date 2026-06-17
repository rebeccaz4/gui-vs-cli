from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_lo_ready, with_log_redirect


def build_libreoffice_writer_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command(
            "soffice",
            "--writer",
            "--accept=socket,host=localhost,port=2002;urp;",
            "--norestore",
            "--nologo",
            ctx.first_task_path(),
        )
        return with_log_redirect(command, ctx.log_path("libreoffice_writer"))

    return AppSpec(
        app_id="libreoffice_writer",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="libreoffice_writer",
        build_launch_command=build_launch_command,
        ready_check=check_lo_ready,
    )
