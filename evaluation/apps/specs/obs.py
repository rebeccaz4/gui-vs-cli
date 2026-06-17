from __future__ import annotations

from evaluation.runtime.run_config import OBS_SCENE_COLLECTION_REMOTE

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, task_has_env_file, with_log_redirect


def prepare_obs_launch_config(ctx: AppContext) -> None:
    ctx.sandbox.commands.run(
        "mkdir -p /home/user/.config/obs-studio/basic/profiles/Untitled "
        "/home/user/.config/obs-studio/basic/scenes",
        timeout=5,
    )
    ctx.sandbox.files.write(
        "/home/user/.config/obs-studio/global.ini",
        "[General]\n"
        "Pre19Defaults=false\n"
        "Pre21Defaults=false\n"
        "Pre23Defaults=false\n"
        "Pre24.1Defaults=false\n"
        "FirstRun=false\n\n"
        "[Basic]\n"
        "Profile=Untitled\n"
        "ProfileDir=Untitled\n"
        "SceneCollection=Untitled\n"
        "SceneCollectionFile=Untitled\n\n"
        "[BasicWindow]\n"
        "gridMode=false\n",
    )
    ctx.sandbox.files.write(
        "/home/user/.config/obs-studio/basic/profiles/Untitled/basic.ini",
        "[General]\nName=Untitled\n\n"
        "[Video]\n"
        f"BaseCX={ctx.display_width}\n"
        f"BaseCY={ctx.display_height}\n"
        "OutputCX=1280\n"
        "OutputCY=720\n",
    )
    if task_has_env_file(ctx.task, OBS_SCENE_COLLECTION_REMOTE):
        return
    ctx.sandbox.files.write(
        OBS_SCENE_COLLECTION_REMOTE,
        '{"current_program_scene":"Scene","current_scene":"Scene",'
        '"current_transition":"Fade","groups":[],"modules":{"auto-scene-switcher":'
        '{"active":false,"interval":300,"non_matching_scene":"","switch_if_not_matching":false,'
        '"switches":[]},"output-timer":{"autoStartRecordTimer":false,"autoStartStreamTimer":false,'
        '"pauseRecordTimer":true,"recordTimerHours":0,"recordTimerMinutes":0,"recordTimerSeconds":30,'
        '"streamTimerHours":0,"streamTimerMinutes":0,"streamTimerSeconds":30},"scripts-tool":[]},'
        '"name":"Untitled","preview_locked":false,"quick_transitions":[{"duration":300,'
        '"fade_to_black":false,"hotkeys":[],"id":1,"name":"Cut"},{"duration":300,'
        '"fade_to_black":false,"hotkeys":[],"id":2,"name":"Fade"},{"duration":300,'
        '"fade_to_black":true,"hotkeys":[],"id":3,"name":"Fade"}],"saved_projectors":[],'
        '"scaling_enabled":false,"scaling_level":0,"scaling_off_x":0.0,"scaling_off_y":0.0,'
        '"scene_order":[{"name":"Scene"}],"sources":[{"balance":0.5,"deinterlace_field_order":0,'
        '"deinterlace_mode":0,"enabled":true,"flags":0,"hotkeys":{"OBSBasic.SelectScene":[]},'
        '"id":"scene","mixers":0,"monitoring_type":0,"muted":false,"name":"Scene",'
        '"prev_ver":453115907,"private_settings":{},"push-to-mute":false,"push-to-mute-delay":0,'
        '"push-to-talk":false,"push-to-talk-delay":0,"settings":{"custom_size":false,'
        '"id_counter":0,"items":[]},"sync":0,"versioned_id":"scene","volume":1.0}],'
        '"transition_duration":300,"transitions":[]}',
    )


def _dismiss_obs_wizard(ctx: AppContext) -> None:
    ctx.sandbox.commands.run(
        "for _ in $(seq 1 12); do "
        "  WID=$(xdotool search --name 'Auto-Configuration Wizard' 2>/dev/null | head -n1 || true); "
        '  if [ -n "$WID" ]; then '
        '    xdotool windowactivate "$WID" key --clearmodifiers Escape >/dev/null 2>&1 || true; '
        "    break; "
        "  fi; "
        "  sleep 1; "
        "done",
        timeout=20,
    )


def build_obs_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("obs")
        return with_log_redirect(command, ctx.log_path("obs"))

    return AppSpec(
        app_id="obs",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="obs",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "obs"),
        prepare_profile_hooks=(prepare_obs_launch_config,),
        post_launch_hooks=(_dismiss_obs_wizard,),
    )
