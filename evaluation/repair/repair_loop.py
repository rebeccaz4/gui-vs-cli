#!/usr/bin/env python3
"""
Iterative verifier-script repair pipeline.

One persistent desktop environment per task. The agent runs once, an LLM judge produces
a ground-truth verdict from the trajectory, then the verifier script is run
against the live sandbox and compared to the judge. On disagreement, a headless
Claude Code invocation edits the task's verification commands and/or the
verifier module. Re-verify. Repeat up to --max-rounds.

All reasoning stages (judge, comparator, repair) are headless `claude -p`
subprocess calls; this file only wires them together and owns the sandbox.

Assumptions:
- The verifier module is idempotent, so re-running verification against the
  same post-agent sandbox state is safe (no snapshot/restore).
- Only one task per run. Run multiple tasks by calling this script N times.

Usage:
    # --app is optional; auto-detected from task.json["app"]
    python evaluation/repair/repair_loop.py --task blender_animated_object
    python evaluation/repair/repair_loop.py --task calc_class_roster_grade_band \
        --max-rounds 3 --max-iterations 50

    # List every app the repair loop supports
    python evaluation/repair/repair_loop.py --list-apps
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    import dotenv
except ModuleNotFoundError:
    dotenv = None

if dotenv is not None:
    dotenv.load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────

REPAIR_DIR = Path(__file__).parent
EVAL_DIR = REPAIR_DIR.parent
PROJECT_ROOT = EVAL_DIR.parent
TASK_GEN_DIR = PROJECT_ROOT / "task_generator"
VERIFIERS_DIR = PROJECT_ROOT / "verifiers"

PROMPTS_DIR = REPAIR_DIR / "prompts"
RUNS_DIR = REPAIR_DIR / "runs"

sys.path.insert(0, str(PROJECT_ROOT))

from computer_env import (
    DEFAULT_DOCKER_CPUS,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_MEMORY,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_DOCKER_READY_TIMEOUT,
    DEFAULT_DOCKER_SHM_SIZE,
    DEFAULT_ENV_BACKEND,
    ensure_backend_support,
)

from evaluation.apps.registry import get_app_spec, list_app_ids  # noqa: E402
from evaluation.apps.save import auto_save_app  # noqa: E402
from evaluation.runtime.agent_runner import run_agent_on_task  # noqa: E402
from evaluation.runtime.sandbox_session import setup_sandbox, upload_verifier  # noqa: E402
from evaluation.runtime.verification import run_verifier  # noqa: E402

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_MODEL = os.getenv("REPAIR_MODEL", "kimi-k2.6")
DEFAULT_MAX_ITERATIONS = int(os.getenv("REPAIR_MAX_ITERATIONS", "100"))
DEFAULT_MAX_ROUNDS = int(os.getenv("REPAIR_MAX_ROUNDS", "4"))
DEFAULT_SANDBOX_TIMEOUT = int(os.getenv("REPAIR_SANDBOX_TIMEOUT", "200"))

# Headless reasoning backends. Both are invoked with YOLO-mode flags so every
# stage has unrestricted tool access. Selected at CLI time via --backend.
BACKENDS = {
    "claude": {
        "bin_env": "CLAUDE_BIN",
        "default_bin": "claude",
        # `claude -p "<prompt>"` is non-interactive headless mode.
        "build_argv": lambda binary, prompt: [
            binary, "--dangerously-skip-permissions", "-p", prompt,
        ],
    },
    "codex": {
        "bin_env": "CODEX_BIN",
        "default_bin": "codex",
        # `codex exec "<prompt>"` is non-interactive headless mode.
        "build_argv": lambda binary, prompt: [
            binary, "exec", "--dangerously-bypass-approvals-and-sandbox", prompt,
        ],
    },
}
DEFAULT_BACKEND = os.getenv("REPAIR_BACKEND", "claude")

# Populated by main() before the pipeline runs.
_ACTIVE_BACKEND = DEFAULT_BACKEND


def _resolve_backend(name):
    if name not in BACKENDS:
        raise ValueError(f"Unknown backend: {name}. Choose from {list(BACKENDS)}")
    cfg = BACKENDS[name]
    binary = os.getenv(cfg["bin_env"], cfg["default_bin"])
    return name, binary, cfg["build_argv"]


# ── Task / verifier helpers ──────────────────────────────────────────────────


def load_task(task_id):
    task_path = TASK_GEN_DIR / "tasks" / task_id / "task.json"
    if not task_path.exists():
        raise FileNotFoundError(f"Task file not found: {task_path}")
    with open(task_path) as f:
        return json.load(f), task_path


def upload_verifier_script(sandbox, app_name):
    """Re-upload the verifier script to the sandbox after a repair edit."""
    upload_verifier(sandbox, app_name)


def run_verifier_batch(sandbox, app_name, checks):
    """Run every verification command once against the live sandbox.

    Returns a list of per-check result dicts, in the same order as `checks`.
    LLM-judged entries are not adjudicated here (passed=None); the script side
    cannot decide them, so the comparator will skip them.
    """
    results = []
    for i, check in enumerate(checks):
        cmd = check.get("command")
        description = check.get("description", cmd or f"check {i}")

        if check.get("judge") == "llm":
            data = run_verifier(sandbox, app_name, cmd) if cmd else None
            results.append({
                "index": i,
                "description": description,
                "mode": "llm_judge",
                "command": cmd,
                "prompt": check.get("prompt"),
                "raw_output": data,
                "passed": None,
            })
            continue

        data = run_verifier(sandbox, app_name, cmd)
        entry = {
            "index": i,
            "description": description,
            "command": cmd,
            "raw_output": data,
        }
        if "eval" in check:
            entry["mode"] = "eval"
            entry["eval_expr"] = check["eval"]
            try:
                result = data  # noqa: F841 -- referenced by eval expression
                entry["passed"] = bool(eval(check["eval"]))  # noqa: S307
            except Exception as e:
                entry["passed"] = False
                entry["error"] = f"eval failed: {e}"
        else:
            key = check.get("key")
            expected = check.get("expected")
            actual = data.get(key) if isinstance(data, dict) else None
            entry["mode"] = "key"
            entry["key"] = key
            entry["expected"] = expected
            entry["actual"] = actual
            entry["passed"] = actual == expected
        results.append(entry)
    return results


def summarize_script_results(script_results):
    passed = sum(1 for r in script_results if r.get("passed") is True)
    failed = sum(1 for r in script_results if r.get("passed") is False)
    skipped = sum(1 for r in script_results if r.get("passed") is None)
    return {
        "passed": passed,
        "failed": failed,
        "skipped_llm_judge": skipped,
        "total": len(script_results),
    }


def compute_divergences(script_results, llm_judge_result):
    """Mechanical comparison of script vs judge, keyed by index.

    Does NOT touch LLM-judged entries (script cannot decide them). The
    comparator stage below does the interpretive work; this is just a cheap
    early-exit signal and a summary for the SOLVED.md log.
    """
    judge_by_index = {}
    for entry in llm_judge_result.get("checks", []):
        idx = entry.get("index")
        if idx is None:
            continue
        judge_by_index[idx] = entry

    diffs = []
    for r in script_results:
        if r.get("passed") is None:
            continue  # llm-judged — not a script call
        i = r["index"]
        judge = judge_by_index.get(i)
        if judge is None:
            diffs.append({
                "index": i,
                "description": r.get("description"),
                "script_passed": r.get("passed"),
                "judge_passed": None,
                "judge_reason": "no_judge_entry_for_this_index",
            })
            continue
        if bool(r.get("passed")) != bool(judge.get("passed")):
            diffs.append({
                "index": i,
                "description": r.get("description"),
                "script_passed": r.get("passed"),
                "judge_passed": judge.get("passed"),
                "judge_reason": judge.get("reasoning", ""),
            })
    return diffs


# ── Headless Claude Code invocation ──────────────────────────────────────────


def render_prompt(template_name, substitutions):
    template = (PROMPTS_DIR / template_name).read_text()
    for key, value in substitutions.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def call_claude_code(prompt_text, working_dir, timeout, log_path):
    """Invoke the active headless reasoning backend (claude or codex).

    Writes the prompt, stdout, and stderr to `log_path` so runs are auditable.
    Returns (stdout, stderr, returncode).
    """
    backend_name, binary, build_argv = _resolve_backend(_ACTIVE_BACKEND)
    cmd = build_argv(binary, prompt_text)
    label = log_path.stem if log_path else "cc"
    print(f"    [{label}] headless {backend_name} (unrestricted tools)")
    start = time.time()
    try:
        r = subprocess.run(
            cmd,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout, stderr, rc = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) \
            + f"\n[TIMEOUT after {timeout}s]"
        rc = 124
    elapsed = time.time() - start
    print(f"    [{label}] rc={rc} in {elapsed:.1f}s")

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# returncode: {rc}\n# elapsed: {elapsed:.1f}s\n"
            f"# cwd: {working_dir}\n"
            f"# backend: {backend_name}\n"
            f"# argv: {cmd[:-1] + ['<prompt omitted — see PROMPT section below>']}\n\n"
            f"## PROMPT\n{prompt_text}\n\n"
            f"## STDOUT\n{stdout}\n\n"
            f"## STDERR\n{stderr}\n"
        )
    return stdout, stderr, rc


# ── Pipeline stages ──────────────────────────────────────────────────────────


def stage_judge(task_id, app_name, task_dict, traj_dir, round_dir):
    """Stage B — LLM-as-judge. Produces round_dir/llm_judge.json."""
    out_path = round_dir / "llm_judge.json"
    criteria = [
        {
            "index": i,
            "description": c.get("description", ""),
            "llm_judged": c.get("judge") == "llm",
            "prompt": c.get("prompt"),
        }
        for i, c in enumerate(task_dict["verification"])
    ]
    prompt = render_prompt("judge.md", {
        "TASK_ID": task_id,
        "APP_NAME": app_name,
        "TASK_DESCRIPTION": task_dict["task"],
        "TRAJECTORY_DIR": str(traj_dir),
        "CRITERIA_JSON": json.dumps(criteria, indent=2),
        "OUTPUT_PATH": str(out_path),
        "LLM_JUDGE_GUIDE": str(EVAL_DIR / "llm_judge.md"),
    })
    stdout, stderr, rc = call_claude_code(
        prompt, PROJECT_ROOT,
        timeout=1800, log_path=round_dir / "judge_cc.log",
    )
    if not out_path.exists():
        raise RuntimeError(
            f"Judge stage did not produce {out_path} (rc={rc}).\n"
            f"stderr tail: {stderr[-800:]}"
        )
    return json.loads(out_path.read_text())


def stage_comparator(task_id, app_name, task_path, script_result_path,
                     llm_judge_path, traj_dir, round_dir):
    """Stage D — classify disagreements. Produces round_dir/disagreements.json."""
    out_path = round_dir / "disagreements.json"
    prompt = render_prompt("comparator.md", {
        "TASK_ID": task_id,
        "APP_NAME": app_name,
        "TASK_PATH": str(task_path),
        "SCRIPT_RESULT_PATH": str(script_result_path),
        "LLM_JUDGE_PATH": str(llm_judge_path),
        "TRAJECTORY_DIR": str(traj_dir),
        "VERIFIER_PATH": str(VERIFIERS_DIR / app_name / f"{app_name}.py"),
        "VERIFIER_README": str(VERIFIERS_DIR / app_name / "README.md"),
        "OUTPUT_PATH": str(out_path),
    })
    stdout, stderr, rc = call_claude_code(
        prompt, PROJECT_ROOT,
        timeout=1200, log_path=round_dir / "comparator_cc.log",
    )
    if not out_path.exists():
        raise RuntimeError(
            f"Comparator stage did not produce {out_path} (rc={rc}).\n"
            f"stderr tail: {stderr[-800:]}"
        )
    return json.loads(out_path.read_text())


def stage_repair(task_id, app_name, task_path, disagreements_path, round_dir,
                 round_num):
    """Stage E — edit verifier / task.json to fix divergences.

    Returns the markdown log contents the repair agent wrote, or stdout
    fallback if it failed to write one.
    """
    log_path = round_dir / "repair_log.md"
    task_dir = task_path.parent
    prompt = render_prompt("repair.md", {
        "TASK_ID": task_id,
        "APP_NAME": app_name,
        "ROUND_NUM": round_num,
        "TASK_PATH": str(task_path),
        "TASK_DIR": str(task_dir),
        "VERIFIER_PATH": str(VERIFIERS_DIR / app_name / f"{app_name}.py"),
        "VERIFIER_README": str(VERIFIERS_DIR / app_name / "README.md"),
        "DISAGREEMENTS_PATH": str(disagreements_path),
        "REPAIR_LOG_PATH": str(log_path),
        "LESSONS_PATH": str(TASK_GEN_DIR / "LESSONS.md"),
    })
    stdout, stderr, rc = call_claude_code(
        prompt, PROJECT_ROOT,
        timeout=1800, log_path=round_dir / "repair_cc.log",
    )
    if log_path.exists():
        return log_path.read_text()
    # Fallback — repair agent didn't write the structured log
    return f"(no repair_log.md produced; stdout tail)\n\n{stdout[-2000:]}"


# ── SOLVED.md writer ─────────────────────────────────────────────────────────


def write_solved_md(run_dir, task_id, app_name, task_path, agent_info,
                    initial_criteria_count, rounds_info, final_diffs,
                    llm_judge_result):
    lines = []
    lines.append(f"# Repair Report — `{task_id}`")
    lines.append("")
    lines.append(f"- **App:** `{app_name}`")
    lines.append(f"- **Task file:** `{task_path}`")
    lines.append(f"- **Agent:** `{agent_info['model']}` — "
                 f"{'done' if agent_info['agent_done'] else 'not done'} "
                 f"in {agent_info['steps']} steps")
    lines.append(f"- **Initial criteria count:** {initial_criteria_count}")
    lines.append(f"- **Rounds run:** {len(rounds_info)}")
    stopped_judge_wrong = bool(rounds_info) and rounds_info[-1].get("all_judge_wrong")
    if not final_diffs and stopped_judge_wrong:
        lines.append("- **Final state:** ✅ verifier script trusted — "
                     "all remaining divergences were classified `judge_wrong`")
    elif not final_diffs:
        lines.append("- **Final state:** ✅ verifier script agrees with LLM judge on all criteria")
    else:
        lines.append(f"- **Final state:** ⚠️ {len(final_diffs)} criteria still divergent")
    lines.append("")

    lines.append("## LLM judge (ground truth)")
    for c in llm_judge_result.get("checks", []):
        mark = "✅" if c.get("passed") else "❌"
        lines.append(f"- {mark} #{c.get('index')} — {c.get('description', '')}")
        if c.get("reasoning"):
            lines.append(f"  - reasoning: {c['reasoning'][:300]}")
    if llm_judge_result.get("summary"):
        lines.append("")
        lines.append(f"> {llm_judge_result['summary']}")
    lines.append("")

    lines.append("## Round-by-round")
    for info in rounds_info:
        lines.append("")
        lines.append(f"### Round {info['round']}")
        s = info["script_summary"]
        lines.append(
            f"- Script: **{s['passed']}** pass / **{s['failed']}** fail / "
            f"**{s['skipped_llm_judge']}** llm-judged — total {s['total']}"
        )
        lines.append(f"- Divergences vs judge: **{len(info['diffs'])}**")
        for d in info["diffs"]:
            lines.append(
                f"  - #{d['index']} — {d.get('description', '')}: "
                f"script=`{d.get('script_passed')}` judge=`{d.get('judge_passed')}`"
            )
            if d.get("judge_reason"):
                lines.append(f"    - judge: {d['judge_reason'][:220]}")
        if info.get("disagreement_items"):
            lines.append("")
            lines.append("  **Comparator classifications:**")
            for item in info["disagreement_items"]:
                lines.append(
                    f"  - #{item.get('index')} → `{item.get('classification')}` "
                    f"(fix scope: `{item.get('fix_scope')}`)"
                )
                if item.get("suggested_fix"):
                    lines.append(f"    - fix: {item['suggested_fix'][:300]}")
        if info.get("repair_summary"):
            lines.append("")
            lines.append("<details><summary>Repair log</summary>")
            lines.append("")
            lines.append(info["repair_summary"])
            lines.append("")
            lines.append("</details>")

    lines.append("")
    lines.append("## Final state")
    if not final_diffs and stopped_judge_wrong:
        lines.append(
            "All remaining divergences were classified as `judge_wrong` by the comparator. "
            "The verifier script is treated as correct; all criteria are considered passed. ✅"
        )
    elif not final_diffs:
        lines.append("All criteria reconciled between verifier script and LLM judge. ✅")
    else:
        lines.append("Unresolved divergences after max rounds:")
        for d in final_diffs:
            lines.append(
                f"- #{d['index']} — {d.get('description', '')}: "
                f"script=`{d.get('script_passed')}` judge=`{d.get('judge_passed')}`"
            )

    (run_dir / "SOLVED.md").write_text("\n".join(lines))


# ── Main loop ────────────────────────────────────────────────────────────────


def repair_task(
    app_name,
    task_id,
    model_name,
    max_iterations,
    max_rounds,
    sandbox_timeout,
    env_backend=DEFAULT_ENV_BACKEND,
    docker_image=DEFAULT_DOCKER_IMAGE,
    docker_platform=DEFAULT_DOCKER_PLATFORM,
    docker_shm_size=DEFAULT_DOCKER_SHM_SIZE,
    docker_memory=DEFAULT_DOCKER_MEMORY,
    docker_cpus=DEFAULT_DOCKER_CPUS,
    docker_ready_timeout=DEFAULT_DOCKER_READY_TIMEOUT,
):
    task_dict, task_path = load_task(task_id)
    initial_criteria_count = len(task_dict["verification"])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / f"{task_id}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    traj_dir = run_dir / "trajectory"
    traj_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*72}")
    print(f"  Repair run: {task_id}")
    print(f"  App:   {app_name}")
    print(f"  Model: {model_name}")
    print(f"  Env:   {env_backend}")
    print(f"  Run:   {run_dir}")
    print(f"{'='*72}")

    sandbox = None
    agent_info = {"model": model_name, "agent_done": False, "steps": 0}
    try:
        # ── Stage A: open sandbox + run agent once ───────────────────────────
        sandbox, stream_url = setup_sandbox(
            app_name,
            task_dict,
            sandbox_timeout,
            env_backend=env_backend,
            docker_image=docker_image,
            docker_platform=docker_platform,
            docker_shm_size=docker_shm_size,
            docker_memory=docker_memory,
            docker_cpus=docker_cpus,
            docker_ready_timeout=docker_ready_timeout,
        )
        print(f"  Desktop: {stream_url}")

        print("  Running agent...")
        agent_done, steps, trajectory = run_agent_on_task(
            sandbox, task_dict["task"], model_name, max_iterations, traj_dir,
        )
        agent_info.update({"agent_done": agent_done, "steps": steps})
        print(f"  Agent done={agent_done} in {steps} steps")

        # Auto-save, mirroring run_eval.py behavior for apps that need it
        app_spec = get_app_spec(app_name)
        if app_spec.save_shortcut:
            try:
                save_result = auto_save_app(
                    sandbox,
                    app_name,
                    app_spec.save_shortcut,
                    save_window_name=app_spec.save_window_name,
                )
                if save_result["ok"]:
                    print(f"  Auto-save: {save_result['message']}")
                else:
                    print(f"  Auto-save warning: {save_result['message']}")
                    if save_result["stderr"]:
                        print(f"  Auto-save stderr: {save_result['stderr']}")
            except Exception as e:
                print(f"  Auto-save failed: {e}")

        # Persist trajectory meta alongside the screenshots the agent runner wrote
        with open(traj_dir / "trajectory.json", "w") as f:
            json.dump({
                "task_id": task_id,
                "app": app_name,
                "model": model_name,
                "task": task_dict["task"],
                "agent_done": agent_done,
                "agent_steps": steps,
                "trajectory": trajectory,
            }, f, indent=2, default=str)

        # Final-state screenshot so judge can see the end state cleanly
        try:
            (traj_dir / "screenshots").mkdir(exist_ok=True)
            with open(traj_dir / "screenshots" / "final_after_agent.png", "wb") as f:
                f.write(sandbox.screenshot())
        except Exception:
            pass

        # ── Stage B: LLM judge (once — trajectory is fixed) ──────────────────
        judge_dir = run_dir / "judge"
        judge_dir.mkdir(exist_ok=True)
        print(f"  Stage B: LLM judge (headless {_ACTIVE_BACKEND})...")
        llm_judge_result = stage_judge(task_id, app_name, task_dict, traj_dir, judge_dir)
        llm_judge_path = judge_dir / "llm_judge.json"
        judge_pass = sum(
            1 for c in llm_judge_result.get("checks", []) if c.get("passed")
        )
        judge_total = len(llm_judge_result.get("checks", []))
        print(f"  Judge: {judge_pass}/{judge_total} criteria judged passed")

        # ── Round loop: C (verify) → D (compare) → E (repair) → re-verify ──
        rounds_info = []
        final_diffs = []
        for round_num in range(max_rounds):
            round_dir = run_dir / f"round_{round_num}"
            round_dir.mkdir(parents=True, exist_ok=True)

            # Re-read task spec from disk (prior round's repair may have edited it)
            with open(task_path) as f:
                task_dict = json.load(f)

            print(f"\n  ── Round {round_num} ──")

            # Stage C: run verifier
            script_results = run_verifier_batch(
                sandbox, app_name, task_dict["verification"],
            )
            script_result_path = round_dir / "script_result.json"
            with open(script_result_path, "w") as f:
                json.dump(script_results, f, indent=2, default=str)
            summary = summarize_script_results(script_results)
            print(f"    Script: {summary['passed']}P / {summary['failed']}F / "
                  f"{summary['skipped_llm_judge']}L (total {summary['total']})")

            # Mechanical divergence scan for early-exit
            diffs = compute_divergences(script_results, llm_judge_result)
            print(f"    Divergences vs judge: {len(diffs)}")

            round_record = {
                "round": round_num,
                "script_summary": summary,
                "diffs": diffs,
                "disagreement_items": [],
                "repair_summary": "",
            }

            if not diffs:
                rounds_info.append(round_record)
                final_diffs = []
                print("    ✅ verifier agrees with judge — stopping")
                break

            # Stage D: comparator (always copy judge into round_dir for locality)
            shutil.copy(llm_judge_path, round_dir / "llm_judge.json")
            print(f"    Stage D: comparator (headless {_ACTIVE_BACKEND})...")
            disagreements = stage_comparator(
                task_id, app_name, task_path, script_result_path,
                round_dir / "llm_judge.json", traj_dir, round_dir,
            )
            round_record["disagreement_items"] = disagreements.get("items", [])
            print(f"    Comparator classified {len(round_record['disagreement_items'])} item(s)")

            # If the comparator classified every remaining divergence as `judge_wrong`,
            # the verifier script is actually correct and there is nothing to repair.
            # Treat the script as the trusted source and declare all criteria passed.
            items = round_record["disagreement_items"]
            if items and all(it.get("classification") == "judge_wrong" for it in items):
                round_record["all_judge_wrong"] = True
                rounds_info.append(round_record)
                final_diffs = []
                print("    ✅ all remaining divergences classified as judge_wrong — "
                      "trusting verifier script, stopping")
                break

            is_last_round = round_num == max_rounds - 1
            if is_last_round:
                rounds_info.append(round_record)
                final_diffs = diffs
                print("    Last round — skipping repair (would have nothing to re-verify)")
                break

            # Stage E: repair
            print(f"    Stage E: repair (headless {_ACTIVE_BACKEND})...")
            disagreements_path = round_dir / "disagreements.json"
            repair_summary = stage_repair(
                task_id, app_name, task_path, disagreements_path,
                round_dir, round_num,
            )
            round_record["repair_summary"] = repair_summary

            # Re-upload the (possibly edited) verifier so next round sees the fix
            upload_verifier_script(sandbox, app_name)

            rounds_info.append(round_record)

        # ── SOLVED.md ────────────────────────────────────────────────────────
        write_solved_md(
            run_dir, task_id, app_name, task_path, agent_info,
            initial_criteria_count, rounds_info, final_diffs, llm_judge_result,
        )
        print(f"\n  SOLVED.md: {run_dir / 'SOLVED.md'}")

        return {
            "run_dir": str(run_dir),
            "rounds": len(rounds_info),
            "final_divergences": len(final_diffs),
            "solved": len(final_diffs) == 0,
            "stopped_reason": (
                "all_judge_wrong" if (rounds_info and rounds_info[-1].get("all_judge_wrong"))
                else ("script_matches_judge" if not final_diffs else "unresolved")
            ),
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
        (run_dir / "ERROR.log").write_text(traceback.format_exc())
        raise
    finally:
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                pass


# ── CLI ──────────────────────────────────────────────────────────────────────


def _supported_apps_help():
    """Build a readable list of every app the repair loop accepts.

    The set of valid apps is exactly the keys of run_eval.APP_CONFIGS, which
    in turn covers every `app` value used by any task.json in
    task_generator/tasks/. Listing them in --help avoids forcing users to
    remember mappings like calc_* -> libreoffice_calc.
    """
    apps = list_app_ids()
    # Wrap roughly 6 per line to keep --help readable.
    lines = []
    for i in range(0, len(apps), 6):
        lines.append("    " + ", ".join(apps[i:i + 6]))
    return "Supported apps (auto-detected from task.json if --app omitted):\n" + "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Iterative verifier-script repair loop (single task, single sandbox).",
        epilog=_supported_apps_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--app", default=None,
                        help="App name (must be in the app registry). "
                             "Optional — defaults to the value of `app` in the task's task.json.")
    parser.add_argument("--task", default=None,
                        help="Task id (folder name under task_generator/tasks/, "
                             "must contain task.json). Required unless --list-apps.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Agent model alias (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS,
                        help=f"Max agent steps (default: {DEFAULT_MAX_ITERATIONS})")
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS,
                        help=f"Max repair rounds (default: {DEFAULT_MAX_ROUNDS})")
    parser.add_argument("--sandbox-timeout", type=int, default=DEFAULT_SANDBOX_TIMEOUT,
                        help=f"Sandbox timeout seconds (default: {DEFAULT_SANDBOX_TIMEOUT})")
    parser.add_argument(
        "--env-backend",
        choices=["e2b", "docker"],
        default=DEFAULT_ENV_BACKEND,
        help=f"Environment backend for the task sandbox (default: {DEFAULT_ENV_BACKEND})",
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
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=DEFAULT_BACKEND,
                        help=f"Headless reasoning backend for judge/comparator/repair stages "
                             f"(default: {DEFAULT_BACKEND}). Both run with full permissions.")
    parser.add_argument("--list-apps", action="store_true",
                        help="Print every supported app key (from APP_CONFIGS) and exit.")
    args = parser.parse_args()

    available_apps = list_app_ids()

    if args.list_apps:
        for app in available_apps:
            print(app)
        sys.exit(0)

    if not args.task:
        parser.error("--task is required (unless using --list-apps)")

    # Auto-detect the app from task.json if --app was not supplied. This frees
    # users from remembering mappings like calc_* -> libreoffice_calc.
    try:
        task_dict, _task_path = load_task(args.task)
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(1)

    task_app = task_dict.get("app")
    if not args.app:
        if not task_app:
            print(f"Task {args.task} has no `app` field in task.json; "
                  f"please pass --app explicitly.")
            print(f"Available: {', '.join(available_apps)}")
            sys.exit(1)
        args.app = task_app
        print(f"  App auto-detected from task.json: {args.app}")
    elif task_app and task_app != args.app:
        print(f"  WARNING: --app {args.app} overrides task.json app {task_app!r}")

    if args.app not in available_apps:
        print(f"Unknown app: {args.app}")
        print(f"Available: {', '.join(available_apps)}")
        sys.exit(1)
    try:
        ensure_backend_support(args.env_backend, args.app)
    except ValueError as exc:
        print(exc)
        sys.exit(1)

    global _ACTIVE_BACKEND
    _ACTIVE_BACKEND = args.backend
    backend_name, binary, _ = _resolve_backend(_ACTIVE_BACKEND)
    print(f"  Reasoning backend: {backend_name} ({binary})")

    summary = repair_task(
        args.app, args.task, args.model,
        args.max_iterations, args.max_rounds, args.sandbox_timeout,
        env_backend=args.env_backend,
        docker_image=args.docker_image,
        docker_platform=args.docker_platform,
        docker_shm_size=args.docker_shm_size,
        docker_memory=args.docker_memory,
        docker_cpus=args.docker_cpus,
        docker_ready_timeout=args.docker_ready_timeout,
    )
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
