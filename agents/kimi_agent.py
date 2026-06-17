"""
Kimi (Moonshot) agent — uses pyautogui code generation via chat API.

Env vars required:
  KIMI_API_KEY
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

logger = logging.getLogger("agents.kimi")

KIMI_API_URL = "https://api.moonshot.ai/v1/chat/completions"
KIMI_AUTH_ENV_VARS = ("KIMI_API_KEY", "MOONSHOT_API_KEY")

# ── System prompts ──────────────────────────────────────────────────────

SYSTEM_PROMPT_THINKING = """
You are a GUI agent. You are given an instruction, a screenshot of the screen and your previous interactions with the computer. You need to perform a series of actions to complete the task. The passoword of the computer is {password}.

For each step, provide your response in this format:
{{thought}}
## Action:
{{action}}
## Code:
{{code}}

In the code section, the code should be either pyautogui code or one of the following functions wrapped in the code block:
- {{"name": "computer.wait", "description": "Make the computer wait for 20 seconds for installation, running code, etc.", "parameters": {{"type": "object", "properties": {{}}, "required": []}}}}
- {{"name": "computer.terminate", "description": "Terminate the current task and report its completion status", "parameters": {{"type": "object", "properties": {{"status": {{"type": "string", "enum": ["success", "failure"], "description": "The status of the task"}}, "answer": {{"type": "string", "description": "The answer of the task"}}}}, "required": ["status"]}}}}
""".strip()

SYSTEM_PROMPT_NON_THINKING = """
You are a GUI agent. You are given an instruction, a screenshot of the screen and your previous interactions with the computer. You need to perform a series of actions to complete the task. The passoword of the computer is {password}.

For each step, provide your response in this format:
## Thought
{{thought}}
## Action:
{{action}}
## Code:
{{code}}

In the code section, the code should be either pyautogui code or one of the following functions wrapped in the code block:
- {{"name": "computer.wait", "description": "Make the computer wait for 20 seconds for installation, running code, etc.", "parameters": {{"type": "object", "properties": {{}}, "required": []}}}}
- {{"name": "computer.terminate", "description": "Terminate the current task and report its completion status", "parameters": {{"type": "object", "properties": {{"status": {{"type": "string", "enum": ["success", "failure"], "description": "The status of the task"}}, "answer": {{"type": "string", "description": "The answer of the task"}}}}, "required": ["status"]}}}}
""".strip()

INSTRUCTION_TEMPLATE = (
    "# Task Instruction:\n{instruction}\n\n"
    "Please generate the next move according to the screenshot, "
    "task instruction and previous steps (if provided).\n"
)
STEP_TEMPLATE = "# Step {step_num}:\n"
THOUGHT_HISTORY_THINKING = "\u25c1think\u25b7{thought}\u25c1/think\u25b7## Action:\n{action}\n"
THOUGHT_HISTORY_NON_THINKING = "## Thought:\n{thought}\n\n## Action:\n{action}\n"


class KimiAgent(BaseAgent):
    """
    Agent powered by Kimi K2.5 (Moonshot) chat API.

    Generates pyautogui code blocks; coordinates can be relative or absolute.
    """

    def __init__(
        self,
        model: str = "kimi-k2.5",
        thinking: bool = True,
        coordinate_type: str = "relative",
        max_image_history: int = 3,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.thinking = thinking
        self.coordinate_type = coordinate_type
        self.max_image_history = max_image_history

        if thinking:
            self.system_prompt = SYSTEM_PROMPT_THINKING.format(password=self.password)
            self.history_template = THOUGHT_HISTORY_THINKING
        else:
            self.system_prompt = SYSTEM_PROMPT_NON_THINKING.format(password=self.password)
            self.history_template = THOUGHT_HISTORY_NON_THINKING

        self.actions: List[str] = []
        self.observations: List[Dict] = []
        self.cots: List[dict] = []

    # ── Public interface ────────────────────────────────────────────────

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        import httpx

        messages = self._build_messages(instruction, obs)

        max_retry = 5
        response_msg = None
        parsed_action = None
        parsed_code = None
        cot = {}

        for retry in range(max_retry):
            try:
                response_msg = self._call_api(
                    messages,
                    temp_override=max(0.2, self.temperature) if retry > 0 and self.temperature else self.temperature,
                )
                if not response_msg:
                    raise ValueError("Empty response from Kimi API")

                parsed_action, parsed_code, cot = self._parse_response(
                    response_msg, self.screen_size, self.coordinate_type
                )
                if "<Error>" in (parsed_action or ""):
                    raise ValueError(f"Parse error: {parsed_action}")
                break
            except Exception as e:
                logger.warning(f"Attempt {retry + 1}/{max_retry} failed: {e}")
                if retry == max_retry - 1:
                    return str(e), ["FAIL"]

        # Scale scroll for Windows
        if self.platform == "windows":
            parsed_code = [self._scale_scroll(c, 50) for c in (parsed_code or [])]

        # Save history
        self.observations.append(obs)
        self.actions.append(parsed_action or "")
        self.cots.append(cot)

        # Store raw response for logging
        self.last_raw_response = response_msg

        # Force termination at max steps
        step = len(self.actions)
        if step >= self.max_steps and parsed_code and "computer.terminate" not in parsed_code[0].lower():
            logger.warning(f"Reached max steps ({self.max_steps}), forcing FAIL")
            return "Max steps reached", ["FAIL"]

        reasoning = cot.get("thought", parsed_action or "")
        return reasoning, parsed_code or ["FAIL"]

    def reset(self) -> None:
        self.actions = []
        self.observations = []
        self.cots = []

    # ── Message construction ────────────────────────────────────────────

    def _build_messages(self, instruction: str, obs: Dict) -> list:
        messages = [{"role": "system", "content": self.system_prompt}]
        instruction_prompt = INSTRUCTION_TEMPLATE.format(instruction=instruction)

        # Add history
        for i in range(len(self.actions)):
            if i > len(self.actions) - self.max_image_history:
                # Recent steps: include screenshot
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{self._encode(self.observations[i]['screenshot'])}"
                                },
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": STEP_TEMPLATE.format(step_num=i + 1)
                        + self.history_template.format(
                            thought=self.cots[i].get("thought", ""),
                            action=self.cots[i].get("action", ""),
                        ),
                    }
                )
            else:
                # Older steps: text only (collapsed into one block at boundary)
                if i == len(self.actions) - self.max_image_history:
                    text_parts = []
                    for j in range(i + 1):
                        text_parts.append(
                            STEP_TEMPLATE.format(step_num=j + 1)
                            + self.history_template.format(
                                thought=self.cots[j].get("thought", ""),
                                action=self.cots[j].get("action", ""),
                            )
                        )
                    messages.append({"role": "assistant", "content": "\n".join(text_parts)})

        # Current observation
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{self._encode(obs['screenshot'])}"
                        },
                    },
                    {"type": "text", "text": instruction_prompt},
                ],
            }
        )
        return messages

    # ── API call ────────────────────────────────────────────────────────

    def _call_api(self, messages: list, temp_override: Optional[float] = None) -> Optional[dict]:
        import httpx

        api_key = next((os.getenv(name) for name in KIMI_AUTH_ENV_VARS if os.getenv(name)), None)
        if not api_key:
            raise RuntimeError(
                "Missing Kimi API key. Set KIMI_API_KEY or MOONSHOT_API_KEY in .env."
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self.max_tokens,
            "top_p": self.top_p or 0.95,
            "temperature": temp_override if temp_override is not None else (self.temperature or 1.0),
        }

        for attempt in range(20):
            try:
                resp = httpx.post(
                    KIMI_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=1200,
                    verify=False,
                )
            except httpx.HTTPError as exc:
                logger.warning(f"Kimi API request failed: {exc}")
                time.sleep(5)
                continue

            if resp.status_code != 200:
                logger.warning(f"Kimi API error ({resp.status_code}): {resp.text}")
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        "Kimi API authentication failed. Check that the key is a valid "
                        "Moonshot/Kimi API key for https://api.moonshot.ai, not a kimi.com "
                        "web subscription token, and rotate it if it was exposed."
                    )
                time.sleep(5)
                continue

            data = resp.json()
            finish = data["choices"][0].get("finish_reason")
            if finish == "stop":
                return data["choices"][0]["message"]
            else:
                logger.warning("Kimi did not finish, retrying...")
                time.sleep(5)

        return None

    # ── Response parsing ────────────────────────────────────────────────

    def _parse_response(
        self, response: dict, screen_size: Tuple[int, int], coordinate_type: str
    ) -> Tuple[str, List[str], dict]:
        """Parse Kimi response into (action_description, code_list, cot_dict)."""
        input_string = response["content"].lstrip()
        sections: dict = {}

        try:
            if self.thinking:
                thought = response.get("reasoning_content", "").strip()
                sections["thought"] = thought
                m = re.search(r"^##\s*Action\b", input_string, flags=re.MULTILINE)
                if m:
                    input_string = input_string[m.start() :]
            else:
                thought = re.search(
                    r"^##\s*Thought\s*:?[\n\r]+(.*?)(?=^##\s*Action:|^##|\Z)",
                    input_string,
                    re.DOTALL | re.MULTILINE,
                )
                sections["thought"] = thought.group(1).strip() if thought else ""

            # Extract action
            action_match = re.search(
                r"^\s*##\s*Action\s*:?\s*[\n\r]+(.*?)(?=^\s*##|\Z)",
                input_string,
                re.DOTALL | re.MULTILINE,
            )
            if action_match:
                sections["action"] = action_match.group(1).strip()

            # Extract code block
            code_blocks = re.findall(
                r"```(?:code|python)?\s*(.*?)\s*```", input_string, re.DOTALL | re.IGNORECASE
            )
            if not code_blocks:
                return f"<Error>: no code blocks found", ["FAIL"], sections

            code_block = code_blocks[-1].strip()
            sections["original_code"] = code_block

            # Special commands
            if "computer.wait" in code_block.lower():
                sections["code"] = "WAIT"
                return sections.get("action", "wait"), ["WAIT"], sections
            elif "computer.terminate" in code_block.lower():
                lower = code_block.lower()
                if "failure" in lower or "fail" in lower:
                    sections["code"] = "FAIL"
                    return code_block, ["FAIL"], sections
                elif "success" in lower:
                    sections["code"] = "DONE"
                    return code_block, ["DONE"], sections
                else:
                    return "<Error>: terminate without status", ["FAIL"], sections

            # Project coordinates
            sections["code"] = _project_coordinates(
                code_block,
                screen_width=screen_size[0],
                screen_height=screen_size[1],
                coordinate_type=coordinate_type,
            )

            if not sections.get("code") or not sections.get("action"):
                return f"<Error>: missing action or code", ["FAIL"], sections

            return sections["action"], [sections["code"]], sections

        except Exception as e:
            return f"<Error>: {e}", ["FAIL"], sections

    # ── Utilities ───────────────────────────────────────────────────────

    @staticmethod
    def _encode(image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("utf-8")

    @staticmethod
    def _scale_scroll(code: str, factor: int = 50) -> str:
        pattern = re.compile(r"(pyautogui\.scroll\()\s*([-+]?\d+)\s*\)")
        return pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)) * factor})", code)


# ── Coordinate projection ────────────────────────────────────────────────

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


def _project_coordinates(
    pyautogui_code: str,
    screen_width: int,
    screen_height: int,
    coordinate_type: str = "relative",
) -> str:
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
                args[param_names[idx]] = ast.literal_eval(arg)

        try:
            for kw in parsed_keywords:
                args[kw.arg] = ast.literal_eval(kw.value)
        except Exception:
            return pyautogui_code

        updated = False
        if 'x' in args and 'y' in args:
            try:
                x_rel = float(args['x'])
                y_rel = float(args['y'])
                x_abs, y_abs = _coordinate_projection(x_rel, y_rel, screen_width, screen_height, coordinate_type)
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
