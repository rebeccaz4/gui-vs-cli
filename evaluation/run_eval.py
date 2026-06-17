#!/usr/bin/env python3
"""
Evaluation runner — execute tasks across apps and models, save trajectories + final report.

Usage:
    python evaluation/run_eval.py
    python evaluation/run_eval.py --app libreoffice_calc
    python evaluation/run_eval.py --app chrome --task chrome_form_fill_httpbin
    python evaluation/run_eval.py --model claude-sonnet-4-5
    python evaluation/run_eval.py --model gui-owl-1.5

    # Run multiple apps
    python evaluation/run_eval.py --app chrome --app firefox --app brave

    # Run all apps EXCEPT some
    python evaluation/run_eval.py --skip-app zoom

    # Run only N tasks per app (useful for smoke tests / sampling)
    python evaluation/run_eval.py --tasks-per-app 3

    python evaluation/run_eval.py --env-backend docker --one-task-per-app
    python evaluation/run_eval.py --env-backend docker --one-task-per-app --ready-check-only

    # Resume a previous run (skip already-completed tasks)
    python evaluation/run_eval.py --resume <run_id>
    python evaluation/run_eval.py --list-apps
    python evaluation/run_eval.py --list-models
    python evaluation/run_eval.py --list-tasks --app chrome
    python evaluation/run_eval.py --max-iterations 15 --sandbox-timeout 1800

    # Point the agent at a local OpenAI-compatible endpoint on port 8001 / 8002
    python evaluation/run_eval.py --model gui-owl-1.5 --endpoint-port 8001
    python evaluation/run_eval.py --model gui-owl-1.5 --endpoint-url http://localhost:8002/v1

    # Use endpoint url for bltcy
    python evaluation/run_eval.py --model bltcy-gpt-5.4

    # Use custom API endpoint and key
    python evaluation/run_eval.py --model gpt-5.4 --base-url https://api.openai.com/v1 --api-key sk-xxx

    # Specify output directory name
    python evaluation/run_eval.py --output-dir gpt5.4

    # Control whether to skip completed tasks when resuming
    python evaluation/run_eval.py --output-dir gpt5.4 --skip-completed false
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import dotenv
except ModuleNotFoundError:
    dotenv = None

if dotenv is not None:
    dotenv.load_dotenv()

# Clear ALL_PROXY to avoid SOCKS proxy requirements in httpx
# We only want HTTP_PROXY and HTTPS_PROXY for API calls, not SOCKS
for proxy_var in ['ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent
GUI_RUNS_DIR = EVAL_DIR / "runs" / "gui"
sys.path.insert(0, str(PROJECT_ROOT))

from agents import list_models
from computer_env import (
    DEFAULT_DOCKER_CPUS,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_MEMORY,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_DOCKER_READY_TIMEOUT,
    DEFAULT_DOCKER_SHM_SIZE,
    DEFAULT_ENV_BACKEND,
)
from computer_env.backends.docker.runtime import cleanup_active_docker_containers, cleanup_docker_containers_by_metadata
from computer_env.backends.e2b.runtime import (
    cleanup_active_e2b_sandboxes,
    cleanup_e2b_sandboxes_by_metadata,
)
from evaluation.apps.registry import list_app_ids
from evaluation.runtime.reporting import generate_report
from evaluation.runtime.run_config import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MODEL,
    DEFAULT_SANDBOX_TIMEOUT,
)
from evaluation.runtime.task_runner import run_single_task
from evaluation.runtime.tasks import (
    get_completed_tasks,
    load_existing_results,
    load_tasks,
    select_pending_tasks,
    set_tasks_dir,
)


def _mask_secret(value: str, visible: int = 8) -> str:
    if len(value) <= visible:
        return "*" * len(value)
    return f"{value[:visible]}..."


def _cleanup_docker_on_interrupt(env_backend: str, run_id: str | None = None) -> None:
    if env_backend != "docker":
        return

    cleaned = cleanup_active_docker_containers()
    if run_id:
        for container_id in cleanup_docker_containers_by_metadata(
            {
                "gui_synth_env": "1",
                "source": "evaluation",
                "mode": "gui",
                "run_id": run_id,
            }
        ):
            if container_id not in cleaned:
                cleaned.append(container_id)

    if cleaned:
        print("\nInterrupted by user. Cleaned up docker containers:")
        for container_id in cleaned:
            print(f"  {container_id}")
    else:
        print("\nInterrupted by user. No active docker containers needed cleanup.")


def _cleanup_active_e2b_on_interrupt(env_backend: str, run_id: str | None = None) -> None:
    if env_backend != "e2b":
        return

    cleaned = cleanup_active_e2b_sandboxes()
    if run_id:
        extra = cleanup_e2b_sandboxes_by_metadata(
            {
                "gui_synth_env": "1",
                "source": "evaluation",
                "mode": "gui",
                "run_id": run_id,
            }
        )
        for sandbox_id in extra:
            if sandbox_id not in cleaned:
                cleaned.append(sandbox_id)

    if cleaned:
        print("\nInterrupted by user. Cleaned up e2b sandboxes:")
        for sandbox_id in cleaned:
            print(f"  {sandbox_id}")
    else:
        print("\nInterrupted by user. No active e2b sandboxes needed cleanup.")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate GUI agents across apps and tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--app",
        type=str,
        action="append",
        dest="apps",
        help="App(s) to evaluate (repeat for multiple). Default: all apps.",
    )
    parser.add_argument(
        "--skip-app",
        type=str,
        action="append",
        dest="skip_apps",
        default=[],
        help="App(s) to exclude from the run (repeat for multiple).",
    )
    parser.add_argument("--task", type=str, help="Run a specific task by ID (requires --app)")
    parser.add_argument(
        "--tasks-dir",
        type=str,
        default=None,
        help="Directory containing task subdirectories with task.json files "
             "(default: task_generator/tasks).",
    )
    parser.add_argument(
        "--task-field",
        type=str,
        default="task",
        help="Field in task.json to send to the agent as the task prompt "
             "(default: task). Use task_grounding for grounded prompts.",
    )
    parser.add_argument(
        "--tasks-per-app",
        type=int,
        default=None,
        metavar="N",
        help="Run at most N tasks per app (default: all tasks). "
             "Already-completed tasks for an app count toward the cap so "
             "resuming never exceeds N total runs per app.",
    )
    parser.add_argument(
        "--one-task-per-app",
        action="store_true",
        help="Run at most one pending task per app (useful for smoke tests)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Optional label for paired GUI/CLI comparisons. GUI agent selection is controlled by --model.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model alias (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=f"Max agent steps per task (default: {DEFAULT_MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=int,
        default=DEFAULT_SANDBOX_TIMEOUT,
        help=f"Sandbox timeout in seconds (default: {DEFAULT_SANDBOX_TIMEOUT})",
    )
    parser.add_argument("--resume", type=str, metavar="RUN_ID", help="Resume a previous run, skipping completed tasks")
    parser.add_argument(
        "--output-dir",
        type=str,
        metavar="NAME",
        help="Output directory name under runs/gui/ (e.g., --output-dir gpt5.4). "
             "If not specified, uses auto-generated name {model}_{timestamp}.",
    )
    parser.add_argument(
        "--skip-completed",
        type=lambda x: x.lower() in ("true", "1", "yes", "on") if x is not None else True,
        default=True,
        metavar="BOOL",
        help="Whether to skip completed tasks when output-dir exists (default: true). "
             "Set to 'false' to re-run all tasks including completed ones.",
    )
    parser.add_argument("--list-apps", action="store_true", help="List available apps and exit")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    parser.add_argument("--parallel", type=int, default=1, metavar="N", help="Run N tasks in parallel (default: 1)")
    parser.add_argument("--list-tasks", action="store_true", help="List tasks for --app and exit")
    parser.add_argument("--keep-alive", action="store_true", help="Keep sandbox alive after each task (interactive)")
    parser.add_argument(
        "--ready-check-only",
        action="store_true",
        help="Only launch the app and wait for ready checks/window readiness; skip agent run and verification",
    )
    parser.add_argument("--run-dir", type=str, help="Save results to this existing eval run directory")
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
    parser.add_argument(
        "--http-proxy",
        type=str,
        default=None,
        help="HTTP proxy for Docker container (default: None)",
    )
    parser.add_argument(
        "--https-proxy",
        type=str,
        default=None,
        help="HTTPS proxy for Docker container (default: None)",
    )
    parser.add_argument(
        "--no-proxy",
        type=str,
        default=None,
        help="No-proxy list for Docker container (default: None)",
    )
    parser.add_argument(
        "--e2b-api-key",
        type=str,
        help="E2B API key (overrides E2B_API_KEY env var)",
    )
    parser.add_argument(
        "--endpoint-port",
        type=int,
        metavar="PORT",
        help="Port of a local OpenAI-compatible model endpoint "
             "(sets OPENAI_BASE_URL=http://localhost:<PORT>/v1). "
             "e.g. --endpoint-port 8001",
    )
    parser.add_argument(
        "--endpoint-url",
        type=str,
        metavar="URL",
        help="Full URL for an OpenAI-compatible model endpoint "
             "(sets OPENAI_BASE_URL). Overrides --endpoint-port.",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        metavar="URL",
        default=None,
        help="Base URL for OpenAI-compatible API endpoint "
             "(sets OPENAI_BASE_URL). If omitted, keeps the existing environment value.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        metavar="KEY",
        default=None,
        help="API key for the endpoint (sets OPENAI_API_KEY). If omitted, keeps the existing environment value.",
    )
    parser.add_argument(
        "--judge-api-key",
        type=str,
        metavar="KEY",
        help="API key for LLM judge (sets JUDGE_API_KEY). "
             "If not specified, uses the same as --api-key.",
    )
    parser.add_argument(
        "--judge-base-url",
        type=str,
        metavar="URL",
        help="Base URL for LLM judge API endpoint (sets JUDGE_BASE_URL). "
             "Default: https://openrouter.ai/api/v1",
    )
    args = parser.parse_args()

    if args.tasks_dir:
        set_tasks_dir(args.tasks_dir)

    if args.e2b_api_key:
        os.environ["E2B_API_KEY"] = args.e2b_api_key

    # Set API key and base URL only when explicitly provided. This preserves
    # working shell/.env credentials and avoids replacing them with stale keys.
    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key
        print(f"Using API key from --api-key: {_mask_secret(args.api_key)}")

    # Set judge API key and base URL
    if args.judge_api_key:
        os.environ["JUDGE_API_KEY"] = args.judge_api_key
        print(f"Using judge API key from --judge-api-key: {_mask_secret(args.judge_api_key)}")
    elif args.api_key:
        # Use the explicitly provided agent key for judge if no separate judge
        # key was provided. If --api-key was omitted, leave existing judge env
        # configuration untouched.
        os.environ["JUDGE_API_KEY"] = args.api_key
        print("Using --api-key for judge")

    if args.judge_base_url:
        os.environ["JUDGE_BASE_URL"] = args.judge_base_url
        print(f"Using judge base URL: {args.judge_base_url}")

    if args.endpoint_url:
        os.environ["OPENAI_BASE_URL"] = args.endpoint_url
        print(f"Using endpoint: {args.endpoint_url}")
    elif args.endpoint_port:
        endpoint = f"http://localhost:{args.endpoint_port}/v1"
        os.environ["OPENAI_BASE_URL"] = endpoint
        print(f"Using endpoint: {endpoint}")
    elif args.base_url:
        os.environ["OPENAI_BASE_URL"] = args.base_url
        print(f"Using endpoint: {args.base_url}")

    available_apps = list_app_ids()

    if args.list_models:
        print("Available models:")
        for model_name in list_models():
            print(f"  {model_name}")
        return

    if args.list_apps:
        print("Available apps:")
        for app_name in available_apps:
            print(f"  {app_name:<25s} ({len(load_tasks(app_name))} tasks)")
        return

    if args.list_tasks:
        if not args.apps:
            print("--list-tasks requires --app")
            sys.exit(1)
        for app_name in args.apps:
            tasks = load_tasks(app_name)
            print(f"\nTasks for {app_name} ({len(tasks)}):")
            for task in tasks:
                print(f"  {task['id']:45s} ({len(task.get('verification', []))} checks)")
        return

    apps_to_run = args.apps if args.apps else available_apps
    for app_name in apps_to_run:
        if app_name not in available_apps:
            print(f"Unknown app: {app_name}. Use --list-apps to see options.")
            sys.exit(1)

    skip_apps = set(args.skip_apps or [])
    for app_name in skip_apps:
        if app_name not in available_apps:
            print(f"Unknown app in --skip-app: {app_name}. Use --list-apps to see options.")
            sys.exit(1)
    if skip_apps:
        apps_to_run = [a for a in apps_to_run if a not in skip_apps]
        if not apps_to_run:
            print("No apps left to run after applying --skip-app.")
            sys.exit(1)
        print(f"Skipping apps: {', '.join(sorted(skip_apps))}")

    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        completed = get_completed_tasks(run_dir)
        existing_results = load_existing_results(run_dir)
    elif args.resume:
        run_dir = GUI_RUNS_DIR / args.resume
        if not run_dir.exists():
            print(f"Run directory not found: {run_dir}")
            sys.exit(1)
        completed = get_completed_tasks(run_dir)
        existing_results = load_existing_results(run_dir)
        print(f"Resuming run {args.resume} — {len(completed)} tasks already done")
    elif args.output_dir:
        run_dir = GUI_RUNS_DIR / args.output_dir
        if run_dir.exists():
            completed = get_completed_tasks(run_dir)
            existing_results = load_existing_results(run_dir)
            if args.skip_completed:
                print(f"Output directory exists: {args.output_dir} — {len(completed)} tasks already done, will skip completed tasks")
            else:
                print(f"Output directory exists: {args.output_dir} — {len(completed)} tasks already done, will re-run all tasks (--skip-completed=false)")
                completed = set()
                existing_results = []
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            completed = set()
            existing_results = []
    else:
        run_id = f"{args.model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = GUI_RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        completed = set()
        existing_results = []

    run_config = {
        "mode": "gui",
        "provider": args.provider,
        "model": args.model,
        "apps": apps_to_run,
        "skip_apps": sorted(skip_apps),
        "env_backend": args.env_backend,
        "docker_image": args.docker_image,
        "docker_platform": args.docker_platform,
        "docker_shm_size": args.docker_shm_size,
        "docker_memory": args.docker_memory,
        "docker_cpus": args.docker_cpus,
        "docker_ready_timeout": args.docker_ready_timeout,
        "http_proxy": args.http_proxy,
        "https_proxy": args.https_proxy,
        "no_proxy": args.no_proxy,
        "one_task_per_app": args.one_task_per_app,
        "tasks_per_app": args.tasks_per_app,
        "tasks_dir": args.tasks_dir,
        "task_field": args.task_field,
        "ready_check_only": args.ready_check_only,
        "max_iterations": args.max_iterations,
        "sandbox_timeout": args.sandbox_timeout,
        "parallel": args.parallel,
        "endpoint_url": args.endpoint_url,
        "endpoint_port": args.endpoint_port,
        "base_url": args.base_url,
        "skip_completed": args.skip_completed,
        "started": datetime.now().isoformat(),
    }
    with open(run_dir / "config.json", "w") as handle:
        json.dump(run_config, handle, indent=2)

    task_queue = []
    if args.task and (args.resume or args.run_dir):
        completed.discard(args.task)
        existing_results = [result for result in existing_results if result["task_id"] != args.task]

    for app_name in apps_to_run:
        tasks = load_tasks(app_name)
        if args.task_field != "task":
            remapped_tasks = []
            for task in tasks:
                if args.task_field not in task:
                    print(f"Task '{task.get('id', '<unknown>')}' missing field '{args.task_field}', skipping")
                    continue
                task = dict(task)
                task["_original_task"] = task.get("task")
                task["_task_field"] = args.task_field
                task["task"] = task[args.task_field]
                remapped_tasks.append(task)
            tasks = remapped_tasks
        if args.task:
            tasks = [task for task in tasks if task["id"] == args.task]
            if not tasks:
                print(f"Task '{args.task}' not found in {app_name}")
                continue
        if args.tasks_per_app is not None and args.tasks_per_app > 0 and not args.task:
            sorted_tasks = sorted(tasks, key=lambda t: t["id"])
            cap = args.tasks_per_app
            # Already-completed tasks for this app count toward the cap so
            # resuming never exceeds N total runs per app.
            completed_for_app = sum(1 for t in sorted_tasks if t["id"] in completed)
            remaining_slots = max(0, cap - completed_for_app)
            if remaining_slots == 0:
                print(f"  [{app_name}] already at cap ({completed_for_app}/{cap}), skipping")
                continue
            pending = [t for t in sorted_tasks if t["id"] not in completed]
            selected_tasks = pending[:remaining_slots]
        else:
            selected_tasks = select_pending_tasks(
                tasks,
                completed,
                one_task_per_app=args.one_task_per_app and not args.task,
            )
        for task in selected_tasks:
            task_queue.append((app_name, task))

    total = len(task_queue) + len(completed)
    parallel = max(1, args.parallel)
    print(f"\nEvaluation: {len(task_queue)} tasks to run ({len(completed)} already done, {total} total)")
    print(f"Model: {args.model}")
    print(f"Backend: {args.env_backend}")
    if args.env_backend == "docker":
        print(f"Docker image: {args.docker_image}")
        print(f"Docker platform: {args.docker_platform}")
        print(f"Docker shm size: {args.docker_shm_size}")
        if args.docker_memory:
            print(f"Docker memory: {args.docker_memory}")
        if args.docker_cpus:
            print(f"Docker CPUs: {args.docker_cpus}")
        print(f"Docker ready timeout: {args.docker_ready_timeout}s")
    if args.one_task_per_app and not args.task:
        print("Task selection: first pending task per app")
    if args.tasks_per_app is not None and args.tasks_per_app > 0 and not args.task:
        print(f"Task selection: at most {args.tasks_per_app} tasks per app")
    if args.ready_check_only:
        print("Mode: ready check only (skip agent + verification)")
    print(f"Parallel: {parallel}")
    print(f"Apps: {', '.join(apps_to_run)}")
    print(f"Run dir: {run_dir}\n")

    all_results = list(existing_results)
    results_lock = threading.Lock()
    counter = {"done": len(existing_results)}

    def run_one(app_name, task):
        with results_lock:
            counter["done"] += 1
            index = counter["done"]
        print(f"\n[{index}/{total}] Starting {task['id']}...")
        result = run_single_task(
            app_name,
            task,
            args.model,
            run_dir,
            run_dir.name,
            args.max_iterations,
            args.sandbox_timeout,
            keep_alive=args.keep_alive,
            ready_check_only=args.ready_check_only,
            env_backend=args.env_backend,
            docker_image=args.docker_image,
            docker_platform=args.docker_platform,
            docker_shm_size=args.docker_shm_size,
            docker_memory=args.docker_memory,
            docker_cpus=args.docker_cpus,
            docker_ready_timeout=args.docker_ready_timeout,
            http_proxy=args.http_proxy,
            https_proxy=args.https_proxy,
            no_proxy=args.no_proxy,
        )
        with results_lock:
            all_results.append(result)
            with open(run_dir / "results.jsonl", "a") as handle:
                handle.write(json.dumps(result, default=str) + "\n")
        return result

    try:
        if parallel == 1:
            for app_name, task in task_queue:
                run_one(app_name, task)
        else:
            pool = ThreadPoolExecutor(max_workers=parallel)
            futures = {pool.submit(run_one, app_name, task): task["id"] for app_name, task in task_queue}
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

        deduped = {}
        for result in all_results:
            deduped[result["task_id"]] = result
        deduped_results = list(deduped.values())
        with open(run_dir / "results.jsonl", "w") as handle:
            for result in deduped_results:
                handle.write(json.dumps(result, default=str) + "\n")

        if deduped_results:
            generate_report(deduped_results, run_dir, args.model, apps_to_run)
    except KeyboardInterrupt:
        _cleanup_docker_on_interrupt(args.env_backend, run_dir.name)
        _cleanup_active_e2b_on_interrupt(args.env_backend, run_dir.name)
        sys.exit(130)


if __name__ == "__main__":
    main()
