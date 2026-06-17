from __future__ import annotations

from pathlib import Path

from ..base import AppContext, AppSpec
from ..utils import build_launcher_command, check_cdp_ready, local_file_url, with_log_redirect

_CDP_BROWSER_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-extensions",
    "--disable-component-update",
    "--disable-hang-monitor",
    "--disable-breakpad",
    "--disable-domain-reliability",
    "--metrics-recording-only",
    "--safebrowsing-disable-auto-update",
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    "--window-size=1280,720",
    "--disable-features=VizDisplayCompositor",
    "--disable-infobars",
)


def _browser_start_target(ctx: AppContext) -> str:
    path = ctx.first_task_path(
        predicate=lambda file_entry: Path(file_entry.get("sandbox_path", "")).suffix.lower()
        in {".html", ".htm", ".json", ".svg", ".txt"}
    )
    if path:
        return local_file_url(path)
    return "about:blank"


def build_brave_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_launcher_command(
            "/usr/local/bin/brave-browser",
            *_CDP_BROWSER_FLAGS,
            "--user-data-dir=/tmp/brave-test-profile",
            _browser_start_target(ctx),
        )
        return with_log_redirect(command, ctx.log_path("brave"))

    return AppSpec(
        app_id="brave",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="brave-browser",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_cdp_ready(sandbox, "Brave"),
    )
