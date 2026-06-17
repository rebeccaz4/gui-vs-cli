from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_port_ready, with_log_redirect


def build_vlc_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command(
            "vlc",
            "--intf",
            "http",
            "--http-port",
            "8080",
            "--http-password",
            "secret",
            "--no-qt-privacy-ask",
            ctx.first_task_path(),
        )
        return with_log_redirect(command, ctx.log_path("vlc"))

    return AppSpec(
        app_id="vlc",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="vlc",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_port_ready(sandbox, 8080, "VLC HTTP"),
    )
