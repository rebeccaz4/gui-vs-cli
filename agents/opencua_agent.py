"""
OpenCUA agent — uses pyautogui code generation with Observation/Thought/Action format.

Env vars required:
  OPENCUA_API_KEY
"""

import ast
import base64
import logging
import math
import os
import re
import time
import traceback
from typing import Dict, List, Optional, Tuple

from .base import BaseAgent

logger = logging.getLogger("agents.opencua")

INSTRUCTION_TEMPLATE = (
    "# Task Instruction:\n{instruction}\n\n"
    "Please generate the next move according to the screenshot, "
    "task instruction and previous steps (if provided).\n"
)
STEP_TEMPLATE = "# Step {step_num}:\n"
ACTION_HISTORY_TEMPLATE = "## Action:\n{action}\n"
THOUGHT_HISTORY_TEMPLATE = "## Thought:\n{thought}\n\n## Action:\n{action}\n"
OBSERVATION_HISTORY_TEMPLATE = "## Observation:\n{observation}\n\n## Thought:\n{thought}\n\n## Action:\n{action}\n"

SYSTEM_PROMPT = """You are a GUI agent. You are given a task, a screenshot of the screen and your previous interactions with the computer. You need to perform a series of actions to complete the task. The password of the computer is "{password}", use it when you need sudo rights. You need to **wait** explicitly for installation, waiting website loading or running commands to finish. Don't terminate the task unless you are sure the task is finished. If you find that you can't finish the task, you must report **failure**.

For each step, provide your response in this format:
# Step: {{step number}}
## Observation:
{{observation}}
## Thought:
{{thought}}
## Action:
{{action}}
## Code:
{{code}}

For the code section, output PyAutoGUI code or one of:
- {{"name": "computer.wait"}}
- {{"name": "computer.terminate", "parameters": {{"status": "success|failure"}}}}"""


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


class OpenCUAAgent(BaseAgent):
    """
    OpenCUA agent for desktop automation.
    Uses pyautogui code blocks with Observation/Thought/Action chain-of-thought.
    """

    def __init__(
        self,
        model: str,
        history_type: str = "observation_history",
        coordinate_type: str = "relative",
        cot_level: str = "l2",
        max_image_history: int = 3,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        assert history_type in ("action_history", "thought_history", "observation_history")
        self.history_type = history_type
        self.coordinate_type = coordinate_type
        self.cot_level = cot_level
        self.max_image_history = max_image_history

        if history_type == "action_history":
            self._history_template = ACTION_HISTORY_TEMPLATE
        elif history_type == "thought_history":
            self._history_template = THOUGHT_HISTORY_TEMPLATE
        else:
            self._history_template = OBSERVATION_HISTORY_TEMPLATE

        self.system_prompt = SYSTEM_PROMPT.format(password=self.password)

        self.actions: List[str] = []
        self.observations: List[Dict] = []
        self.cots: List[dict] = []

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        import httpx

        messages = self._build_messages(instruction, obs)

        max_retry = 5
        parsed_action = None
        parsed_code = None
        cot: dict = {}

        for retry in range(max_retry):
            try:
                response = self._call_api(messages, temp_override=max(0.2, self.temperature or 0) if retry > 0 else self.temperature)
                if not response:
                    raise ValueError("Empty response")

                parsed_action, parsed_code, cot = _parse_response(response, self.screen_size, self.coordinate_type)
                if "<Error>" in (parsed_action or ""):
                    raise ValueError(f"Parse error: {parsed_action}")
                break
            except Exception as e:
                logger.warning(f"Attempt {retry + 1}/{max_retry} failed: {e}")
                if retry == max_retry - 1:
                    return str(e), ["FAIL"]

        # Scale scroll for Windows
        if self.platform == "windows":
            parsed_code = [_scale_scroll(c, 50) for c in (parsed_code or [])]

        self.observations.append(obs)
        self.actions.append(parsed_action or "")
        self.cots.append(cot)

        # Store raw response for logging
        self.last_raw_response = response

        # Max steps check
        if len(self.actions) >= self.max_steps and parsed_code and parsed_code[0] not in ("DONE", "FAIL", "WAIT"):
            return "Max steps reached", ["FAIL"]

        reasoning = cot.get("thought", parsed_action or "")
        return reasoning, parsed_code or ["FAIL"]

    def reset(self) -> None:
        self.actions = []
        self.observations = []
        self.cots = []

    def _build_messages(self, instruction: str, obs: Dict) -> list:
        messages = [{"role": "system", "content": self.system_prompt}]
        instruction_prompt = INSTRUCTION_TEMPLATE.format(instruction=instruction)

        history_texts = []
        for i in range(len(self.actions)):
            history_content = STEP_TEMPLATE.format(step_num=i + 1) + self._history_template.format(
                observation=self.cots[i].get("observation", ""),
                thought=self.cots[i].get("thought", ""),
                action=self.cots[i].get("action", ""),
            )

            if i > len(self.actions) - self.max_image_history:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_encode(self.observations[i]['screenshot'])}"}},
                    ],
                })
                messages.append({"role": "assistant", "content": history_content})
            else:
                history_texts.append(history_content)
                if i == len(self.actions) - self.max_image_history:
                    messages.append({"role": "assistant", "content": "\n".join(history_texts)})

        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_encode(obs['screenshot'])}"}},
                {"type": "text", "text": instruction_prompt},
            ],
        })
        return messages

    def _call_api(self, messages: list, temp_override=None) -> Optional[str]:
        import httpx

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['OPENCUA_API_KEY']}",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p or 0.9,
            "temperature": temp_override if temp_override is not None else (self.temperature or 0.0),
        }

        for attempt in range(20):
            resp = httpx.post(
                f"https://{self.model}.app.msh.team/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=500,
                verify=False,
            )
            if resp.status_code != 200:
                logger.warning(f"OpenCUA API error ({resp.status_code})")
                time.sleep(5)
                continue
            data = resp.json()
            if data["choices"][0].get("finish_reason") == "stop":
                return data["choices"][0]["message"]["content"]
            time.sleep(5)
        return None


def _parse_response(response: str, screen_size, coordinate_type) -> Tuple[str, List[str], dict]:
    """Parse Observation/Thought/Action/Code response."""
    sections: dict = {}
    try:
        for key, pattern in [
            ("observation", r"^##\s*Observation\s*:?[\n\r]+(.*?)(?=^##\s*Thought:|^##\s*Action:|^##|\Z)"),
            ("thought", r"^##\s*Thought\s*:?[\n\r]+(.*?)(?=^##\s*Action:|^##|\Z)"),
            ("action", r"^##\s*Action\s*:?[\n\r]+(.*?)(?=^##|\Z)"),
        ]:
            m = re.search(pattern, response, re.DOTALL | re.MULTILINE)
            if m:
                sections[key] = m.group(1).strip()

        code_blocks = re.findall(r"```(?:code|python)?\s*(.*?)\s*```", response, re.DOTALL | re.IGNORECASE)
        if not code_blocks:
            return f"<Error>: no code blocks found", ["FAIL"], sections

        code = code_blocks[-1].strip()
        sections["original_code"] = code

        if "computer.wait" in code.lower():
            sections["code"] = "WAIT"
            return sections.get("action", "wait"), ["WAIT"], sections
        elif "computer.terminate" in code.lower():
            if "failure" in code.lower() or "fail" in code.lower():
                sections["code"] = "FAIL"
                return code, ["FAIL"], sections
            elif "success" in code.lower():
                sections["code"] = "DONE"
                return code, ["DONE"], sections
            return "<Error>: terminate without status", ["FAIL"], sections

        sections["code"] = _project_coordinates(code, screen_size[0], screen_size[1], coordinate_type)

        if not sections.get("code") or not sections.get("action"):
            return "<Error>: missing action or code", ["FAIL"], sections

        return sections["action"], [sections["code"]], sections

    except Exception as e:
        return f"<Error>: {e}\n{traceback.format_exc()}", ["FAIL"], sections


def _smart_resize(
    height: int,
    width: int,
    factor: int = 28,
    min_pixels: int = 56 * 56,
    max_pixels: int = 14 * 14 * 4 * 1280,
):
    """Rescale dimensions so both are divisible by factor, within pixel bounds."""
    if height < factor or width < factor:
        raise ValueError(f"height:{height} or width:{width} must be >= factor:{factor}")
    h_bar = max(1, round(height / factor)) * factor
    w_bar = max(1, round(width / factor)) * factor
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(1, math.floor(height / beta / factor)) * factor
        w_bar = max(1, math.floor(width / beta / factor)) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def _project_coordinates(pyautogui_code, screen_w, screen_h, coord_type="relative"):
    """Convert relative coordinates in pyautogui code to absolute screen coordinates.

    Ported from OSWorld/mm_agents/opencua/opencua_agent.py project_coordinate_to_absolute_scale.
    """
    def _coordinate_projection(x, y, sw, sh, ctype):
        if ctype == "relative":
            return int(round(x * sw)), int(round(y * sh))
        elif ctype == "qwen25":
            height, width = _smart_resize(
                height=sh, width=sw,
                factor=28, min_pixels=3136, max_pixels=12845056,
            )
            if 0 <= x <= 1 and 0 <= y <= 1:
                return int(round(x * width)), int(round(y * height))
            return int(x / width * sw), int(y / height * sh)
        else:
            raise ValueError(f"Invalid coordinate type: {ctype}")

    pattern = r'(pyautogui\.\w+\([^\)]*\))'
    matches = re.findall(pattern, pyautogui_code)
    new_code = pyautogui_code

    for full_call in matches:
        func_name_pattern = r'(pyautogui\.\w+)\((.*)\)'
        func_match = re.match(func_name_pattern, full_call, re.DOTALL)
        if not func_match:
            continue

        func_name = func_match.group(1)
        args_str = func_match.group(2)

        try:
            parsed = ast.parse(f"func({args_str})").body[0].value
            parsed_args = parsed.args
            parsed_keywords = parsed.keywords
        except SyntaxError:
            return pyautogui_code

        function_parameters = {
            'click': ['x', 'y', 'clicks', 'interval', 'button', 'duration', 'pause'],
            'rightClick': ['x', 'y', 'duration', 'tween', 'pause'],
            'middleClick': ['x', 'y', 'duration', 'tween', 'pause'],
            'doubleClick': ['x', 'y', 'interval', 'button', 'duration', 'pause'],
            'tripleClick': ['x', 'y', 'interval', 'button', 'duration', 'pause'],
            'moveTo': ['x', 'y', 'duration', 'tween', 'pause'],
            'dragTo': ['x', 'y', 'duration', 'button', 'mouseDownUp', 'pause'],
        }

        func_base_name = func_name.split('.')[-1]
        param_names = function_parameters.get(func_base_name, [])

        args = {}
        for idx, arg in enumerate(parsed_args):
            if idx < len(param_names):
                param_name = param_names[idx]
                args[param_name] = ast.literal_eval(arg)

        try:
            for kw in parsed_keywords:
                param_name = kw.arg
                args[param_name] = ast.literal_eval(kw.value)
        except Exception as e:
            logger.error(f"Error parsing keyword arguments: {e}")
            return pyautogui_code

        updated = False
        if 'x' in args and 'y' in args:
            try:
                x_rel = float(args['x'])
                y_rel = float(args['y'])
                x_abs, y_abs = _coordinate_projection(x_rel, y_rel, screen_w, screen_h, coord_type)
                args['x'] = x_abs
                args['y'] = y_abs
                updated = True
            except ValueError:
                pass

        if updated:
            reconstructed_args = []
            for idx, param_name in enumerate(param_names):
                if param_name in args:
                    arg_value = args[param_name]
                    if isinstance(arg_value, str):
                        arg_repr = f"'{arg_value}'"
                    else:
                        arg_repr = str(arg_value)
                    reconstructed_args.append(arg_repr)
                else:
                    break

            used_params = set(param_names[:len(reconstructed_args)])
            for kw in parsed_keywords:
                if kw.arg not in used_params:
                    arg_value = args[kw.arg]
                    if isinstance(arg_value, str):
                        arg_repr = f"{kw.arg}='{arg_value}'"
                    else:
                        arg_repr = f"{kw.arg}={arg_value}"
                    reconstructed_args.append(arg_repr)

            new_args_str = ', '.join(reconstructed_args)
            new_full_call = f"{func_name}({new_args_str})"
            new_code = new_code.replace(full_call, new_full_call)

    return new_code


def _scale_scroll(code: str, factor: int = 50) -> str:
    """Scale pyautogui.scroll amounts for Windows."""
    pattern = re.compile(r"(pyautogui\.scroll\()\s*([-+]?\d+)\s*\)")
    return pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)) * factor})", code)
