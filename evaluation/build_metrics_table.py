#!/usr/bin/env python3
"""Build the model-comparison table.

Computes Avg. Steps, Time/Step, Token/Task, and Cost/Task per run by reading
results.jsonl plus per-step raw_responses (where token usage is recorded).

Token usage schemas supported:
- claude  : usage.input_tokens / usage.output_tokens
- openai  : usage.input_tokens / usage.output_tokens
- gemini  : usage_metadata.prompt_token_count / candidates_token_count
            (+ thoughts_token_count counted as output reasoning)
- (others): no token data stored in raw_responses; reported as N/A.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
RUNS_ROOT = Path(__file__).resolve().parent / "runs"

# label -> (run_path_relative, schema, price_in_per_M, price_out_per_M)
# price set to None when model is open source / unknown.
MODELS = [
    (
        "GPT-5.4",
        "bltcy-gpt-5.4_20260423_005550",
        "openai",
        1.25,
        10.00,
    ),
    (
        "Claude-Sonnet-4.6",
        "bltcy-claude-sonnet-4-6_from_bltcy-gpt-5.4_20260423_005550_20260424_164637",
        "claude",
        3.00,
        15.00,
    ),
    (
        "Kimi-K2.6",
        "kimi-k2.6_from_bltcy-gpt-5.4_20260423_005550_20260423_185033",
        "none",
        None,
        None,
    ),
    (
        "Qwen-3.5-27B",
        "Qwen/Qwen3.5-27B_20260414_231544",
        "none",
        None,
        None,
    ),
    (
        "Gemini-3-Flash",
        "gemini-3-flash_20260422_003723",
        "gemini",
        0.30,
        2.50,
    ),
    (
        "EvoCUA-8B",
        "evocua-s2_20260412_012441",
        "none",
        None,
        None,
    ),
    (
        "Qwen-3.5-9B",
        "Qwen/Qwen3.5-9B_20260421_224627",
        "none",
        None,
        None,
    ),
    (
        "GUI-OWL-1.5-8B",
        None,  # no run available in this workspace
        "none",
        None,
        None,
    ),
]


# ----------------------------------------------------------------------------
# Token extraction
# ----------------------------------------------------------------------------
def step_tokens(data: dict, schema: str) -> tuple[int, int] | None:
    if schema == "claude":
        u = data.get("usage")
        if not isinstance(u, dict):
            return None
        i = int(u.get("input_tokens", 0) or 0)
        o = int(u.get("output_tokens", 0) or 0)
        return i, o
    if schema == "openai":
        u = data.get("usage")
        if not isinstance(u, dict):
            return None
        i = int(u.get("input_tokens", 0) or 0)
        o = int(u.get("output_tokens", 0) or 0)
        return i, o
    if schema == "gemini":
        u = data.get("usage_metadata")
        if not isinstance(u, dict):
            return None
        i = int(u.get("prompt_token_count", 0) or 0)
        o = int(u.get("candidates_token_count", 0) or 0)
        # include reasoning ("thoughts") as output tokens
        o += int(u.get("thoughts_token_count", 0) or 0)
        return i, o
    return None


def collect_run_metrics(run_dir: Path, schema: str) -> dict:
    results_path = run_dir / "results.jsonl"
    n_tasks = 0
    sum_steps = 0
    sum_secs = 0.0
    with results_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_tasks += 1
            sum_steps += int(r.get("agent_steps", 0) or 0)
            sum_secs += float(r.get("elapsed_seconds", 0) or 0)

    in_tok = 0
    out_tok = 0
    tok_tasks = 0
    if schema != "none":
        traj_root = run_dir / "trajectories"
        for task_dir in sorted(traj_root.iterdir()):
            if not task_dir.is_dir():
                continue
            raw_dir = task_dir / "raw_responses"
            if not raw_dir.exists():
                continue
            task_in = task_out = 0
            counted = False
            for step_file in sorted(raw_dir.glob("step_*.json")):
                try:
                    with step_file.open() as f:
                        sdata = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue
                tok = step_tokens(sdata, schema)
                if tok is None:
                    continue
                ti, to = tok
                task_in += ti
                task_out += to
                counted = True
            if counted:
                in_tok += task_in
                out_tok += task_out
                tok_tasks += 1

    return {
        "n_tasks": n_tasks,
        "sum_steps": sum_steps,
        "sum_secs": sum_secs,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "tok_tasks": tok_tasks,
    }


def fmt_tok(x: float) -> str:
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}M"
    if x >= 1_000:
        return f"{x/1_000:.1f}k"
    return f"{x:.0f}"


def fmt_cost(x: float) -> str:
    if x < 0.01:
        return f"${x:.4f}"
    if x < 1:
        return f"${x:.3f}"
    return f"${x:.2f}"


def main() -> int:
    rows = []
    for label, rel, schema, p_in, p_out in MODELS:
        if rel is None:
            rows.append((label, None, schema, p_in, p_out, None))
            continue
        run_dir = RUNS_ROOT / rel
        if not run_dir.exists():
            print(f"[warn] run not found: {run_dir}", file=sys.stderr)
            rows.append((label, run_dir, schema, p_in, p_out, None))
            continue
        m = collect_run_metrics(run_dir, schema)
        rows.append((label, run_dir, schema, p_in, p_out, m))

    print()
    header = f"{'Model':<18} {'N':>4}  {'Avg Steps':>10}  {'Time/Task (s)':>14}  {'Time/Step (s)':>14}  {'In tok/task':>12}  {'Out tok/task':>13}  {'Tok/Task':>10}  {'Cost/Task':>10}"
    print(header)
    print("-" * len(header))

    table_rows = []
    for label, run_dir, schema, p_in, p_out, m in rows:
        if m is None:
            print(
                f"{label:<18} {'-':>4}  {'-':>10}  {'-':>14}  {'-':>14}  {'-':>12}  {'-':>13}  {'-':>10}  {'-':>10}"
            )
            table_rows.append({"model": label, "available": False})
            continue
        n = m["n_tasks"]
        avg_steps = m["sum_steps"] / max(n, 1)
        avg_time = m["sum_secs"] / max(n, 1)
        time_per_step = m["sum_secs"] / max(m["sum_steps"], 1)

        if m["tok_tasks"] > 0:
            in_per_task = m["in_tok"] / m["tok_tasks"]
            out_per_task = m["out_tok"] / m["tok_tasks"]
            tok_per_task = in_per_task + out_per_task
            tok_per_task_str = fmt_tok(tok_per_task)
            in_str = fmt_tok(in_per_task)
            out_str = fmt_tok(out_per_task)
        else:
            in_per_task = out_per_task = tok_per_task = None
            tok_per_task_str = "N/A"
            in_str = "N/A"
            out_str = "N/A"

        if (
            tok_per_task is not None
            and p_in is not None
            and p_out is not None
        ):
            cost_per_task = (
                in_per_task * p_in + out_per_task * p_out
            ) / 1_000_000
            cost_str = fmt_cost(cost_per_task)
        else:
            cost_per_task = None
            cost_str = "N/A"

        print(
            f"{label:<18} {n:>4}  {avg_steps:>10.2f}  {avg_time:>14.2f}  {time_per_step:>14.2f}  "
            f"{in_str:>12}  {out_str:>13}  {tok_per_task_str:>10}  {cost_str:>10}"
        )
        table_rows.append(
            {
                "model": label,
                "available": True,
                "n_tasks": n,
                "avg_steps": avg_steps,
                "avg_time_s": avg_time,
                "time_per_step_s": time_per_step,
                "tasks_with_token_data": m["tok_tasks"],
                "input_tokens_per_task": in_per_task,
                "output_tokens_per_task": out_per_task,
                "total_tokens_per_task": tok_per_task,
                "cost_per_task_usd": cost_per_task,
                "price_in_per_M": p_in,
                "price_out_per_M": p_out,
            }
        )

    out_path = Path(__file__).resolve().parent / "metrics_table.json"
    out_path.write_text(json.dumps(table_rows, indent=2))
    print()
    print(f"Saved JSON: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
