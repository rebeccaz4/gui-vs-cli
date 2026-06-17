from __future__ import annotations

from pathlib import Path

from ..base import AppContext, AppSpec
from ..utils import build_command, check_port_ready, local_file_url, with_log_redirect


def _browser_start_target(ctx: AppContext) -> str:
    path = ctx.first_task_path(
        predicate=lambda file_entry: Path(file_entry.get("sandbox_path", "")).suffix.lower()
        in {".html", ".htm", ".json", ".svg", ".txt"}
    )
    if path:
        return local_file_url(path)
    return "about:blank"


def build_firefox_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command(
            "firefox-esr",
            "--marionette",
            _browser_start_target(ctx),
        )
        return with_log_redirect(command, ctx.log_path("firefox"))

    return AppSpec(
        app_id="firefox",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="firefox-esr",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_port_ready(sandbox, 2828, "Firefox Marionette"),
    )
