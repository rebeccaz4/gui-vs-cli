#!/usr/bin/env python3
"""
Open an interactive desktop sandbox for manual testing.

Usage:
    python evaluation/interactive_sandbox.py
    python evaluation/interactive_sandbox.py --app kdenlive
    python evaluation/interactive_sandbox.py --app kdenlive --task kdenlive_add_clip_01
    python evaluation/interactive_sandbox.py --timeout 3600
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import dotenv
except ModuleNotFoundError:
    dotenv = None

if dotenv is not None:
    dotenv.load_dotenv()

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

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
    ensure_backend_support,
)
from evaluation.apps.registry import get_app_spec, list_app_ids
from evaluation.apps.save import app_window_patterns, auto_save_app
from evaluation.apps.utils import describe_windows
from evaluation.runtime.run_config import DISPLAY_HEIGHT, DISPLAY_WIDTH, TASK_GEN_DIR
from evaluation.runtime.sandbox_session import setup_sandbox_session, upload_verifier
from evaluation.runtime.verification import run_verifier


def load_task(task_id: str) -> dict | None:
    task_file = TASK_GEN_DIR / "tasks" / task_id / "task.json"
    if not task_file.exists():
        return None
    with open(task_file) as handle:
        return json.load(handle)


def run_verifier_command(sandbox, app_name: str, verifier_args: str) -> None:
    if not app_name:
        print("  No app selected.")
        return
    if not verifier_args.strip():
        print("  Usage: verify <verifier-args>")
        return
    result = run_verifier(sandbox, app_name, verifier_args)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def run_task_verifications(sandbox, app_name: str, task: dict | None) -> None:
    if not app_name:
        print("  No app selected.")
        return
    if not task or not task.get("verification"):
        print("  No task verification commands available.")
        return
    for verification in task["verification"]:
        command = verification["command"]
        description = verification.get("description", command)
        print(f"\n== {description} ==")
        run_verifier_command(sandbox, app_name, command)


def main():
    parser = argparse.ArgumentParser(description="Interactive desktop sandbox")
    parser.add_argument("--app", type=str, default=None, help="App to launch")
    parser.add_argument("--task", type=str, default=None, help="Task ID to load env files for")
    parser.add_argument("--timeout", type=int, default=1800, help="Sandbox timeout in seconds (default 1800)")
    parser.add_argument(
        "--env-backend",
        choices=["e2b", "docker"],
        default=DEFAULT_ENV_BACKEND,
        help=f"Environment backend to use (default: {DEFAULT_ENV_BACKEND})",
    )
    parser.add_argument(
        "--docker-image",
        type=str,
        default=DEFAULT_DOCKER_IMAGE,
        help=f"Docker image for --env-backend docker (default: {DEFAULT_DOCKER_IMAGE})",
    )
    parser.add_argument(
        "--docker-platform",
        type=str,
        default=DEFAULT_DOCKER_PLATFORM,
        help=f"Docker platform for --env-backend docker (default: {DEFAULT_DOCKER_PLATFORM})",
    )
    parser.add_argument(
        "--docker-shm-size",
        type=str,
        default=DEFAULT_DOCKER_SHM_SIZE,
        help=f"Docker shm size for --env-backend docker (default: {DEFAULT_DOCKER_SHM_SIZE})",
    )
    parser.add_argument(
        "--docker-memory",
        type=str,
        default=DEFAULT_DOCKER_MEMORY,
        help="Docker memory limit for --env-backend docker (default: unset)",
    )
    parser.add_argument(
        "--docker-cpus",
        type=str,
        default=DEFAULT_DOCKER_CPUS,
        help="Docker CPU limit for --env-backend docker (default: unset)",
    )
    parser.add_argument(
        "--docker-ready-timeout",
        type=int,
        default=DEFAULT_DOCKER_READY_TIMEOUT,
        help=f"Docker desktop ready timeout in seconds (default: {DEFAULT_DOCKER_READY_TIMEOUT})",
    )
    args = parser.parse_args()

    task = load_task(args.task) if args.task else None
    if args.task and not task:
        print(f"Task not found: {args.task}")
        sys.exit(1)

    if args.app and args.app not in list_app_ids():
        print(f"Unknown app: {args.app}")
        print(f"Available: {', '.join(list_app_ids())}")
        sys.exit(1)

    if args.app:
        ensure_backend_support(args.env_backend, args.app)

    print("Creating sandbox...")
    if args.app:
        session = setup_sandbox_session(
            args.app,
            task,
            args.timeout,
            env_backend=args.env_backend,
            docker_image=args.docker_image,
            docker_platform=args.docker_platform,
            docker_shm_size=args.docker_shm_size,
            docker_memory=args.docker_memory,
            docker_cpus=args.docker_cpus,
            docker_ready_timeout=args.docker_ready_timeout,
        )
        sandbox = session.sandbox
        stream_url = session.stream_url
    else:
        sandbox = create_env(
            backend=args.env_backend,
            timeout=args.timeout,
            resolution=(DISPLAY_WIDTH, DISPLAY_HEIGHT),
            template=DEFAULT_E2B_TEMPLATE,
            docker_image=args.docker_image,
            docker_platform=args.docker_platform,
            docker_shm_size=args.docker_shm_size,
            docker_memory=args.docker_memory,
            docker_cpus=args.docker_cpus,
            docker_ready_timeout=args.docker_ready_timeout,
            app_name=None,
        )
        try:
            sandbox.stream.start()
        except RuntimeError:
            pass
        stream_url = sandbox.stream.get_url(resize="scale")

    print(f"\n{'=' * 60}")
    print("  Sandbox ready!")
    print(f"  Backend: {args.env_backend}")
    print(f"  URL: {stream_url}")
    print(f"  Timeout: {args.timeout}s")
    print(f"{'=' * 60}\n")

    app_name = args.app or "unknown"
    if args.app:
        app_spec = get_app_spec(args.app)
        print(f"  App launched: {args.app} via {app_spec.canonical_launcher}")
        upload_verifier(sandbox, args.app)

    print("\nCommands:")
    print("  save          — Send the configured save shortcut to the app")
    print("  windows       — List matching X11 windows for the app")
    print("  screenshot    — Take a screenshot")
    print("  verify <args> — Run the app verifier with given arguments")
    print("  verify-task   — Run all verification commands for the loaded task")
    print("  run <cmd>     — Run a command in the sandbox")
    print("  quit          — Shut down and exit")
    print()

    if task and task.get("verification"):
        print("Task checks:")
        for verification in task["verification"]:
            print(f"  verify {verification['command']}")
        print()

    try:
        while True:
            try:
                command = input("sandbox> ").strip()
            except EOFError:
                break

            if not command:
                continue
            if command == "quit":
                break
            if command == "save":
                if not args.app:
                    print("  No app selected.")
                    continue
                app_spec = get_app_spec(args.app)
                if not app_spec.save_shortcut:
                    print(f"  No save shortcut configured for {args.app}.")
                    continue
                try:
                    result = auto_save_app(
                        sandbox,
                        args.app,
                        app_spec.save_shortcut,
                        save_window_name=app_spec.save_window_name,
                    )
                    print(result["message"])
                    if result["stderr"]:
                        print(result["stderr"])
                except Exception as exc:
                    print(f"  Save command failed: {exc}")
                continue
            if command == "windows":
                output = describe_windows(
                    sandbox,
                    patterns=app_window_patterns(args.app) if args.app else None,
                )
                print(output or "  No matching windows found.")
                continue
            if command == "screenshot":
                screenshot = sandbox.screenshot()
                filename = f"sandbox_screenshot_{int(time.time())}.png"
                with open(filename, "wb") as handle:
                    handle.write(screenshot)
                print(f"  Saved: {filename}")
                continue
            if command == "verify-task":
                run_task_verifications(sandbox, args.app, task)
                continue
            if command.startswith("verify "):
                run_verifier_command(sandbox, args.app, command[7:])
                continue
            if command.startswith("run "):
                shell_command = command[4:]
                try:
                    result = sandbox.commands.run(f"DISPLAY=:0 {shell_command}", timeout=30)
                    if result.stdout:
                        print(result.stdout)
                    if result.stderr:
                        print(f"STDERR: {result.stderr}")
                except Exception as exc:
                    print(f"  Error: {exc}")
                continue
            print(f"  Unknown command: {command}")
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        sandbox.kill()


if __name__ == "__main__":
    main()
