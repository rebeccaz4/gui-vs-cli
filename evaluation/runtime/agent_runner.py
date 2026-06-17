from __future__ import annotations

import json
import struct
import time
from datetime import datetime

from agents import create_agent

from .run_config import DISPLAY_HEIGHT, DISPLAY_WIDTH


GUI_SCREEN_ONLY_POLICY = """<GUI_SCREEN_ONLY_POLICY>
Hard requirements:
* All task-result changes must be made through the target application's visible GUI.
* Do not directly rewrite task files on disk or mutate their underlying data using Python, shell commands, scripts, automation APIs, databases, archives, config files, or external utilities.
* Editing content through the target application's own GUI is allowed.
* Opening a terminal, REPL, scripting console, developer console, or macro/script editor to execute code or commands is not allowed, even if accessed through the GUI.
</GUI_SCREEN_ONLY_POLICY>"""


def build_gui_task_prompt(task_text: str) -> str:
    return f"{GUI_SCREEN_ONLY_POLICY}\n\n<USER_TASK>\n{task_text}\n</USER_TASK>"


def run_agent_on_task(sandbox, task_text, model_name, max_iterations, traj_dir=None):
    agent = create_agent(
        model_name,
        platform="ubuntu",
        screen_size=(DISPLAY_WIDTH, DISPLAY_HEIGHT),
        max_steps=max_iterations,
    )
    agent.reset()
    task_prompt = build_gui_task_prompt(task_text)

    trajectory = []
    screenshots_dir = None
    responses_dir = None
    if traj_dir:
        screenshots_dir = traj_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        responses_dir = traj_dir / "raw_responses"
        responses_dir.mkdir(parents=True, exist_ok=True)

    for step in range(1, max_iterations + 1):
        step_record = {"step": step, "timestamp": datetime.now().isoformat()}

        screenshot_bytes = sandbox.screenshot()
        if screenshot_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", screenshot_bytes[16:24])
            step_record["screenshot_size"] = [width, height]
        obs = {"screenshot": screenshot_bytes}

        if screenshots_dir:
            with open(screenshots_dir / f"step_{step:03d}.png", "wb") as handle:
                handle.write(screenshot_bytes)
            step_record["screenshot_file"] = f"screenshots/step_{step:03d}.png"

        try:
            reasoning, actions = agent.predict(task_prompt, obs)
        except Exception as exc:
            step_record["error"] = str(exc)
            trajectory.append(step_record)
            return False, step, trajectory

        step_record["reasoning"] = reasoning
        step_record["actions"] = actions

        if responses_dir and getattr(agent, "last_raw_response", None) is not None:
            try:
                with open(responses_dir / f"step_{step:03d}.json", "w") as handle:
                    json.dump(agent.last_raw_response, handle, indent=2, default=str)
                step_record["raw_response_file"] = f"raw_responses/step_{step:03d}.json"
            except Exception:
                pass

        action_results = []
        done = False
        failed = False
        for action_code in actions:
            if action_code == "DONE":
                action_results.append({"action": "DONE"})
                done = True
                break
            if action_code == "FAIL":
                action_results.append({"action": "FAIL"})
                failed = True
                break
            if action_code == "WAIT":
                action_results.append({"action": "WAIT"})
                time.sleep(5)
                continue

            ok, desc = agent.execute_action(sandbox, action_code)
            action_results.append(
                {
                    "action": action_code,
                    "success": ok,
                    "description": desc,
                }
            )

        step_record["action_results"] = action_results
        trajectory.append(step_record)

        if done:
            return True, step, trajectory
        if failed:
            return False, step, trajectory

        time.sleep(0.5)

    return False, max_iterations, trajectory
