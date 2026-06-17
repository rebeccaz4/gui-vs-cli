#!/usr/bin/env python3
"""
Evaluation runner that *replays* the task selection from a previous run.

Looks at an existing eval run (e.g. `bltcy-gpt-5.4_20260423_005550`),
groups its results by app, picks N tasks per app that were already executed
there, and re-runs them with whatever model you choose — using the exact
same pipeline as `run_eval.py` (sandbox setup, agent loop, verification,
trajectory saving, report generation).

Usage:
    # Re-run 5 tasks per app from a source run, using kimi-k2.6
    python evaluation/run_eval_from_run.py \\
        --source-run bltcy-gpt-5.4_20260423_005550 \\
        --model kimi-k2.6

    # Restrict to specific apps
    python evaluation/run_eval_from_run.py \\
        --source-run bltcy-gpt-5.4_20260423_005550 \\
        --model kimi-k2.6 \\
        --app libreoffice_calc --app gimp

    # Only pick tasks the source model FAILED on (reward < 1.0)
    python evaluation/run_eval_from_run.py \\
        --source-run bltcy-gpt-5.4_20260423_005550 \\
        --model kimi-k2.6 \\
        --only-failed

    # Only pick tasks the source model PASSED (reward == 1.0)
    python evaluation/run_eval_from_run.py \\
        --source-run bltcy-gpt-5.4_20260423_005550 \\
        --model kimi-k2.6 \\
        --only-passed

    # Run in parallel and resume across crashes
    python evaluation/run_eval_from_run.py \\
        --source-run bltcy-gpt-5.4_20260423_005550 \\
        --model kimi-k2.6 \\
        --tasks-per-app 5 \\
        --parallel 5 \\
        --resume <new_run_id>

    # Just print the picked plan, don't run anything
    python evaluation/run_eval_from_run.py \\
        --source-run bltcy-gpt-5.4_20260423_005550 \\
        --tasks-per-app 5 --dry-run
"""

import argparse
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import dotenv

dotenv.load_dotenv()

EVAL_DIR = Path(__file__).parent
PROJECT_ROOT = EVAL_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the entire pipeline from run_eval.py — no duplication of sandbox /
# agent / verification logic.
from evaluation.run_eval import (  # noqa: E402
    APP_CONFIGS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MODEL,
    DEFAULT_SANDBOX_TIMEOUT,
    generate_report,
    get_completed_tasks,
    load_existing_results,
    load_tasks,
    run_single_task,
)
from agents import list_models  # noqa: E402


# ── Source-run loading ────────────────────────────────────────────────────────

def _resolve_source_run(source: str) -> Path:
    """Accept either a run_id under evaluation/runs/ or an explicit path."""
    p = Path(source)
    if p.is_absolute() and p.exists():
        return p
    candidate = EVAL_DIR / "runs" / source
    if candidate.exists():
        return candidate
    if p.exists():
        return p
    raise FileNotFoundError(
        f"Could not find source run: {source}. "
        f"Tried {candidate} and {p.resolve()}"
    )


def _load_source_results(run_dir: Path) -> list[dict]:
    """
    Read every task result recorded in a previous run, preferring results.jsonl
    and falling back to per-trajectory files.
    """
    results_file = run_dir / "results.jsonl"
    results: list[dict] = []
    if results_file.exists():
        with open(results_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not results:
        results = load_existing_results(run_dir)

    # Dedup by task_id, keeping the latest entry (results.jsonl is append-only
    # so later entries are more recent).
    seen: dict[str, dict] = {}
    for r in results:
        tid = r.get("task_id")
        if tid:
            seen[tid] = r
    return list(seen.values())


def _filter_results(
    results: list[dict],
    only_failed: bool,
    only_passed: bool,
    skip_errors: bool,
) -> list[dict]:
    out = []
    for r in results:
        reward = r.get("reward")
        if reward is None:
            continue
        if skip_errors and r.get("error"):
            continue
        if only_failed and reward >= 1.0:
            continue
        if only_passed and reward < 1.0:
            continue
        out.append(r)
    return out


def _pick_tasks_per_app(
    source_results: list[dict],
    available_apps: set[str],
    tasks_per_app: int,
    apps_filter: list[str] | None,
    skip_apps: set[str],
    sort_mode: str,
) -> list[tuple[str, str]]:
    """
    Return [(app, task_id), ...] chosen from the source run.

    sort_mode controls task ordering within each app before slicing:
      - "id":              alphabetical by task_id (deterministic, default)
      - "source_order":    in the order they appear in the source run
      - "source_order_rev": reverse source order
      - "reward_asc":      lowest reward first (good with --only-failed)
      - "reward_desc":     highest reward first
    """
    by_app: dict[str, list[dict]] = defaultdict(list)
    for r in source_results:
        app = r.get("app")
        if app:
            by_app[app].append(r)

    if apps_filter:
        wanted_apps = [a for a in apps_filter if a in by_app]
        missing = [a for a in apps_filter if a not in by_app]
        for a in missing:
            print(f"  [warn] app '{a}' has no results in source run, skipping")
    else:
        wanted_apps = sorted(by_app.keys())

    plan: list[tuple[str, str]] = []
    for app in wanted_apps:
        if app in skip_apps:
            continue
        if app not in available_apps:
            print(f"  [warn] app '{app}' is not registered in APP_CONFIGS, skipping")
            continue

        rows = list(by_app[app])

        if sort_mode == "id":
            rows.sort(key=lambda r: r.get("task_id", ""))
        elif sort_mode == "source_order":
            pass  # already in source order
        elif sort_mode == "source_order_rev":
            rows.reverse()
        elif sort_mode == "reward_asc":
            rows.sort(key=lambda r: (r.get("reward", 0.0), r.get("task_id", "")))
        elif sort_mode == "reward_desc":
            rows.sort(key=lambda r: (-r.get("reward", 0.0), r.get("task_id", "")))
        else:
            raise ValueError(f"unknown --sort mode: {sort_mode}")

        # Restrict to tasks that still exist on disk for this app — otherwise
        # run_single_task would have nothing to load.
        on_disk_ids = {t["id"] for t in load_tasks(app)}
        picked: list[tuple[str, str]] = []
        for r in rows:
            tid = r.get("task_id")
            if tid in on_disk_ids:
                picked.append((app, tid))
            if len(picked) >= tasks_per_app:
                break

        if not picked:
            print(f"  [warn] no usable tasks left for app '{app}' (all source "
                  f"tasks missing from disk?), skipping")
            continue

        if len(picked) < tasks_per_app:
            print(f"  [info] app '{app}': only {len(picked)} task(s) available "
                  f"(requested {tasks_per_app})")

        plan.extend(picked)

    return plan


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Re-run the per-app task picks from a previous eval run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Source / picking
    parser.add_argument("--source-run", required=True,
                        help="Run ID under evaluation/runs/ (e.g. "
                             "'bltcy-gpt-5.4_20260423_005550') or an explicit "
                             "path to a run directory.")
    parser.add_argument("--tasks-per-app", type=int, default=5, metavar="N",
                        help="Pick at most N tasks per app from the source run "
                             "(default: 5).")
    parser.add_argument("--app", type=str, action="append", dest="apps",
                        help="Restrict to these apps (repeat for multiple). "
                             "Default: every app present in the source run.")
    parser.add_argument("--skip-app", type=str, action="append", dest="skip_apps",
                        default=[],
                        help="Drop these apps from the plan (repeat for multiple).")
    parser.add_argument("--only-failed", action="store_true",
                        help="Only consider source tasks with reward < 1.0.")
    parser.add_argument("--only-passed", action="store_true",
                        help="Only consider source tasks with reward == 1.0.")
    parser.add_argument("--include-errors", action="store_true",
                        help="Include source tasks that errored. Default: skip them.")
    parser.add_argument("--sort", default="id",
                        choices=["id", "source_order", "source_order_rev",
                                 "reward_asc", "reward_desc"],
                        help="How to order tasks within an app before picking N "
                             "(default: id).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the picked plan and exit without running anything.")

    # Run-time / mirror of run_eval.py
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help=f"Model alias (default: {DEFAULT_MODEL}). "
                             "Use --list-models to see registered aliases.")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS,
                        help=f"Max agent steps per task (default: {DEFAULT_MAX_ITERATIONS})")
    parser.add_argument("--sandbox-timeout", type=int, default=DEFAULT_SANDBOX_TIMEOUT,
                        help=f"Sandbox timeout in seconds (default: {DEFAULT_SANDBOX_TIMEOUT})")
    parser.add_argument("--parallel", type=int, default=1, metavar="N",
                        help="Run N tasks in parallel (default: 1).")
    parser.add_argument("--keep-alive", action="store_true",
                        help="Keep the sandbox alive after each task (interactive).")
    parser.add_argument("--resume", type=str, metavar="RUN_ID",
                        help="Resume an existing run dir under evaluation/runs/, "
                             "skipping tasks already completed there.")
    parser.add_argument("--run-dir", type=str,
                        help="Save results into this existing run directory.")
    parser.add_argument("--list-models", action="store_true",
                        help="List registered model aliases and exit.")

    # Endpoint forwarding (mirrors run_eval.py)
    parser.add_argument("--e2b-api-key", type=str,
                        help="Override E2B_API_KEY for this run.")
    parser.add_argument("--endpoint-port", type=int, metavar="PORT",
                        help="Local OpenAI-compatible endpoint port "
                             "(sets OPENAI_BASE_URL=http://localhost:<PORT>/v1).")
    parser.add_argument("--endpoint-url", type=str, metavar="URL",
                        help="Full URL for an OpenAI-compatible endpoint "
                             "(sets OPENAI_BASE_URL). Overrides --endpoint-port.")

    args = parser.parse_args()

    if args.list_models:
        print("Available models:")
        for m in list_models():
            print(f"  {m}")
        return

    if args.only_failed and args.only_passed:
        print("--only-failed and --only-passed are mutually exclusive.")
        sys.exit(1)

    if args.e2b_api_key:
        os.environ["E2B_API_KEY"] = args.e2b_api_key

    if args.endpoint_url:
        os.environ["OPENAI_BASE_URL"] = args.endpoint_url
        print(f"Using endpoint: {args.endpoint_url}")
    elif args.endpoint_port:
        endpoint = f"http://localhost:{args.endpoint_port}/v1"
        os.environ["OPENAI_BASE_URL"] = endpoint
        print(f"Using endpoint: {endpoint}")

    # ── Load the source run ──
    source_dir = _resolve_source_run(args.source_run)
    print(f"Source run: {source_dir}")
    raw_results = _load_source_results(source_dir)
    if not raw_results:
        print(f"No usable results found in {source_dir}.")
        sys.exit(1)
    print(f"  {len(raw_results)} total task results in source run")

    filtered = _filter_results(
        raw_results,
        only_failed=args.only_failed,
        only_passed=args.only_passed,
        skip_errors=not args.include_errors,
    )
    print(f"  {len(filtered)} after filters "
          f"(only_failed={args.only_failed}, only_passed={args.only_passed}, "
          f"skip_errors={not args.include_errors})")

    # ── Build the per-app picking plan ──
    skip_apps = set(args.skip_apps or [])
    available_apps = set(APP_CONFIGS.keys())
    plan = _pick_tasks_per_app(
        source_results=filtered,
        available_apps=available_apps,
        tasks_per_app=args.tasks_per_app,
        apps_filter=args.apps,
        skip_apps=skip_apps,
        sort_mode=args.sort,
    )
    if not plan:
        print("No tasks selected — nothing to do.")
        sys.exit(0)

    by_app_plan: dict[str, list[str]] = defaultdict(list)
    for app, tid in plan:
        by_app_plan[app].append(tid)

    print(f"\nPlan: {len(plan)} tasks across {len(by_app_plan)} apps")
    for app in sorted(by_app_plan.keys()):
        ids = by_app_plan[app]
        print(f"  [{app}] {len(ids)}: {', '.join(ids)}")

    if args.dry_run:
        print("\n--dry-run set, exiting without executing.")
        return

    # ── Set up the destination run dir (mirrors run_eval.py) ──
    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        completed = get_completed_tasks(run_dir)
        existing_results = load_existing_results(run_dir)
    elif args.resume:
        run_dir = EVAL_DIR / "runs" / args.resume
        if not run_dir.exists():
            print(f"Resume run directory not found: {run_dir}")
            sys.exit(1)
        completed = get_completed_tasks(run_dir)
        existing_results = load_existing_results(run_dir)
        print(f"Resuming run {args.resume} — {len(completed)} tasks already done")
    else:
        run_id = f"{args.model}_from_{source_dir.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = EVAL_DIR / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        completed = set()
        existing_results = []

    apps_to_run = sorted(by_app_plan.keys())

    run_config = {
        "model": args.model,
        "apps": apps_to_run,
        "max_iterations": args.max_iterations,
        "sandbox_timeout": args.sandbox_timeout,
        "parallel": args.parallel,
        "tasks_per_app": args.tasks_per_app,
        "source_run": source_dir.name,
        "source_run_path": str(source_dir),
        "filters": {
            "only_failed": args.only_failed,
            "only_passed": args.only_passed,
            "skip_errors": not args.include_errors,
            "sort": args.sort,
            "apps": args.apps,
            "skip_apps": sorted(skip_apps),
        },
        "planned_tasks": {app: list(ids) for app, ids in by_app_plan.items()},
        "started": datetime.now().isoformat(),
    }
    with open(run_dir / "config.json", "w") as f:
        json.dump(run_config, f, indent=2)

    # ── Build the executable task queue ──
    # We need the full task dicts (not just task_ids) for run_single_task.
    task_queue: list[tuple[str, dict]] = []
    for app in apps_to_run:
        wanted = set(by_app_plan[app])
        on_disk = {t["id"]: t for t in load_tasks(app)}
        for tid in by_app_plan[app]:  # preserve plan order
            if tid in completed:
                continue
            t = on_disk.get(tid)
            if t is None:
                print(f"  [warn] {app}/{tid} disappeared from disk, skipping")
                continue
            task_queue.append((app, t))

    total = len(task_queue) + len(completed)
    parallel = max(1, args.parallel)
    print(f"\nEvaluation: {len(task_queue)} tasks to run "
          f"({len(completed)} already done, {total} total)")
    print(f"Model: {args.model}")
    print(f"Parallel: {parallel}")
    print(f"Run dir: {run_dir}\n")

    # ── Execute (same shape as run_eval.py) ──
    all_results = list(existing_results)
    results_lock = threading.Lock()
    counter = {"done": len(existing_results)}

    def _run_one(app, task):
        with results_lock:
            counter["done"] += 1
            idx = counter["done"]
        print(f"\n[{idx}/{total}] Starting {task['id']}...")
        result = run_single_task(
            app, task, args.model, run_dir,
            args.max_iterations, args.sandbox_timeout,
            keep_alive=args.keep_alive,
        )
        with results_lock:
            all_results.append(result)
            with open(run_dir / "results.jsonl", "a") as f:
                f.write(json.dumps(result, default=str) + "\n")
        return result

    if parallel == 1:
        for app, task in task_queue:
            _run_one(app, task)
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(_run_one, app, task): task["id"]
                for app, task in task_queue
            }
            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    result = future.result()
                    status = "PASS" if result["reward"] == 1.0 else f"reward={result['reward']:.2f}"
                    print(f"  >> Completed {task_id}: {status}")
                except Exception as e:
                    print(f"  >> EXCEPTION {task_id}: {e}")

    # ── Dedup + final report (same shape as run_eval.py) ──
    seen = {}
    for r in all_results:
        seen[r["task_id"]] = r
    deduped = list(seen.values())
    with open(run_dir / "results.jsonl", "w") as f:
        for r in deduped:
            f.write(json.dumps(r, default=str) + "\n")

    if deduped:
        generate_report(deduped, run_dir, args.model, apps_to_run)


if __name__ == "__main__":
    main()
