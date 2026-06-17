"""
EvoCUA agent — supports S1 (pyautogui code) and S2 (tool_call XML) prompt styles.

Env vars required:
  OPENAI_BASE_URL + OPENAI_API_KEY   (OpenAI-compatible endpoint)
"""

import ast
import base64
import json
import logging
import math
import os
import re
import traceback
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import backoff
from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.evocua")


def _smart_resize(height, width, factor=32, min_pixels=56 * 56, max_pixels=16 * 16 * 4 * 12800):
    if height < factor or width < factor:
        raise ValueError(f"height:{height} or width:{width} must be >= {factor}")
    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def _process_image(image_bytes, factor=32, max_pixels=16 * 16 * 4 * 12800):
    image = Image.open(BytesIO(image_bytes))
    w, h = image.size
    new_h, new_w = _smart_resize(h, w, factor=factor, max_pixels=max_pixels)
    image = image.resize((new_w, new_h))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8"), new_w, new_h


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


# ── S1 prompts ──────────────────────────────────────────────────────────

S1_SYSTEM_PROMPT = """You are a GUI agent. You are given a task, a screenshot of the screen and your previous interactions with the computer. You need to perform a series of actions to complete the task. The password of the computer is "{password}", use it when you need sudo rights. You need to **wait** explicitly for installation, waiting website loading or running commands to finish. Don't terminate the task unless you are sure the task is finished. If you find that you can't finish the task, or the task is not finished exactly as the instruction indicates, you must report **failure**.

For each step, provide your response in this format:
# Step: {{step number}}
## Thought:
{{thought}}
## Action:
{{action}}
## Code:
{{code}}

For the code section, you should output the corresponding code for the action. The code should be either PyAutoGUI code or one of the following functions:
- {{"name": "computer.wait", "description": "Wait 20 seconds"}}
- {{"name": "computer.terminate", "description": "Terminate with status", "parameters": {{"status": "success|failure"}}}}"""

S1_INSTRUCTION_TEMPLATE = "# Task Instruction:\n{instruction}\n\nPlease generate the next move according to the screenshot, task instruction and previous steps (if provided).\n"
S1_STEP_TEMPLATE = "# Step {step_num}:\n"
S1_ACTION_HISTORY = "## Action:\n{action}\n"

# ── S2 prompts ──────────────────────────────────────────────────────────

S2_ACTION_DESCRIPTION = """* `key`: Press key(s).
* `key_down`: Hold key(s) down.
* `key_up`: Release key(s).
* `type`: Type text.
* `mouse_move`: Move cursor.
* `left_click`: Left click.
* `left_click_drag`: Click and drag.
* `right_click`: Right click.
* `middle_click`: Middle click.
* `double_click`: Double click.
* `triple_click`: Triple click.
* `scroll`: Scroll.
* `wait`: Wait.
* `terminate`: End task."""

S2_SYSTEM_PROMPT_TEMPLATE = """# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{tools_json}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": <function-name>, "arguments": <args-json-object>}}
</tool_call>

# Response format

Response format for every step:
1) Action: a short imperative describing what to do in the UI.
2) A single <tool_call>...</tool_call> block.

Rules:
- Output exactly in the order: Action, <tool_call>.
- Be brief: one sentence for Action.
- If finishing, use action=terminate in the tool call."""


def _build_s2_tools_def(description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name_for_human": "computer_use",
            "name": "computer_use",
            "description": description,
            "parameters": {
                "properties": {
                    "action": {
                        "description": S2_ACTION_DESCRIPTION,
                        "enum": [
                            "key", "type", "mouse_move", "left_click", "left_click_drag",
                            "right_click", "middle_click", "double_click", "triple_click",
                            "scroll", "wait", "terminate", "key_down", "key_up",
                        ],
                        "type": "string",
                    },
                    "keys": {"description": "Required only by `action=key`.", "type": "array"},
                    "text": {"description": "Required only by `action=type`.", "type": "string"},
                    "coordinate": {"description": "The x,y coordinates.", "type": "array"},
                    "pixels": {"description": "Scroll amount.", "type": "number"},
                    "time": {"description": "Wait seconds.", "type": "number"},
                    "status": {"description": "Task status.", "type": "string", "enum": ["success", "failure"]},
                },
                "required": ["action"],
                "type": "object",
            },
            "args_format": "Format the arguments as a JSON object.",
        },
    }


class EvoCUAAgent(BaseAgent):
    """
    EvoCUA agent with S1 (pyautogui code gen) and S2 (tool_call XML) modes.
    Uses an OpenAI-compatible API endpoint.
    """

    def __init__(
        self,
        model: str = "EvoCUA-S2",
        prompt_style: str = "S2",
        coordinate_type: str = "relative",
        max_history_turns: int = 4,
        resize_factor: int = 32,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        assert prompt_style in ("S1", "S2"), f"Invalid prompt_style: {prompt_style}"
        self.prompt_style = prompt_style
        self.coordinate_type = coordinate_type
        self.max_history_turns = max_history_turns
        self.resize_factor = resize_factor

        self.actions: List[str] = []
        self.observations: List[Dict] = []
        self.responses: List[str] = []
        self.screenshots: List[str] = []
        self.cots: List[dict] = []

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        screenshot_bytes = obs["screenshot"]
        orig_img = Image.open(BytesIO(screenshot_bytes))
        orig_w, orig_h = orig_img.size

        if self.prompt_style == "S1":
            raw_b64 = _encode(screenshot_bytes)
            self.screenshots.append(raw_b64)
            result = self._predict_s1(instruction, obs, raw_b64)
        else:
            proc_b64, p_w, p_h = _process_image(screenshot_bytes, factor=self.resize_factor)
            self.screenshots.append(proc_b64)
            result = self._predict_s2(instruction, obs, proc_b64, p_w, p_h, orig_w, orig_h)

        # Store raw response for logging
        self.last_raw_response = {"content": self.responses[-1] if self.responses else None}
        return result

    def reset(self) -> None:
        self.actions = []
        self.observations = []
        self.responses = []
        self.screenshots = []
        self.cots = []

    # ── S1 mode ─────────────────────────────────────────────────────────

    def _predict_s1(self, instruction, obs, b64):
        messages = [{"role": "system", "content": S1_SYSTEM_PROMPT.format(password=self.password)}]

        # History
        for i in range(len(self.actions)):
            cot = self.cots[i] if i < len(self.cots) else {}
            step_content = S1_STEP_TEMPLATE.format(step_num=i + 1) + S1_ACTION_HISTORY.format(action=cot.get("action", ""))

            if i > len(self.actions) - self.max_history_turns:
                if i < len(self.screenshots) - 1:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{self.screenshots[i]}"}}],
                    })
                messages.append({"role": "assistant", "content": step_content})
            # Older steps collapsed (omitted for brevity, same pattern as original)

        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": S1_INSTRUCTION_TEMPLATE.format(instruction=instruction)},
            ],
        })

        response = self._call_llm(messages)
        low_level, codes, cot_data = self._parse_s1(response or "")

        self.observations.append(obs)
        self.cots.append(cot_data)
        self.actions.append(low_level)
        self.responses.append(response or "")

        return low_level, codes

    def _parse_s1(self, response: str) -> Tuple[str, List[str], dict]:
        sections = {}
        for key, pattern in [
            ("observation", r'#{1,2}\s*Observation\s*:?[\n\r]+(.*?)(?=^#{1,2}\s|$)'),
            ("thought", r'#{1,2}\s*Thought\s*:?[\n\r]+(.*?)(?=^#{1,2}\s|$)'),
            ("action", r'#{1,2}\s*Action\s*:?[\n\r]+(.*?)(?=^#{1,2}\s|$)'),
        ]:
            m = re.search(pattern, response, re.DOTALL | re.MULTILINE)
            if m:
                sections[key] = m.group(1).strip()

        code_blocks = re.findall(r'```(?:code|python)?\s*(.*?)\s*```', response, re.DOTALL | re.IGNORECASE)
        code = code_blocks[-1].strip() if code_blocks else "FAIL"
        sections["original_code"] = code

        if "computer.wait" in code.lower():
            sections["code"] = "WAIT"
            return sections.get("action", "wait"), ["WAIT"], sections
        elif "computer.terminate" in code.lower():
            lower_block = code.lower()
            if "failure" in lower_block or "fail" in lower_block:
                sections["code"] = "FAIL"
                return code, ["FAIL"], sections
            elif "success" in lower_block:
                sections["code"] = "DONE"
                return code, ["DONE"], sections
            else:
                return code, ["FAIL"], sections
        else:
            projected = _project_coordinates(code, self.screen_size[0], self.screen_size[1], self.coordinate_type)
            rewritten = _rewrite_type_inputs(projected)
            sections["code"] = rewritten
            final = [rewritten]

        if not sections.get("code") or not sections.get("action"):
            return "<Error>: missing action or code", ["FAIL"], sections

        return sections.get("action", "Acting"), final, sections

    # ── S2 mode ─────────────────────────────────────────────────────────

    def _predict_s2(self, instruction, obs, proc_b64, p_w, p_h, orig_w, orig_h):
        current_step = len(self.actions)
        history_n = self.max_history_turns

        if self.coordinate_type == "absolute":
            res_info = f"* The screen's resolution is {p_w}x{p_h}."
        else:
            res_info = "* The screen's resolution is 1000x1000."

        desc = (
            "Use a mouse and keyboard to interact with a computer, and take screenshots.\n"
            f"* This is an interface to a desktop GUI.\n{res_info}\n"
            "* Click the center of elements, not edges."
        )
        tools_json = json.dumps(_build_s2_tools_def(desc))
        system_prompt = S2_SYSTEM_PROMPT_TEMPLATE.format(tools_json=tools_json)

        messages = self._build_s2_messages(instruction, proc_b64, current_step, history_n, system_prompt)
        response = self._call_llm(messages)
        self.responses.append(response or "")

        low_level, codes = self._parse_s2(response or "", p_w, p_h, orig_w, orig_h)

        # Max steps check
        step = len(self.actions) + 1
        if step >= self.max_steps and codes and codes[0] not in ("DONE", "FAIL"):
            low_level = "Max steps reached"
            codes = ["FAIL"]

        self.actions.append(low_level)
        return low_level, codes

    def _build_s2_messages(self, instruction, current_img, step, history_n, system_prompt):
        messages = [{"role": "system", "content": [{"type": "text", "text": system_prompt}]}]

        prev_actions = []
        history_start = max(0, step - history_n)
        for i in range(history_start):
            if i < len(self.actions):
                prev_actions.append(f"Step {i + 1}: {self.actions[i]}")
        prev_str = "\n".join(prev_actions) if prev_actions else "None"

        instruction_prompt = (
            f"Please generate the next move according to the UI screenshot, "
            f"instruction and previous actions.\n\nInstruction: {instruction}\n\nPrevious actions:\n{prev_str}"
        )

        history_len = min(history_n, len(self.responses))
        if history_len > 0:
            hist_responses = self.responses[-history_len:]
            hist_imgs = self.screenshots[-history_len - 1 : -1]

            for idx in range(history_len):
                if idx < len(hist_imgs):
                    img_url = f"data:image/png;base64,{hist_imgs[idx]}"
                    content = [{"type": "image_url", "image_url": {"url": img_url}}]
                    if idx == 0:
                        content.append({"type": "text", "text": instruction_prompt})
                    messages.append({"role": "user", "content": content})
                messages.append({"role": "assistant", "content": [{"type": "text", "text": hist_responses[idx]}]})

            messages.append({
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{current_img}"}}],
            })
        else:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{current_img}"}},
                    {"type": "text", "text": instruction_prompt},
                ],
            })
        return messages

    def _parse_s2(self, response, p_w, p_h, orig_w, orig_h):
        """Parse S2 tool_call XML response (same format as Qwen)."""
        low_level = ""
        codes: List[str] = []

        if not response or not response.strip():
            return low_level, codes

        def adjust(x, y):
            if self.coordinate_type == "absolute":
                if p_w and p_h:
                    return int(x * orig_w / p_w), int(y * orig_h / p_h)
                return int(x), int(y)
            return int(x * orig_w / 999), int(y * orig_h / 999)

        def process_tc(json_str):
            try:
                tc = json.loads(json_str)
                if tc.get("name") != "computer_use":
                    return
                args = tc["arguments"]
                action = args["action"]

                if action in ("left_click", "click", "right_click", "middle_click", "double_click", "triple_click"):
                    fn_map = {"left_click": "click", "click": "click", "right_click": "rightClick",
                              "middle_click": "middleClick", "double_click": "doubleClick", "triple_click": "tripleClick"}
                    fn = fn_map.get(action, "click")
                    if "coordinate" in args:
                        ax, ay = adjust(*args["coordinate"])
                        codes.append(f"pyautogui.{fn}({ax}, {ay})")
                    else:
                        codes.append(f"pyautogui.{fn}()")
                elif action == "type":
                    text = args.get("text", "")
                    lines = []
                    for ch in text:
                        if ch == "\n":
                            lines.append("pyautogui.press('enter')")
                        elif ch == "'":
                            lines.append("pyautogui.press(\"'\")")
                        elif ch == "\\":
                            lines.append("pyautogui.press('\\\\')")
                        elif ch == '"':
                            lines.append('pyautogui.press(\'"\')')
                        else:
                            lines.append(f"pyautogui.press('{ch}')")
                    codes.append("\n".join(lines))
                elif action == "key":
                    keys = [k.strip() for k in args.get("keys", []) if isinstance(k, str)]
                    ks = ", ".join(f"'{k}'" for k in keys)
                    codes.append(f"pyautogui.hotkey({ks})" if len(keys) > 1 else f"pyautogui.press({ks})")
                elif action == "key_down":
                    for k in args.get("keys", []):
                        codes.append(f"pyautogui.keyDown('{k}')")
                elif action == "key_up":
                    for k in reversed(args.get("keys", [])):
                        codes.append(f"pyautogui.keyUp('{k}')")
                elif action == "scroll":
                    codes.append(f"pyautogui.scroll({args.get('pixels', 0)})")
                elif action == "mouse_move":
                    if "coordinate" in args:
                        ax, ay = adjust(*args["coordinate"])
                        codes.append(f"pyautogui.moveTo({ax}, {ay})")
                elif action == "left_click_drag":
                    if "coordinate" in args:
                        ax, ay = adjust(*args["coordinate"])
                        codes.append(f"pyautogui.dragTo({ax}, {ay}, duration={args.get('duration', 0.5)})")
                elif action == "wait":
                    codes.append("WAIT")
                elif action == "terminate":
                    codes.append("DONE" if args.get("status", "success") == "success" else "FAIL")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse tool call: {e}")

        # Parse tool_call XML
        inside_tc = False
        tc_lines: List[str] = []
        for line in response.split("\n"):
            s = line.strip()
            if not s:
                continue
            if s.lower().startswith("action:") and not low_level:
                low_level = s.split(":", 1)[-1].strip()
                continue
            if s.startswith("<tool_call>"):
                inside_tc = True
                continue
            elif s.startswith("</tool_call>"):
                if tc_lines:
                    process_tc("\n".join(tc_lines))
                    tc_lines = []
                inside_tc = False
                continue
            if inside_tc:
                tc_lines.append(s)
                continue
            if s.startswith("{") and s.endswith("}"):
                try:
                    obj = json.loads(s)
                    if "name" in obj and "arguments" in obj:
                        process_tc(s)
                except json.JSONDecodeError:
                    pass

        if tc_lines:
            process_tc("\n".join(tc_lines))

        if not low_level and codes:
            low_level = "Performing action"

        return low_level, codes

    # ── LLM call ────────────────────────────────────────────────────────

    def _call_llm(self, messages: list) -> Optional[str]:
        import openai as oai

        base_url = os.environ.get("OPENAI_BASE_URL", "")
        api_key = os.environ.get("OPENAI_API_KEY", "sk-xxx")
        client = oai.OpenAI(base_url=base_url, api_key=api_key)

        for attempt in range(5):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature or 0.0,
                    top_p=self.top_p or 0.9,
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.error(f"EvoCUA LLM error (attempt {attempt + 1}): {e}")
                import time
                time.sleep(5)
        return ""


# ── Coordinate projection (for S1 mode) ────────────────────────────────

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

    Ported from OSWorld/mm_agents/evocua/utils.py project_coordinate_to_absolute_scale.
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
            continue

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
                try:
                    args[param_names[idx]] = ast.literal_eval(arg)
                except Exception:
                    pass

        try:
            for kw in parsed_keywords:
                args[kw.arg] = ast.literal_eval(kw.value)
        except Exception as e:
            logger.error(f"Error parsing keyword arguments: {e}")
            continue

        updated = False
        if 'x' in args and 'y' in args:
            try:
                x_rel = float(args['x'])
                y_rel = float(args['y'])
                x_abs, y_abs = _coordinate_projection(x_rel, y_rel, screen_w, screen_h, coord_type)
                args['x'] = x_abs
                args['y'] = y_abs
                updated = True
            except (ValueError, TypeError):
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


def _fallback_rewrite_pyautogui_text_inputs(code: str) -> str:
    """Regex-based fallback for rewriting pyautogui.write/typewrite to per-char press calls."""
    import re as _re

    def _replacer(match):
        full_match = match.group(0)
        str_match = _re.search(r"""['"](.*?)['"]""", full_match)
        if not str_match:
            return full_match
        text = str_match.group(1)
        lines = []
        for char in text:
            press_value = "enter" if char == "\n" else char
            lines.append(f"pyautogui.press('{press_value}')")
        return "\n".join(lines)

    pattern = r"pyautogui\.(?:write|typewrite)\s*\(.*?(?=\s*;|\s*$|\n)"
    new_code = re.sub(pattern, _replacer, code)
    if new_code == code and ("pyautogui.write" in code or "pyautogui.typewrite" in code):
        new_code = re.sub(r"pyautogui\.(?:write|typewrite)\s*\(.*", _replacer, code)
    return new_code


def _rewrite_type_inputs(code: str) -> str:
    """Expand pyautogui.write/typewrite string literals into per-character presses.

    Ported from OSWorld/mm_agents/evocua/utils.py rewrite_pyautogui_text_inputs.
    """
    try:
        tree = ast.parse(code)

        class _TextCallRewriter(ast.NodeTransformer):
            def _extract_text(self, call: ast.Call):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "pyautogui"
                    and call.func.attr in ("write", "typewrite")
                ):
                    return None

                message_node = call.args[0] if call.args else None
                if message_node is None:
                    for kw in call.keywords:
                        if kw.arg in ("message", "text"):
                            message_node = kw.value
                            break

                if isinstance(message_node, ast.Constant) and isinstance(message_node.value, str):
                    return message_node.value
                return None

            def visit_Expr(self, node):
                self.generic_visit(node)
                if isinstance(node.value, ast.Call):
                    text = self._extract_text(node.value)
                    if text is not None:
                        new_nodes = []
                        for char in text:
                            press_value = "enter" if char == "\n" else char
                            press_call = ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="pyautogui", ctx=ast.Load()),
                                        attr="press",
                                        ctx=ast.Load(),
                                    ),
                                    args=[ast.Constant(value=press_value)],
                                    keywords=[],
                                )
                            )
                            new_nodes.append(press_call)
                        return new_nodes if new_nodes else node
                return node

        tree = _TextCallRewriter().visit(tree)
        tree = ast.fix_missing_locations(tree)
        new_code = ast.unparse(tree)
        return new_code

    except (SyntaxError, Exception):
        return _fallback_rewrite_pyautogui_text_inputs(code)
