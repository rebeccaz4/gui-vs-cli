from __future__ import annotations

import json
from pathlib import Path

from .run_config import TASKS_DIR

_tasks_dir = TASKS_DIR


def set_tasks_dir(tasks_dir: str | Path) -> None:
    global _tasks_dir
    _tasks_dir = Path(tasks_dir)


def iter_task_files():
    if not _tasks_dir.exists():
        return
    for task_dir in sorted(_tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        task_file = task_dir / "task.json"
        if not task_file.exists():
            continue
        try:
            with open(task_file) as handle:
                yield json.load(handle)
        except (json.JSONDecodeError, OSError):
            continue


def load_tasks(app_name: str) -> list[dict]:
    """Load tasks for an app.

    Note: Tasks are pre-filtered in task_generator/tasks/ directory.
    All remaining tasks have already passed CLI feasibility screening.
    """
    tasks = []
    for task in iter_task_files():
        if task.get("app") != app_name:
            continue
        tasks.append(task)

    return tasks


def select_pending_tasks(tasks: list[dict], completed: set[str], one_task_per_app: bool = False) -> list[dict]:
    pending = [task for task in tasks if task["id"] not in completed]
    if one_task_per_app:
        return pending[:1]
    return pending


def get_completed_tasks(run_dir: Path) -> set[str]:
    completed: set[str] = set()
    traj_dir = run_dir / "trajectories"
    if not traj_dir.exists():
        return completed
    for task_dir in traj_dir.iterdir():
        if not task_dir.is_dir():
            continue
        traj_file = task_dir / "trajectory.json"
        if not traj_file.exists():
            continue
        try:
            with open(traj_file) as handle:
                data = json.load(handle)
        except Exception:
            continue
        if data.get("reward") is not None:
            completed.add(data["task_id"])
    return completed


def load_existing_results(run_dir: Path) -> list[dict]:
    results: list[dict] = []
    traj_dir = run_dir / "trajectories"
    if not traj_dir.exists():
        return results
    for task_dir in sorted(traj_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        traj_file = task_dir / "trajectory.json"
        if not traj_file.exists():
            continue
        try:
            with open(traj_file) as handle:
                data = json.load(handle)
        except Exception:
            continue
        if data.get("reward") is None:
            continue
        results.append(
            {
                "task_id": data["task_id"],
                "app": data["app"],
                "model": data.get("model", ""),
                "task": data.get("task", ""),
                "agent_done": data.get("agent_done", False),
                "agent_steps": data.get("agent_steps", 0),
                "checks_passed": data.get("checks_passed", 0),
                "checks_total": data.get("checks_total", 0),
                "reward": data["reward"],
                "elapsed_seconds": data.get("elapsed_seconds", 0),
                "error": data.get("error"),
                "timestamp": data.get("timestamp", ""),
            }
        )
    return results
