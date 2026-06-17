#!/usr/bin/env python3
"""Compare two evaluation runs on the intersection of tasks.

Usage:
    python compare_runs.py <run_dir_a> <run_dir_b>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean


def load_results(run_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    results_path = run_dir / "results.jsonl"
    with results_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[rec["task_id"]] = rec
    return out


def sum_tokens_for_task(run_dir: Path, task_id: str) -> tuple[int, int, int, int]:
    """Return (input_tokens, output_tokens, total_tokens, step_files_with_usage)."""
    raw_dir = run_dir / "trajectories" / task_id / "raw_responses"
    if not raw_dir.exists():
        return 0, 0, 0, 0
    in_t = out_t = total = 0
    n = 0
    for p in sorted(raw_dir.glob("step_*.json")):
        try:
            with p.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        usage = data.get("usage")
        if not isinstance(usage, dict):
            continue
        # OpenAI shape
        if "input_tokens" in usage and "output_tokens" in usage:
            ti = int(usage.get("input_tokens", 0) or 0)
            to = int(usage.get("output_tokens", 0) or 0)
            tt = int(usage.get("total_tokens", ti + to) or (ti + to))
        else:
            ti = to = tt = 0
        in_t += ti
        out_t += to
        total += tt
        n += 1
    return in_t, out_t, total, n


def fmt_int(x: float) -> str:
    return f"{int(round(x)):,}"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    run_a = Path(sys.argv[1]).resolve()
    run_b = Path(sys.argv[2]).resolve()

    res_a = load_results(run_a)
    res_b = load_results(run_b)

    common = sorted(set(res_a) & set(res_b))
    only_a = sorted(set(res_a) - set(res_b))
    only_b = sorted(set(res_b) - set(res_a))

    model_a = next(iter(res_a.values()), {}).get("model", run_a.name)
    model_b = next(iter(res_b.values()), {}).get("model", run_b.name)

    print("=" * 80)
    print("Run A:", run_a.name)
    print("       model =", model_a, "| total tasks =", len(res_a))
    print("Run B:", run_b.name)
    print("       model =", model_b, "| total tasks =", len(res_b))
    print("-" * 80)
    print(f"Common tasks  : {len(common)}")
    print(f"Only in A     : {len(only_a)}")
    print(f"Only in B     : {len(only_b)}")
    print("=" * 80)

    if not common:
        print("No common tasks; nothing to compare.")
        return 0

    # Per-task collections
    rows = []
    a_full_pass = a_part_pass = a_steps = a_secs = 0
    b_full_pass = b_part_pass = b_secs = b_steps = 0
    a_reward_sum = b_reward_sum = 0.0
    a_checks_pass = a_checks_tot = 0
    b_checks_pass = b_checks_tot = 0
    a_in_tok = a_out_tok = a_tot_tok = 0
    b_in_tok = b_out_tok = b_tot_tok = 0
    a_tok_tasks = b_tok_tasks = 0

    for tid in common:
        ra = res_a[tid]
        rb = res_b[tid]

        a_steps += int(ra.get("agent_steps", 0) or 0)
        b_steps += int(rb.get("agent_steps", 0) or 0)
        a_secs += float(ra.get("elapsed_seconds", 0) or 0)
        b_secs += float(rb.get("elapsed_seconds", 0) or 0)
        a_reward_sum += float(ra.get("reward", 0) or 0)
        b_reward_sum += float(rb.get("reward", 0) or 0)
        a_checks_pass += int(ra.get("checks_passed", 0) or 0)
        a_checks_tot += int(ra.get("checks_total", 0) or 0)
        b_checks_pass += int(rb.get("checks_passed", 0) or 0)
        b_checks_tot += int(rb.get("checks_total", 0) or 0)

        if float(ra.get("reward", 0) or 0) >= 0.9999:
            a_full_pass += 1
        if float(ra.get("reward", 0) or 0) > 0:
            a_part_pass += 1
        if float(rb.get("reward", 0) or 0) >= 0.9999:
            b_full_pass += 1
        if float(rb.get("reward", 0) or 0) > 0:
            b_part_pass += 1

        ai, ao, at, an = sum_tokens_for_task(run_a, tid)
        bi, bo, bt, bn = sum_tokens_for_task(run_b, tid)
        if an > 0:
            a_in_tok += ai
            a_out_tok += ao
            a_tot_tok += at
            a_tok_tasks += 1
        if bn > 0:
            b_in_tok += bi
            b_out_tok += bo
            b_tot_tok += bt
            b_tok_tasks += 1

        rows.append(
            {
                "task_id": tid,
                "a_reward": float(ra.get("reward", 0) or 0),
                "b_reward": float(rb.get("reward", 0) or 0),
                "a_steps": int(ra.get("agent_steps", 0) or 0),
                "b_steps": int(rb.get("agent_steps", 0) or 0),
                "a_secs": float(ra.get("elapsed_seconds", 0) or 0),
                "b_secs": float(rb.get("elapsed_seconds", 0) or 0),
                "a_total_tokens": at,
                "b_total_tokens": bt,
            }
        )

    n = len(common)

    def section(title: str) -> None:
        print()
        print(title)
        print("-" * len(title))

    section("AGGREGATE COMPARISON ON COMMON TASKS")
    print(
        f"{'metric':<32} {'A: ' + model_a:<32} {'B: ' + model_b:<32}"
    )
    print("-" * 96)

    def line(label: str, av: str, bv: str) -> None:
        print(f"{label:<32} {av:<32} {bv:<32}")

    line(
        "Full pass (reward == 1.0)",
        f"{a_full_pass}/{n} ({100*a_full_pass/n:.1f}%)",
        f"{b_full_pass}/{n} ({100*b_full_pass/n:.1f}%)",
    )
    line(
        "Any partial credit (reward > 0)",
        f"{a_part_pass}/{n} ({100*a_part_pass/n:.1f}%)",
        f"{b_part_pass}/{n} ({100*b_part_pass/n:.1f}%)",
    )
    line(
        "Mean reward",
        f"{a_reward_sum / n:.3f}",
        f"{b_reward_sum / n:.3f}",
    )
    line(
        "Sum reward",
        f"{a_reward_sum:.2f}",
        f"{b_reward_sum:.2f}",
    )
    line(
        "Check pass rate",
        f"{a_checks_pass}/{a_checks_tot} ({100*a_checks_pass/max(a_checks_tot,1):.1f}%)",
        f"{b_checks_pass}/{b_checks_tot} ({100*b_checks_pass/max(b_checks_tot,1):.1f}%)",
    )
    line(
        "Total agent steps",
        fmt_int(a_steps),
        fmt_int(b_steps),
    )
    line(
        "Mean steps / task",
        f"{a_steps / n:.2f}",
        f"{b_steps / n:.2f}",
    )
    line(
        "Total elapsed (s)",
        fmt_int(a_secs),
        fmt_int(b_secs),
    )
    line(
        "Mean elapsed (s)",
        f"{a_secs / n:.1f}",
        f"{b_secs / n:.1f}",
    )

    section("TOKEN USAGE (sum over common tasks)")
    line(
        "Tasks w/ token data",
        f"{a_tok_tasks}/{n}",
        f"{b_tok_tasks}/{n}",
    )
    line("Input tokens (sum)", fmt_int(a_in_tok), fmt_int(b_in_tok))
    line("Output tokens (sum)", fmt_int(a_out_tok), fmt_int(b_out_tok))
    line("Total tokens (sum)", fmt_int(a_tot_tok), fmt_int(b_tot_tok))
    line(
        "Mean input tokens / task",
        fmt_int(a_in_tok / max(a_tok_tasks, 1)),
        fmt_int(b_in_tok / max(b_tok_tasks, 1)),
    )
    line(
        "Mean output tokens / task",
        fmt_int(a_out_tok / max(a_tok_tasks, 1)),
        fmt_int(b_out_tok / max(b_tok_tasks, 1)),
    )
    line(
        "Mean total tokens / task",
        fmt_int(a_tot_tok / max(a_tok_tasks, 1)),
        fmt_int(b_tot_tok / max(b_tok_tasks, 1)),
    )

    section("HEAD-TO-HEAD (full-pass on common tasks)")
    a_only = b_only = both = neither = 0
    for r in rows:
        a_pass = r["a_reward"] >= 0.9999
        b_pass = r["b_reward"] >= 0.9999
        if a_pass and b_pass:
            both += 1
        elif a_pass:
            a_only += 1
        elif b_pass:
            b_only += 1
        else:
            neither += 1
    print(f"Both fully pass        : {both}/{n}")
    print(f"Only A fully passes    : {a_only}/{n}")
    print(f"Only B fully passes    : {b_only}/{n}")
    print(f"Neither fully passes   : {neither}/{n}")

    # Per-app breakdown
    section("PER-APP BREAKDOWN (mean reward)")
    by_app: dict[str, list] = {}
    for tid in common:
        app = res_a[tid].get("app") or res_b[tid].get("app") or "?"
        by_app.setdefault(app, []).append(tid)

    print(f"{'app':<22} {'n':>3}  {'A reward':>9}  {'B reward':>9}  {'A steps':>8}  {'B steps':>8}")
    print("-" * 70)
    app_lines = []
    for app, tids in sorted(by_app.items()):
        ar = mean(float(res_a[t].get("reward", 0) or 0) for t in tids)
        br = mean(float(res_b[t].get("reward", 0) or 0) for t in tids)
        asx = mean(int(res_a[t].get("agent_steps", 0) or 0) for t in tids)
        bsx = mean(int(res_b[t].get("agent_steps", 0) or 0) for t in tids)
        app_lines.append((app, len(tids), ar, br, asx, bsx))
        print(f"{app:<22} {len(tids):>3}  {ar:>9.3f}  {br:>9.3f}  {asx:>8.2f}  {bsx:>8.2f}")

    # Save a JSON summary alongside
    summary = {
        "run_a": {"path": str(run_a), "model": model_a, "total_tasks": len(res_a)},
        "run_b": {"path": str(run_b), "model": model_b, "total_tasks": len(res_b)},
        "common_count": n,
        "only_a": only_a,
        "only_b": only_b,
        "metrics": {
            "a": {
                "full_pass": a_full_pass,
                "partial_pass": a_part_pass,
                "mean_reward": a_reward_sum / n,
                "sum_reward": a_reward_sum,
                "checks_passed": a_checks_pass,
                "checks_total": a_checks_tot,
                "total_steps": a_steps,
                "mean_steps": a_steps / n,
                "total_elapsed_s": a_secs,
                "mean_elapsed_s": a_secs / n,
                "tasks_with_token_data": a_tok_tasks,
                "input_tokens_sum": a_in_tok,
                "output_tokens_sum": a_out_tok,
                "total_tokens_sum": a_tot_tok,
            },
            "b": {
                "full_pass": b_full_pass,
                "partial_pass": b_part_pass,
                "mean_reward": b_reward_sum / n,
                "sum_reward": b_reward_sum,
                "checks_passed": b_checks_pass,
                "checks_total": b_checks_tot,
                "total_steps": b_steps,
                "mean_steps": b_steps / n,
                "total_elapsed_s": b_secs,
                "mean_elapsed_s": b_secs / n,
                "tasks_with_token_data": b_tok_tasks,
                "input_tokens_sum": b_in_tok,
                "output_tokens_sum": b_out_tok,
                "total_tokens_sum": b_tot_tok,
            },
        },
        "head_to_head": {
            "both_full_pass": both,
            "only_a_full_pass": a_only,
            "only_b_full_pass": b_only,
            "neither_full_pass": neither,
        },
        "per_app": [
            {
                "app": a,
                "n": cnt,
                "a_mean_reward": ar,
                "b_mean_reward": br,
                "a_mean_steps": asx,
                "b_mean_steps": bsx,
            }
            for (a, cnt, ar, br, asx, bsx) in app_lines
        ],
        "per_task": rows,
    }
    out_path = Path.cwd() / f"compare_{run_a.name}__VS__{run_b.name}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print()
    print(f"Saved JSON summary: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
