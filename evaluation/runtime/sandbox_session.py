from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from computer_env import (
    DEFAULT_DOCKER_CPUS,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_MEMORY,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_DOCKER_READY_TIMEOUT,
    DEFAULT_DOCKER_SHM_SIZE,
    DEFAULT_ENV_BACKEND,
    DEFAULT_E2B_TEMPLATE,
    create_env,
)
from computer_env.backends.base import CommandExitException

from evaluation.apps.base import AppContext
from evaluation.apps.registry import get_app_spec
from evaluation.apps.utils import describe_windows, wait_for_app_window_ready

from .run_config import DISPLAY_HEIGHT, DISPLAY_WIDTH, TASK_GEN_DIR


@dataclass(slots=True)
class SandboxSession:
    sandbox: object
    stream_url: str
    app_context: AppContext


def upload_verifier(sandbox, app_name: str) -> None:
    app_spec = get_app_spec(app_name)
    sandbox.commands.run("mkdir -p /home/user/verifiers")
    with open(app_spec.verifier_local) as handle:
        sandbox.files.write(app_spec.verifier_remote, handle.read())


def upload_task_env_files(sandbox, task: dict | None) -> None:
    if not task or "env" not in task or "files" not in task["env"]:
        return

    task_id = task["id"]
    env_dir = TASK_GEN_DIR / "tasks" / task_id / "env"
    create_env_script = env_dir / "create_env.py"
    has_create_script = create_env_script.exists()

    for file_entry in task["env"]["files"]:
        local_path = env_dir / file_entry["filename"]
        remote_path = file_entry["sandbox_path"]
        remote_dir = str(Path(remote_path).parent)
        sandbox.commands.run(f"mkdir -p {remote_dir}", timeout=5)
        if local_path.exists():
            with open(local_path, "rb") as handle:
                sandbox.files.write(remote_path, handle.read())

    if has_create_script:
        missing = any(not (env_dir / file_entry["filename"]).exists() for file_entry in task["env"]["files"])
        if missing:
            with open(create_env_script) as handle:
                sandbox.files.write("/tmp/create_env.py", handle.read())
            try:
                sandbox.commands.run("python3 /tmp/create_env.py", timeout=120)
            except CommandExitException:
                sandbox.commands.run(
                    "pip install python-docx python-pptx openpyxl -q 2>&1",
                    timeout=60,
                )
                try:
                    sandbox.commands.run("python3 /tmp/create_env.py", timeout=120)
                except CommandExitException:
                    pass


def run_task_setup_scripts(sandbox, task: dict | None) -> None:
    if not task:
        return
    for file_entry in task.get("env", {}).get("files", []):
        filename = str(file_entry.get("filename", ""))
        sandbox_path = str(file_entry.get("sandbox_path", ""))
        if not filename.startswith("setup_"):
            continue
        if sandbox_path.endswith(".py"):
            sandbox.commands.run(f"python3 {sandbox_path}", timeout=60)
        elif sandbox_path.endswith(".sh"):
            sandbox.commands.run(f"bash {sandbox_path}", timeout=60)
        else:
            sandbox.commands.run(sandbox_path, timeout=60)


def launch_app(app_context: AppContext) -> None:
    command = app_context.app_spec.build_launch_command(app_context)
    app_context.sandbox.commands.run(command, background=True)
    for hook in app_context.app_spec.post_launch_hooks:
        hook(app_context)


def format_app_log_excerpt(app_context: AppContext, lines: int = 80) -> str:
    log_path = app_context.log_path()
    command = (
        f"if [ -f {shlex.quote(log_path)} ]; then "
        f"tail -n {int(lines)} {shlex.quote(log_path)}; "
        "else "
        "echo '<log file not found>'; "
        "fi"
    )
    try:
        result = app_context.sandbox.commands.run(command, timeout=5)
    except Exception as exc:
        return f"App log ({log_path}) unavailable: {exc}"

    excerpt = (result.stdout or result.stderr or "").strip()
    if not excerpt:
        excerpt = "<log file empty>"
    return f"App log ({log_path}):\n{excerpt}"


def setup_sandbox_session(
    app_name,
    task=None,
    sandbox_timeout=200,
    run_id: str | None = None,
    run_mode: str = "gui",
    env_backend=DEFAULT_ENV_BACKEND,
    docker_image=DEFAULT_DOCKER_IMAGE,
    docker_platform=DEFAULT_DOCKER_PLATFORM,
    docker_shm_size=DEFAULT_DOCKER_SHM_SIZE,
    docker_memory=DEFAULT_DOCKER_MEMORY,
    docker_cpus=DEFAULT_DOCKER_CPUS,
    docker_ready_timeout=DEFAULT_DOCKER_READY_TIMEOUT,
    http_proxy=None,
    https_proxy=None,
    no_proxy=None,
):
    app_spec = get_app_spec(app_name)
    e2b_metadata = None
    docker_metadata = None
    if env_backend == "e2b":
        e2b_metadata = {
            "gui_synth_env": "1",
            "source": "evaluation",
            "mode": run_mode,
            "app": app_name,
            "pid": str(os.getpid()),
        }
        if run_id:
            e2b_metadata["run_id"] = run_id
        if task and task.get("id"):
            e2b_metadata["task_id"] = str(task["id"])
    elif env_backend == "docker":
        docker_metadata = {
            "gui_synth_env": "1",
            "source": "evaluation",
            "mode": run_mode,
            "app": app_name,
            "pid": str(os.getpid()),
        }
        if run_id:
            docker_metadata["run_id"] = run_id
        if task and task.get("id"):
            docker_metadata["task_id"] = str(task["id"])

    sandbox = create_env(
        backend=env_backend,
        timeout=sandbox_timeout,
        resolution=(DISPLAY_WIDTH, DISPLAY_HEIGHT),
        template=DEFAULT_E2B_TEMPLATE,
        docker_image=docker_image,
        docker_platform=docker_platform,
        docker_shm_size=docker_shm_size,
        docker_memory=docker_memory,
        docker_cpus=docker_cpus,
        docker_ready_timeout=docker_ready_timeout,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
        no_proxy=no_proxy,
        app_name=app_name,
        docker_metadata=docker_metadata,
        e2b_metadata=e2b_metadata,
    )
    try:
        try:
            sandbox.stream.start()
        except RuntimeError:
            pass
        stream_url = sandbox.stream.get_url(resize="scale")

        upload_verifier(sandbox, app_name)
        upload_task_env_files(sandbox, task)

        app_context = AppContext(
            sandbox=sandbox,
            app_spec=app_spec,
            task=task,
            env_backend=env_backend,
            display_width=DISPLAY_WIDTH,
            display_height=DISPLAY_HEIGHT,
        )
        for hook in app_spec.prepare_task_hooks:
            hook(app_context)
        run_task_setup_scripts(sandbox, task)
        for hook in app_spec.prepare_profile_hooks:
            hook(app_context)

        launch_app(app_context)
        if not app_spec.ready_check(sandbox):
            raise RuntimeError(
                f"{app_name} failed service/process ready check.\n"
                f"{format_app_log_excerpt(app_context)}"
            )
        if not wait_for_app_window_ready(app_context):
            raise RuntimeError(
                f"{app_name} window did not become visible and stable.\n"
                f"{describe_windows(sandbox)}\n"
                f"{format_app_log_excerpt(app_context)}"
            )
        return SandboxSession(
            sandbox=sandbox,
            stream_url=stream_url,
            app_context=app_context,
        )
    except BaseException:
        try:
            sandbox.kill()
        except Exception as exc:
            print(f"  WARNING: failed to kill sandbox during setup cleanup: {exc}")
        raise


def setup_sandbox(*args, **kwargs):
    session = setup_sandbox_session(*args, **kwargs)
    return session.sandbox, session.stream_url
