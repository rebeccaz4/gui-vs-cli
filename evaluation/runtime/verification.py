from __future__ import annotations

import base64
import json
import os
import shlex
import time
from pathlib import Path

from computer_env.backends.base import CommandExitException

from evaluation.apps.registry import get_app_spec

from .run_config import JUDGE_MODEL, MAX_JUDGE_SCREENSHOTS

# LLM Judge API configuration
DEFAULT_JUDGE_BASE_URL = "https://api.ikuncode.cc/v1"
JUDGE_BASE_URL = os.getenv("JUDGE_BASE_URL") or os.getenv("OPENROUTER_BASE_URL", DEFAULT_JUDGE_BASE_URL)


def run_verifier(sandbox, app_name, command, timeout=30):
    app_spec = get_app_spec(app_name)
    verifier_command = f"python3 {app_spec.verifier_remote}"
    parts = shlex.split(command)
    quoted_cmd = " ".join(shlex.quote(part) for part in parts)
    try:
        result = sandbox.commands.run(f"{verifier_command} {quoted_cmd}", timeout=timeout)
        return json.loads(result.stdout)
    except CommandExitException as exc:
        try:
            return json.loads(exc.stdout)
        except Exception:
            return {"error": exc.stderr[:300]}
    except Exception as exc:
        return {"error": str(exc)}


def _load_screenshot_b64(path):
    screenshot_path = Path(path)
    if not screenshot_path.exists():
        return None
    with open(screenshot_path, "rb") as handle:
        return base64.b64encode(handle.read()).decode()


def _format_trajectory_text(trajectory):
    lines = []
    for step in trajectory:
        number = step.get("step", "?")
        reasoning = step.get("reasoning", "")
        actions = step.get("actions", [])
        action_results = step.get("action_results", [])
        lines.append(f"Step {number}:")
        if reasoning:
            lines.append(f"  Reasoning: {reasoning[:400]}")
        for action in actions:
            if isinstance(action, str):
                lines.append(f"  Action: {action[:200]}")
        for action_result in action_results:
            description = action_result.get("description", "")
            if description:
                lines.append(f"  Result: {description[:150]}")
        lines.append("")
    return "\n".join(lines)


def _parse_json_response(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return json.loads(raw)


def _llm_identify_steps(trajectory_text, criteria_descriptions):
    try:
        from openai import OpenAI
    except ImportError:
        return []

    # LLM judge uses JUDGE_API_KEY first (separate from GUI agent's OPENAI_API_KEY)
    api_key = os.getenv("JUDGE_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("    [LLM step identification failed: No API key found]")
        return []

    client = OpenAI(
        base_url=JUDGE_BASE_URL,
        api_key=api_key,
    )
    system = (
        "You are analyzing a GUI agent's execution trajectory. "
        "Given the trajectory and a list of evaluation criteria, identify which "
        "step numbers contain actions relevant to those criteria. "
        'Return ONLY a JSON object: {"relevant_steps": [1, 5, 7]}. '
        "Include steps where the agent performed actions related to the criteria. "
        "Do NOT include steps that are just navigation, waiting, or unrelated setup."
    )
    criteria_text = "\n".join(
        f"  {index + 1}. {description}" for index, description in enumerate(criteria_descriptions)
    )
    user_text = (
        f"Trajectory:\n{trajectory_text}\n\n"
        f"Criteria to evaluate:\n{criteria_text}\n\n"
        "Which step numbers are relevant?"
    )

    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            max_tokens=256,
        )
        data = _parse_json_response(response.choices[0].message.content)
        steps = data.get("relevant_steps", [])
        return [int(step) for step in steps]
    except Exception as exc:
        print(f"    [LLM step identification failed: {exc}]")
        return []


def _llm_judge_criteria(criteria, screenshots_b64, command_outputs):
    try:
        from openai import OpenAI
    except ImportError:
        return [{"passed": False, "reason": "openai package not installed"}] * len(criteria)

    # LLM judge uses JUDGE_API_KEY first (separate from GUI agent's OPENAI_API_KEY)
    api_key = os.getenv("JUDGE_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return [{"passed": False, "reason": "LLM judge error: No API key found. Set JUDGE_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY"}] * len(criteria)

    client = OpenAI(
        base_url=JUDGE_BASE_URL,
        api_key=api_key,
    )
    system = (
        "You are a verification judge for GUI automation tasks. "
        "You will see screenshots from the agent's execution showing the results "
        "of its actions, plus optionally structured data from verifier commands. "
        "For each criterion, determine if it PASSES or FAILS. "
        "Return ONLY a JSON object:\n"
        '{"results": [{"index": 0, "passed": true, "reason": "..."}, ...]}\n'
        "where index matches the criterion number (0-based)."
    )

    user_parts = []
    for label, b64 in screenshots_b64:
        user_parts.append({"type": "text", "text": f"[{label}]"})
        user_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    for index, (criterion, cmd_output) in enumerate(zip(criteria, command_outputs)):
        if cmd_output is None:
            continue
        user_parts.append(
            {
                "type": "text",
                "text": (
                    f"Verifier output for criterion {index} "
                    f"({criterion.get('description', '')}):\n"
                    f"```json\n{json.dumps(cmd_output, indent=2, default=str)}\n```"
                ),
            }
        )

    criteria_text = "Criteria to judge (answer pass/fail for each):\n"
    for index, criterion in enumerate(criteria):
        criteria_text += f"  {index}. {criterion['prompt']}\n"
    user_parts.append({"type": "text", "text": criteria_text})

    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_parts},
            ],
            max_tokens=512,
        )
        data = _parse_json_response(response.choices[0].message.content)
        verdicts = data.get("results", [])
        result_map = {verdict["index"]: verdict for verdict in verdicts if "index" in verdict}
        return [
            result_map.get(index, {"passed": False, "reason": "No verdict returned"})
            for index in range(len(criteria))
        ]
    except Exception as exc:
        return [{"passed": False, "reason": f"LLM judge error: {exc}"}] * len(criteria)


def verify_task(sandbox, app_name, checks, trajectory=None, traj_dir=None):
    time.sleep(3)

    results = [None] * len(checks)
    llm_indices = []

    for index, check in enumerate(checks):
        if check.get("judge") == "llm":
            llm_indices.append(index)
            continue

        command = check["command"]
        data = run_verifier(sandbox, app_name, command)

        if "eval" in check:
            try:
                result = data
                passed = eval(check["eval"])  # noqa: S307
            except Exception as exc:
                passed = False
                data["eval_error"] = str(exc)
            results[index] = {
                "command": command,
                "description": check.get("description", command),
                "passed": passed,
                "result": data,
            }
            continue

        key = check["key"]
        expected = check["expected"]
        actual = data.get(key)
        results[index] = {
            "command": command,
            "key": key,
            "expected": expected,
            "actual": actual,
            "passed": actual == expected,
            "result": data,
        }

    if llm_indices:
        llm_checks = [checks[index] for index in llm_indices]
        descriptions = [check.get("description", check["prompt"]) for check in llm_checks]
        screenshots_b64 = []
        relevant_steps = []

        if trajectory and traj_dir:
            screenshots_dir = Path(traj_dir) / "screenshots"
            print("    [LLM] Phase 1: identifying relevant steps...")
            trajectory_text = _format_trajectory_text(trajectory)
            relevant_steps = _llm_identify_steps(trajectory_text, descriptions)
            print(f"    [LLM] Relevant steps: {relevant_steps}")

            for step_num in relevant_steps:
                result_step = step_num + 1
                screenshot_path = screenshots_dir / f"step_{result_step:03d}.png"
                b64 = _load_screenshot_b64(screenshot_path)
                if b64:
                    screenshots_b64.append(
                        (f"After step {step_num} action (step_{result_step:03d}.png)", b64)
                    )

            if len(screenshots_b64) > MAX_JUDGE_SCREENSHOTS - 2:
                screenshots_b64 = screenshots_b64[-(MAX_JUDGE_SCREENSHOTS - 2):]

            for filename, label in (
                ("final_before_verify.png", "Final state (before verification)"),
                ("final_after_verify.png", "Final state (after verification)"),
            ):
                b64 = _load_screenshot_b64(screenshots_dir / filename)
                if b64:
                    screenshots_b64.append((label, b64))
        else:
            try:
                screenshots_b64.append(
                    ("Current desktop state", base64.b64encode(sandbox.screenshot()).decode())
                )
            except Exception:
                pass

        command_outputs = []
        for check in llm_checks:
            command = check.get("command")
            command_outputs.append(run_verifier(sandbox, app_name, command) if command else None)

        print(
            f"    [LLM] Phase 2: judging {len(llm_checks)} criteria with "
            f"{len(screenshots_b64)} screenshots..."
        )
        verdicts = _llm_judge_criteria(llm_checks, screenshots_b64, command_outputs)
        for verdict_index, result_index in enumerate(llm_indices):
            verdict = verdicts[verdict_index]
            results[result_index] = {
                "command": llm_checks[verdict_index].get("command", "(screenshots)"),
                "description": descriptions[verdict_index],
                "judge": "llm",
                "passed": bool(verdict.get("passed", False)),
                "reason": verdict.get("reason", ""),
                "relevant_steps": relevant_steps,
                "result": command_outputs[verdict_index] or {},
            }

    total = len(results)
    passed = sum(1 for result in results if result and result["passed"])
    return passed, total, results
