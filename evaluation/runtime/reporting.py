from __future__ import annotations

import json
from datetime import datetime


def generate_report(all_results, run_dir, model_name, apps_run):
    app_stats = {}
    for result in all_results:
        app_name = result["app"]
        if app_name not in app_stats:
            app_stats[app_name] = {
                "tasks": 0,
                "passed": 0,
                "total_checks": 0,
                "passed_checks": 0,
                "total_reward": 0.0,
                "total_time": 0.0,
                "total_steps": 0,
                "errors": 0,
                "full_pass": 0,
            }
        stats = app_stats[app_name]
        stats["tasks"] += 1
        stats["passed_checks"] += result["checks_passed"]
        stats["total_checks"] += result["checks_total"]
        stats["total_reward"] += result["reward"]
        stats["total_time"] += result.get("elapsed_seconds", 0)
        stats["total_steps"] += result.get("agent_steps", 0)
        if result.get("error"):
            stats["errors"] += 1
        if result["reward"] == 1.0:
            stats["full_pass"] += 1

    for app_name, stats in app_stats.items():
        stats["avg_reward"] = round(stats["total_reward"] / stats["tasks"], 4) if stats["tasks"] else 0
        stats["avg_steps"] = round(stats["total_steps"] / stats["tasks"], 1) if stats["tasks"] else 0
        stats["avg_time"] = round(stats["total_time"] / stats["tasks"], 1) if stats["tasks"] else 0
        stats["success_rate"] = round(stats["full_pass"] / stats["tasks"], 4) if stats["tasks"] else 0

    total_tasks = len(all_results)
    total_reward = sum(result["reward"] for result in all_results)
    total_full_pass = sum(1 for result in all_results if result["reward"] == 1.0)
    total_checks = sum(result["checks_total"] for result in all_results)
    total_passed_checks = sum(result["checks_passed"] for result in all_results)
    total_time = sum(result.get("elapsed_seconds", 0) for result in all_results)
    total_errors = sum(1 for result in all_results if result.get("error"))

    report = {
        "run_id": run_dir.name,
        "model": model_name,
        "apps": apps_run,
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_tasks": total_tasks,
            "full_pass": total_full_pass,
            "success_rate": round(total_full_pass / total_tasks, 4) if total_tasks else 0,
            "avg_reward": round(total_reward / total_tasks, 4) if total_tasks else 0,
            "total_checks": total_checks,
            "passed_checks": total_passed_checks,
            "check_pass_rate": round(total_passed_checks / total_checks, 4) if total_checks else 0,
            "total_time_seconds": round(total_time, 1),
            "errors": total_errors,
        },
        "per_app": {
            app_name: {
                "tasks": stats["tasks"],
                "full_pass": stats["full_pass"],
                "success_rate": stats["success_rate"],
                "avg_reward": stats["avg_reward"],
                "passed_checks": stats["passed_checks"],
                "total_checks": stats["total_checks"],
                "avg_steps": stats["avg_steps"],
                "avg_time": stats["avg_time"],
                "errors": stats["errors"],
            }
            for app_name, stats in sorted(app_stats.items())
        },
        "task_results": [
            {
                "task_id": result["task_id"],
                "app": result["app"],
                "reward": result["reward"],
                "checks": f"{result['checks_passed']}/{result['checks_total']}",
                "steps": result.get("agent_steps", 0),
                "time": result.get("elapsed_seconds", 0),
                "agent_done": result.get("agent_done", False),
                "error": result.get("error"),
            }
            for result in all_results
        ],
    }

    report_path = run_dir / "report.json"
    with open(report_path, "w") as handle:
        json.dump(report, handle, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  EVALUATION REPORT — {run_dir.name}")
    print(f"  Model: {model_name}")
    print(f"{'=' * 70}")
    print("\n  Overall:")
    print(f"    Tasks:        {total_tasks}")
    print(f"    Full pass:    {total_full_pass}/{total_tasks} ({report['summary']['success_rate']:.1%})")
    print(f"    Avg reward:   {report['summary']['avg_reward']:.4f}")
    print(f"    Checks:       {total_passed_checks}/{total_checks} ({report['summary']['check_pass_rate']:.1%})")
    print(f"    Total time:   {total_time:.0f}s")
    if total_errors:
        print(f"    Errors:       {total_errors}")

    print("\n  Per-app breakdown:")
    print(
        "    "
        f"{'App':<25s} {'Tasks':>5s} {'Pass':>5s} {'Rate':>7s} "
        f"{'Reward':>7s} {'Checks':>10s} {'Steps':>6s} {'Time':>6s}"
    )
    print(f"    {'-' * 25} {'-' * 5} {'-' * 5} {'-' * 7} {'-' * 7} {'-' * 10} {'-' * 6} {'-' * 6}")
    for app_name, stats in sorted(app_stats.items()):
        print(
            f"    {app_name:<25s} {stats['tasks']:>5d} {stats['full_pass']:>5d} "
            f"{stats['success_rate']:>6.1%} {stats['avg_reward']:>7.4f} "
            f"{stats['passed_checks']:>4d}/{stats['total_checks']:<5d} "
            f"{stats['avg_steps']:>5.1f} {stats['avg_time']:>5.0f}s"
        )

    print(f"\n  Report saved: {report_path}")
    return report
