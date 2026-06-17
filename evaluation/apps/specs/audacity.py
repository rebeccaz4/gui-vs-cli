from __future__ import annotations

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

SAVE_WINDOW_HINTS = {
    "class_tokens": ("audacity",),
    "name_tokens": (".aup", ".wav", ".mp3", "audacity"),
    "exact_name_penalty": ("audacity",),
}


def _prepare_audacity_profile(ctx: AppContext) -> None:
    ctx.sandbox.commands.run("mkdir -p /home/user/.audacity-data", timeout=5)
    ctx.sandbox.files.write(
        "/home/user/.audacity-data/audacity.cfg",
        "[Audacity]\nVersion=2.4.2\n"
        "[GUI]\nShowSplashScreen=0\n"
        "[Warnings]\n"
        "FirstProjectSave=0\n"
        "SaveCompressed=0\n"
        "SaveAsCompressed=0\n"
        "SaveWhenEmpty=0\n",
    )


def build_audacity_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("audacity", ctx.first_task_path())
        return with_log_redirect(command, ctx.log_path("audacity"))

    return AppSpec(
        app_id="audacity",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="audacity",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "audacity"),
        save_shortcut="ctrl+s",
        save_window_name="Audacity",
        save_window_hints=SAVE_WINDOW_HINTS,
        prepare_profile_hooks=(_prepare_audacity_profile,),
    )
