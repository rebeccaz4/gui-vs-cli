from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect


def _prepare_darktable_profile(ctx: AppContext) -> None:
    ctx.sandbox.commands.run("mkdir -p /home/user/.config/darktable", timeout=5)
    ctx.sandbox.files.write(
        "/home/user/.config/darktable/darktablerc",
        f"ui_last/window_w={ctx.display_width}\n"
        f"ui_last/window_h={ctx.display_height}\n"
        "ui_last/window_x=0\n"
        "ui_last/window_y=0\n",
    )


def build_darktable_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        target = ctx.common_parent() if len(ctx.task_files) > 1 else ctx.first_task_path()
        command = build_command("darktable", target)
        return with_log_redirect(command, ctx.log_path("darktable"))

    return AppSpec(
        app_id="darktable",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="darktable",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "darktable"),
        prepare_profile_hooks=(_prepare_darktable_profile,),
    )
