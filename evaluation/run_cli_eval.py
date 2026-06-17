#!/usr/bin/env python3
"""
CLI Evaluation Runner — execute tasks using CLI agents (Claude Code or Codex).

Usage:
    python evaluation/run_cli_eval.py
    python evaluation/run_cli_eval.py --app drawio
    python evaluation/run_cli_eval.py --app drawio --task drawio_kubernetes_cluster
    python evaluation/run_cli_eval.py --provider claude --model opus-4.7
    python evaluation/run_cli_eval.py --provider codex --model gpt-5.5
    python evaluation/run_cli_eval.py --tasks-per-app 3
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent

try:
    import dotenv
except ModuleNotFoundError:
    dotenv = None

if dotenv is not None:
    # Explicitly load .env from project root
    dotenv.load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from computer_env import (
    DEFAULT_DOCKER_CPUS,
    DEFAULT_DOCKER_MEMORY,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_DOCKER_READY_TIMEOUT,
    DEFAULT_DOCKER_SHM_SIZE,
)
from computer_env.backends.docker.runtime import cleanup_active_docker_containers
from evaluation.runtime.reporting import generate_report
from evaluation.runtime.run_config import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_SANDBOX_TIMEOUT,
)
from evaluation.runtime.sandbox_session import setup_sandbox_session
from evaluation.runtime.tasks import get_completed_tasks, load_existing_results, load_tasks
from evaluation.runtime.verification import verify_task

# Import CLI agent runner
from evaluation.runtime.cli_agent_runner import (
    build_task_prompt,
    run_cli_agent_interactive,
)


LIBREOFFICE_RELOAD_MODES = {
    "libreoffice_calc": "--calc",
    "libreoffice_impress": "--impress",
    "libreoffice_writer": "--writer",
    "libreoffice_draw": "--draw",
}


def _cleanup_docker_on_interrupt(env_backend: str, run_id: str | None = None) -> None:
    if env_backend != "docker":
        return

    cleaned = cleanup_active_docker_containers()
    print("\nInterrupted by user. Cleaned up docker containers:")
    for container_id in cleaned:
        print(f"  {container_id}")


def _reload_path_from_task(task: dict) -> str | None:
    """Return the preferred sandbox path to open before verification."""
    reload_files = task.get("env", {}).get("reload_files", [])
    if reload_files:
        return str(reload_files[0])

    for file_entry in task.get("env", {}).get("files", []):
        sandbox_path = file_entry.get("sandbox_path")
        if sandbox_path:
            return str(sandbox_path)
    return None


def _reload_libreoffice_file_for_cli_verification(sandbox, app_name: str, task: dict) -> None:
    """Open the task document in LibreOffice so verifiers read it via UNO."""
    reload_mode = LIBREOFFICE_RELOAD_MODES.get(app_name)
    if not reload_mode:
        return

    reload_path = _reload_path_from_task(task)
    if not reload_path:
        print("  LibreOffice reload warning: no reload file found in task env")
        return

    quoted_path = shlex.quote(reload_path)
    command = (
        "pkill -x soffice.bin 2>/dev/null || true; "
        "pkill -x soffice 2>/dev/null || true; "
        "sleep 1; "
        f"soffice {reload_mode} "
        "'--accept=socket,host=localhost,port=2002;urp;' "
        "--norestore --nologo "
        f"{quoted_path} >/tmp/libreoffice_cli_reload.log 2>&1 & "
        "sleep 4"
    )
    sandbox.commands.run(command, timeout=15)
    print(f"  LibreOffice reload: opened {reload_path}")


def load_cli_feasible_tasks(app_names: list[str] | None = None) -> list[dict]:
    """Load CLI-feasible tasks for specified apps.

    Note: Tasks are pre-filtered in task_generator/tasks/ directory.
    All remaining tasks have already passed CLI feasibility screening,
    and GUI-oriented tasks already use task_fair instead of task.
    """
    all_tasks = []

    if not app_names:
        # If no apps specified, load from all available apps
        from evaluation.apps.registry import list_app_ids
        target_apps = list_app_ids()
    else:
        target_apps = app_names

    for app_name in target_apps:
        tasks = load_tasks(app_name)
        for task in tasks:
            # Tasks are already pre-filtered for CLI feasibility
            all_tasks.append((app_name, task))

    return all_tasks


def select_cli_tasks(
    all_tasks: list[tuple[str, dict]],
    *,
    task_id: str | None = None,
    tasks_per_app: int | None = None,
    completed: set[str] | None = None,
) -> list[tuple[str, dict]]:
    """Select CLI tasks using the same ordering/cap semantics as GUI eval."""
    completed = completed or set()

    if task_id:
        return [(app_name, task) for app_name, task in all_tasks if task["id"] == task_id]

    from collections import defaultdict

    by_app: dict[str, list[dict]] = defaultdict(list)
    for app_name, task in all_tasks:
        by_app[app_name].append(task)

    selected: list[tuple[str, dict]] = []
    for app_name in sorted(by_app):
        sorted_tasks = sorted(by_app[app_name], key=lambda t: t["id"])
        if tasks_per_app is not None and tasks_per_app > 0:
            completed_for_app = sum(1 for task in sorted_tasks if task["id"] in completed)
            remaining_slots = max(0, tasks_per_app - completed_for_app)
            pending = [task for task in sorted_tasks if task["id"] not in completed]
            app_tasks = pending[:remaining_slots]
        else:
            app_tasks = [task for task in sorted_tasks if task["id"] not in completed]
        selected.extend((app_name, task) for task in app_tasks)

    return selected


def run_single_cli_task(
    app_name: str,
    task: dict,
    provider: str,
    model_name: str,
    run_dir: Path,
    run_id: str,
    max_iterations: int,
    sandbox_timeout: int,
    docker_image: str,
    docker_platform: str,
    docker_shm_size: str,
    docker_memory: str | None,
    docker_cpus: str | None,
    docker_ready_timeout: int,
) -> dict:
    """Run a single task using CLI agent (Claude Code or Codex)."""
    task_id = task["id"]
    task_text = build_task_prompt(task)

    traj_dir = run_dir / "trajectories" / task_id
    traj_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"  Task:  {task_id}")
    print(f"  App:   {app_name}")
    print(f"  Model: {provider}/{model_name}")
    print(f"  Mode:  CLI ({provider.capitalize()})")
    print(f"  Desc:  {task_text[:100]}...")
    print(f"{'=' * 70}")

    import time
    start_time = time.time()
    sandbox = None

    try:
        # Set up sandbox (but don't launch the GUI app)
        session = setup_sandbox_session(
            app_name,
            task,
            sandbox_timeout,
            run_id=run_id,
            run_mode="cli",
            env_backend="docker",
            docker_image=docker_image,
            docker_platform=docker_platform,
            docker_shm_size=docker_shm_size,
            docker_memory=docker_memory,
            docker_cpus=docker_cpus,
            docker_ready_timeout=docker_ready_timeout,
        )
        sandbox = session.sandbox
        stream_url = session.stream_url
        print(f"  Desktop: {stream_url}")

        # Run CLI Agent
        print(f"  Running {provider.capitalize()} CLI...")

        agent_done, steps, trajectory, model_metadata = run_cli_agent_interactive(
            sandbox,
            task,
            provider,
            model_name,
            max_iterations,
            traj_dir,
        )
        print(f"  Agent finished in {steps} steps (done={agent_done})")

        _reload_libreoffice_file_for_cli_verification(sandbox, app_name, task)

        # Verify results
        print("  Verifying...")
        passed, total, details = verify_task(
            sandbox,
            app_name,
            task["verification"],
            trajectory=None,
            traj_dir=traj_dir,
        )

        for detail in details:
            if detail is None:
                continue
            status = "PASS" if detail["passed"] else "FAIL"
            command = detail.get("command", "")
            description = detail.get("description", command)
            if detail.get("judge") == "llm":
                reason = detail.get("reason", "")
                print(f"    {status}  [LLM] {description} — {reason}")
            elif "key" in detail:
                print(
                    f"    {status}  {command} -> {detail['key']}={detail['actual']} "
                    f"(expected {detail['expected']})"
                )
            else:
                print(f"    {status}  {description}")

        elapsed = time.time() - start_time
        reward = passed / total if total > 0 else 0.0
        print(f"  Result: {passed}/{total} — reward={reward:.2f} ({elapsed:.0f}s)")

        result = {
            "task_id": task_id,
            "app": app_name,
            "provider": provider,
            "model": model_name,
            "requested_model": model_metadata.get("requested_model"),
            "resolved_model": model_metadata.get("resolved_model"),
            "reported_model": model_metadata.get("reported_model"),
            "model_source": model_metadata.get("model_source"),
            "task": task_text,
            "env_backend": "docker_cli",
            "agent_done": agent_done,
            "agent_steps": steps,
            "checks_passed": passed,
            "checks_total": total,
            "reward": reward,
            "elapsed_seconds": round(elapsed, 1),
            "stream_url": stream_url,
            "timestamp": datetime.now().isoformat(),
        }

        traj_data = {**result, "verification_details": details, "trajectory": trajectory}
        with open(traj_dir / "trajectory.json", "w") as handle:
            json.dump(traj_data, handle, indent=2, default=str)

        return result

    except Exception as exc:
        import traceback
        elapsed = time.time() - start_time
        print(f"  ERROR: {exc}")
        traceback.print_exc()
        result = {
            "task_id": task_id,
            "app": app_name,
            "provider": provider,
            "model": model_name,
            "task": task_text,
            "env_backend": "docker_cli",
            "agent_done": False,
            "agent_steps": 0,
            "checks_passed": 0,
            "checks_total": len(task.get("verification", [])),
            "reward": 0.0,
            "elapsed_seconds": round(elapsed, 1),
            "error": str(exc),
            "timestamp": datetime.now().isoformat(),
        }
        with open(traj_dir / "trajectory.json", "w") as handle:
            json.dump(result, handle, indent=2, default=str)
        return result

    finally:
        if sandbox:
            try:
                sandbox.kill()
            except Exception as exc:
                print(f"  WARNING: failed to kill sandbox for {task_id}: {exc}")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CLI agents (Claude Code or Codex) across apps and tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--app",
        type=str,
        action="append",
        dest="apps",
        help="App(s) to evaluate (drawio, shotcut). Default: both.",
    )
    parser.add_argument("--task", type=str, help="Run a specific task by ID (requires --app)")
    parser.add_argument(
        "--tasks-per-app",
        type=int,
        default=None,
        metavar="N",
        help="Run at most N tasks per app (default: all CLI-feasible tasks).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["claude", "codex"],
        default="claude",
        help="Provider to use: claude or codex (default: claude)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name (default: opus-4.7 for claude, gpt-5.5 for codex)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=f"Max agent iterations per task (default: {DEFAULT_MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=int,
        default=DEFAULT_SANDBOX_TIMEOUT,
        help=f"Sandbox timeout in seconds (default: {DEFAULT_SANDBOX_TIMEOUT})",
    )
    parser.add_argument(
        "--resume",
        type=str,
        metavar="RUN_ID",
        help="Resume a previous CLI run, skipping completed tasks",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        metavar="NAME",
        help="Output directory name under runs/cli/ (e.g., --output-dir test-sonnet). "
             "If not specified, uses auto-generated name cli_{model}_{timestamp}.",
    )
    parser.add_argument(
        "--skip-completed",
        type=lambda x: x.lower() in ("true", "1", "yes", "on") if x is not None else True,
        default=True,
        metavar="BOOL",
        help="Whether to skip completed tasks when output-dir exists (default: true). "
             "Set to 'false' to re-run all tasks including completed ones.",
    )
    parser.add_argument("--list-tasks", action="store_true", help="List CLI-feasible tasks and exit")
    parser.add_argument("--parallel", type=int, default=1, metavar="N", help="Run N tasks in parallel (default: 1)")
    parser.add_argument(
        "--docker-image",
        type=str,
        default="paraverse-agent-runtime:latest",
        help="Docker image (default: paraverse-agent-runtime:latest)",
    )
    parser.add_argument(
        "--docker-platform",
        type=str,
        default=DEFAULT_DOCKER_PLATFORM,
        help=f"Docker platform (default: {DEFAULT_DOCKER_PLATFORM})",
    )
    parser.add_argument(
        "--docker-shm-size",
        type=str,
        default=DEFAULT_DOCKER_SHM_SIZE,
        help=f"Docker shm size (default: {DEFAULT_DOCKER_SHM_SIZE})",
    )
    parser.add_argument(
        "--docker-memory",
        type=str,
        default=DEFAULT_DOCKER_MEMORY,
        help="Docker memory limit (default: unset)",
    )
    parser.add_argument(
        "--docker-cpus",
        type=str,
        default=DEFAULT_DOCKER_CPUS,
        help="Docker CPU limit (default: unset)",
    )
    parser.add_argument(
        "--docker-ready-timeout",
        type=int,
        default=DEFAULT_DOCKER_READY_TIMEOUT,
        help=f"Docker ready timeout in seconds (default: {DEFAULT_DOCKER_READY_TIMEOUT})",
    )

    args = parser.parse_args()

    # Handle provider and model
    from evaluation.runtime.model_mapping import get_default_model

    # Set default model if not specified
    if not args.model:
        args.model = get_default_model(args.provider)

    print(f"Using provider: {args.provider}, model: {args.model}")

    # Load CLI-feasible tasks
    all_tasks = load_cli_feasible_tasks(args.apps)

    if args.list_tasks:
        print("CLI-feasible tasks:")
        for app_name, task in all_tasks:
            feasible = task.get("cli_feasibility", {}).get("feasible", "no")
            translation = task.get("cli_feasibility", {}).get("translation", "")[:50]
            print(f"  [{app_name}] {task['id']:45s} feasible={feasible} | {translation}...")
        return

    if not all_tasks:
        print("No CLI-feasible tasks found for the specified apps.")
        return
    requested_apps = sorted(set(app_name for app_name, _ in all_tasks))

    # Create run directory
    completed: set[str] = set()
    existing_results: list[dict] = []
    if args.resume:
        # Resume from existing run
        run_id = args.resume
        run_dir = EVAL_DIR / "runs" / "cli" / args.resume
        if not run_dir.exists():
            print(f"Run directory not found: {run_dir}")
            sys.exit(1)
        completed = get_completed_tasks(run_dir)
        existing_results = load_existing_results(run_dir)
        if args.task:
            completed.discard(args.task)
            existing_results = [result for result in existing_results if result["task_id"] != args.task]
        print(f"Resuming run {args.resume}")
    elif args.output_dir:
        # Use specified output directory
        run_id = args.output_dir
        run_dir = EVAL_DIR / "runs" / "cli" / args.output_dir
        if run_dir.exists():
            completed = get_completed_tasks(run_dir)
            existing_results = load_existing_results(run_dir)
            if args.skip_completed:
                print(f"Output directory exists: {args.output_dir} — {len(completed)} tasks already done, will skip completed tasks")
            else:
                print(f"Output directory exists: {args.output_dir} — {len(completed)} tasks already done, will re-run all tasks (--skip-completed=false)")
                completed = set()
                existing_results = []
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Auto-generate run directory name
        run_id = f"cli_{args.provider}_{args.model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = EVAL_DIR / "runs" / "cli" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

    all_tasks = select_cli_tasks(
        all_tasks,
        task_id=args.task,
        tasks_per_app=args.tasks_per_app,
        completed=completed,
    )
    if args.task and not all_tasks:
        print(f"Task '{args.task}' not found, not CLI-feasible, or already completed.")
        return

    # Save config
    run_config = {
        "mode": "cli",
        "provider": args.provider,
        "model": args.model,
        "apps": requested_apps,
        "tasks_per_app": args.tasks_per_app,
        "skip_completed": args.skip_completed,
        "docker_image": args.docker_image,
        "docker_platform": args.docker_platform,
        "docker_shm_size": args.docker_shm_size,
        "docker_memory": args.docker_memory,
        "docker_cpus": args.docker_cpus,
        "docker_ready_timeout": args.docker_ready_timeout,
        "max_iterations": args.max_iterations,
        "sandbox_timeout": args.sandbox_timeout,
        "parallel": args.parallel,
        "started": datetime.now().isoformat(),
    }
    with open(run_dir / "config.json", "w") as handle:
        json.dump(run_config, handle, indent=2)

    total = len(all_tasks) + len(completed)
    parallel = max(1, args.parallel)
    print(f"\nCLI Evaluation: {len(all_tasks)} tasks to run ({len(completed)} already done, {total} total)")
    print(f"Provider: {args.provider}")
    print(f"Model: {args.model}")
    print(f"Docker image: {args.docker_image}")
    print(f"Parallel: {parallel}")
    print(f"Run dir: {run_dir}\n")

    all_results = list(existing_results)
    results_lock = threading.Lock()
    counter = {"done": len(existing_results)}

    def run_one(app_name, task):
        with results_lock:
            counter["done"] += 1
            index = counter["done"]
        print(f"\n[{index}/{total}] Starting {task['id']}...")
        result = run_single_cli_task(
            app_name,
            task,
            args.provider,
            args.model,
            run_dir,
            run_id,
            args.max_iterations,
            args.sandbox_timeout,
            args.docker_image,
            args.docker_platform,
            args.docker_shm_size,
            args.docker_memory,
            args.docker_cpus,
            args.docker_ready_timeout,
        )
        with results_lock:
            all_results.append(result)
            with open(run_dir / "results.jsonl", "a") as handle:
                handle.write(json.dumps(result, default=str) + "\n")
        return result

    try:
        if parallel == 1:
            for app_name, task in all_tasks:
                run_one(app_name, task)
        else:
            pool = ThreadPoolExecutor(max_workers=parallel)
            futures = {pool.submit(run_one, app_name, task): task["id"] for app_name, task in all_tasks}
            try:
                for future in as_completed(futures):
                    task_id = futures[future]
                    try:
                        result = future.result()
                        status = "PASS" if result["reward"] == 1.0 else f"reward={result['reward']:.2f}"
                        print(f"  >> Completed {task_id}: {status}")
                    except Exception as exc:
                        print(f"  >> EXCEPTION {task_id}: {exc}")
            except BaseException:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                pool.shutdown(wait=True)

        # Deduplicate and save results
        deduped = {}
        for result in all_results:
            deduped[result["task_id"]] = result
        deduped_results = list(deduped.values())
        with open(run_dir / "results.jsonl", "w") as handle:
            for result in deduped_results:
                handle.write(json.dumps(result, default=str) + "\n")

        # Generate report
        if deduped_results:
            generate_report(deduped_results, run_dir, args.model, requested_apps)

    except KeyboardInterrupt:
        _cleanup_docker_on_interrupt("docker", run_id)
        sys.exit(130)


if __name__ == "__main__":
    main()
