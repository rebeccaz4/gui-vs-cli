from __future__ import annotations

import shlex

from evaluation.runtime.run_config import THUNDERBIRD_PROFILE_FILENAME

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect


def get_thunderbird_profile_entry(task: dict | None):
    if not task:
        return None
    for file_entry in task.get("env", {}).get("files", []):
        if file_entry.get("filename") == THUNDERBIRD_PROFILE_FILENAME:
            return file_entry
    return None


def prepare_thunderbird_profile(ctx: AppContext) -> None:
    if not ctx.task:
        return
    profile_entry = get_thunderbird_profile_entry(ctx.task)
    if not profile_entry:
        raise FileNotFoundError(
            f"Thunderbird task {ctx.task['id']} is missing env file {THUNDERBIRD_PROFILE_FILENAME}"
        )
    profile_remote_path = profile_entry["sandbox_path"]
    ctx.sandbox.commands.run("pkill -x thunderbird || true", timeout=10)
    ctx.sandbox.commands.run(f"test -s {shlex.quote(profile_remote_path)}", timeout=5)
    ctx.sandbox.commands.run(
        f"tar -xz --recursive-unlink -f {shlex.quote(profile_remote_path)} -C /home/user/",
        timeout=30,
    )
    ctx.sandbox.commands.run(
        "chown -R user:user /home/user/.thunderbird 2>/dev/null || true",
        timeout=10,
    )


def build_thunderbird_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("thunderbird")
        return with_log_redirect(command, ctx.log_path("thunderbird"))

    return AppSpec(
        app_id="thunderbird",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="thunderbird",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "thunderbird"),
        prepare_task_hooks=(prepare_thunderbird_profile,),
    )
