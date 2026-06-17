"""
GUI-Owl 1.5 agent — adapted from OSWorld/mm_agents/owl15_agent.py.

Uses the Qwen3-VL-style JSON tool-call format with a 1000x1000 coordinate
grid, as specified by the OWL15 system prompt. Coordinates returned by the
model are mapped onto the original screenshot dimensions before being emitted
as pyautogui code.

Env vars (pick one backend):
  OPENAI_BASE_URL + OPENAI_API_KEY   (OpenAI-compatible endpoint)
  DASHSCOPE_BASE_URL + DASHSCOPE_API_KEY
"""

import base64
import json
import logging
import math
import os
import re
import time
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.owl15")

MAX_RETRY_TIMES = 5

# System prompt from OSWorld/mm_agents/owl15_agent.py (OWL15_PROMPT).
OWL15_SYSTEM_PROMPT = (
    "# Tools\n\n"
    "You may call one or more functions to assist with the user query.\n\n"
    "You are provided with function signatures within <tools></tools> XML tags:\n"
    "<tools>\n"
    '{"type": "function", "function": {"name": "computer_use", "description": '
    '"Use a mouse and keyboard to interact with a computer, and take screenshots.\\n'
    "* This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.\\n"
    "* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions. E.g. if you click on Firefox and a window doesn't open, try wait and taking another screenshot.\\n"
    "* The screen's resolution is 1000x1000.\\n"
    "* Whenever you intend to move the cursor to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.\\n"
    "* If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.\\n"
    "* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked."
    '", "parameters": {"properties": {"action": {"description": '
    '"The action to perform. The available actions are:\\n'
    "* `key`: Performs key down presses on the arguments passed in order, then performs key releases in reverse order.\\n"
    "* `type`: Type a string of text on the keyboard.\\n"
    "* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.\\n"
    "* `left_click`: Click the left mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
    "* `left_click_drag`: Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.\\n"
    "* `right_click`: Click the right mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
    "* `middle_click`: Click the middle mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
    "* `double_click`: Double-click the left mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
    "* `triple_click`: Triple-click the left mouse button at a specified (x, y) pixel coordinate on the screen (simulated as double-click since it's the closest action).\\n"
    "* `scroll`: Performs a scroll of the mouse scroll wheel.\\n"
    "* `hscroll`: Performs a horizontal scroll (mapped to regular scroll).\\n"
    "* `wait`: Wait specified seconds for the change to happen.\\n"
    "* `terminate`: Terminate the current task and report its completion status.\\n"
    "* `answer`: Answer a question."
    '", "enum": ["key", "type", "mouse_move", "left_click", "left_click_drag", '
    '"right_click", "middle_click", "double_click", "triple_click", "scroll", '
    '"hscroll", "wait", "terminate", "answer"], "type": "string"}, '
    '"keys": {"description": "Required only by `action=key`.", "type": "array"}, '
    '"text": {"description": "Required only by `action=type` and `action=answer`.", "type": "string"}, '
    '"coordinate": {"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=mouse_move` and `action=left_click_drag`.", "type": "array"}, '
    '"pixels": {"description": "The amount of scrolling to perform. Positive values scroll up, negative values scroll down. Required only by `action=scroll` and `action=hscroll`.", "type": "number"}, '
    '"time": {"description": "The seconds to wait. Required only by `action=wait`.", "type": "number"}, '
    '"status": {"description": "The status of the task. Required only by `action=terminate`.", "type": "string", "enum": ["success", "failure"]}}, '
    '"required": ["action"], "type": "object"}}}\n'
    "</tools>\n\n"
    "For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n"
    "<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n'
    "</tool_call>\n\n"
    "# Response format\n\n"
    "Response format for every step:\n"
    "1) Action: a short imperative describing what to do in the UI.\n"
    "2) A single <tool_call>...</tool_call> block containing only the JSON: "
    '{"name": <function-name>, "arguments": <args-json-object>}.\n\n'
    "Rules:\n"
    "- Output exactly in the order: Action, <tool_call>.\n"
    "- Be brief: one for Action.\n"
    "- Do not output anything else outside those two parts.\n"
    "- If finishing, use action=terminate in the tool call."
)


# ── Image resizing (matches OSWorld owl15 update_image_size_) ────────────

def _round_by(n: int, f: int) -> int:
    return round(n / f) * f


def _floor_by(n: float, f: int) -> int:
    return math.floor(n / f) * f


def _ceil_by(n: float, f: int) -> int:
    return math.ceil(n / f) * f


def _smart_resize(
    height: int,
    width: int,
    factor: int = 32,
    min_pixels: int = 56 * 56,
    max_pixels: int = 2645 * 16 * 16 * 4,
) -> Tuple[int, int]:
    """Qwen-VL-style smart resize (patch_size=16, merge_base=2, max_tokens=2645)."""
    if height < 2 or width < 2:
        raise ValueError(f"height:{height} or width:{width} too small")
    h_bar = _round_by(height, factor)
    w_bar = _round_by(width, factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = _floor_by(height / beta, factor)
        w_bar = _floor_by(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil_by(height * beta, factor)
        w_bar = _ceil_by(width * beta, factor)
    return h_bar, w_bar


def _process_image(image_bytes: bytes) -> Tuple[str, int, int]:
    image = Image.open(BytesIO(image_bytes))
    w, h = image.size
    new_h, new_w = _smart_resize(h, w)
    image = image.resize((new_w, new_h))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8"), new_w, new_h


class Owl15Agent(BaseAgent):
    """
    Agent powered by GUI-Owl 1.5 models via OpenAI-compat or DashScope.

    Outputs JSON tool calls inside <tool_call> tags with a 1000x1000
    coordinate grid; we rescale onto the original screenshot dimensions
    before emitting pyautogui code.
    """

    def __init__(
        self,
        model: str = "gui-owl-1.5",
        api_backend: str = "openai",
        history_n: int = 5,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.api_backend = api_backend
        self.history_n = int(history_n)

        self.actions: List[str] = []
        self.responses: List[str] = []
        self.conclusions: List[str] = []
        self.screenshots: List[str] = []  # processed base64 screenshots
        self.orig_sizes: List[Tuple[int, int]] = []

    # ── Public interface ────────────────────────────────────────────────

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        screenshot_bytes = obs["screenshot"]

        orig_img = Image.open(BytesIO(screenshot_bytes))
        orig_w, orig_h = orig_img.size

        processed_b64, _proc_w, _proc_h = _process_image(screenshot_bytes)
        self.screenshots.append(processed_b64)
        self.orig_sizes.append((orig_w, orig_h))

        messages = self._build_messages(instruction, processed_b64)

        response = self._call_llm(messages)
        logger.info(f"Owl1.5 output: {response}")
        self.responses.append(response or "")
        self.last_raw_response = {"content": response}

        conclusion = self._extract_conclusion(response or "")
        self.conclusions.append(conclusion)

        low_level, code = self._parse_response(response or "", orig_w, orig_h)
        self.actions.append(low_level)
        return low_level, code

    def reset(self) -> None:
        self.actions = []
        self.responses = []
        self.conclusions = []
        self.screenshots = []
        self.orig_sizes = []

    # ── Message construction ────────────────────────────────────────────

    def _build_messages(self, instruction: str, current_b64: str) -> list:
        """Build chat messages with last ``history_n`` image/response pairs."""
        prev_actions_lines = []
        for idx, c in enumerate(self.conclusions):
            if c:
                prev_actions_lines.append(f"Step{idx + 1}: {c}")
        prev_actions_str = (
            "\n".join(prev_actions_lines) if prev_actions_lines else "None"
        )

        instruction_prompt = (
            "Please generate the next move according to the UI screenshot, "
            "instruction and previous actions.\n\n"
            f"Instruction: {instruction}\n\n"
            f"Previous actions:\n{prev_actions_str}"
        )

        messages: List[Dict] = [
            {"role": "system", "content": [{"type": "text", "text": OWL15_SYSTEM_PROMPT}]}
        ]

        total = len(self.screenshots)
        history_len = min(self.history_n, total)
        start = total - history_len  # index of first retained screenshot

        for step_num in range(start, total):
            img_url = f"data:image/png;base64,{self.screenshots[step_num]}"
            is_first_user_turn = step_num == start
            is_current = step_num == total - 1

            if is_first_user_turn:
                content = [
                    {"type": "text", "text": instruction_prompt},
                    {"type": "image_url", "image_url": {"url": img_url}},
                ]
            else:
                content = [{"type": "image_url", "image_url": {"url": img_url}}]

            messages.append({"role": "user", "content": content})

            if not is_current and step_num < len(self.responses):
                messages.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": self.responses[step_num]}],
                    }
                )

        return messages

    # ── LLM call ────────────────────────────────────────────────────────

    def _call_llm(self, messages: list) -> Optional[str]:
        if self.api_backend == "openai":
            return self._call_openai(messages)
        if self.api_backend == "dashscope":
            return self._call_dashscope(messages)
        raise ValueError(f"Unknown API backend: {self.api_backend}")

    def _call_openai(self, messages: list) -> str:
        import openai

        base_url = os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "sk-123")
        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=600)

        for attempt in range(MAX_RETRY_TIMES):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature if self.temperature is not None else 0.0,
                    top_p=self.top_p if self.top_p is not None else 0.9,
                )
                msg = resp.choices[0].message
                return msg.content or ""
            except Exception as e:
                logger.error(f"OpenAI-compat error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRY_TIMES - 1:
                    time.sleep(5)
        return ""

    def _call_dashscope(self, messages: list) -> str:
        import dashscope
        from dashscope import MultiModalConversation
        from http import HTTPStatus

        dashscope.base_http_api_url = os.environ.get(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
        )
        dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-123")

        ds_messages = self._to_dashscope_messages(messages)

        for attempt in range(MAX_RETRY_TIMES):
            try:
                resp = MultiModalConversation.call(
                    model=self.model,
                    messages=ds_messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature if self.temperature is not None else 0.0,
                    top_p=self.top_p if self.top_p is not None else 0.9,
                    vl_high_resolution_images=True,
                )
                if getattr(resp, "status_code", None) not in (None, HTTPStatus.OK):
                    logger.warning(
                        f"DashScope non-OK: {getattr(resp, 'code', '')} {getattr(resp, 'message', '')}"
                    )
                    time.sleep(1.5 * (attempt + 1))
                    continue
                text = self._extract_dashscope_text(resp)
                if text:
                    return text
            except Exception as e:
                logger.error(f"DashScope error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRY_TIMES - 1:
                    time.sleep(1.5 * (attempt + 1))
        return ""

    @staticmethod
    def _to_dashscope_messages(messages: list) -> list:
        out = []
        for m in messages:
            role = m.get("role", "")
            parts = m.get("content", [])
            dc = []
            for p in parts:
                ptype = p.get("type")
                if ptype == "text":
                    dc.append({"text": p.get("text", "")})
                elif ptype == "image_url":
                    url = (p.get("image_url") or {}).get("url", "")
                    dc.append({"image": url})
            if not dc and isinstance(m.get("content"), str):
                dc = [{"text": m["content"]}]
            out.append({"role": role, "content": dc})
        return out

    @staticmethod
    def _extract_dashscope_text(resp) -> Optional[str]:
        out = getattr(resp, "output", None) or (resp.get("output") if isinstance(resp, dict) else None)
        if not out:
            return None
        choices = getattr(out, "choices", None) if not isinstance(out, dict) else out.get("choices")
        if not choices:
            return None
        msg = getattr(choices[0], "message", None) if not isinstance(choices[0], dict) else choices[0].get("message")
        if not msg:
            return None
        content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content", [])
        if not content:
            return None
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and "text" in p) or None

    # ── Response parsing ────────────────────────────────────────────────

    @staticmethod
    def _extract_conclusion(response: str) -> str:
        """Pull the ``Action:`` imperative from an Owl1.5 response."""
        if not response:
            return ""
        pre_tool = response.split("<tool_call>", 1)[0]
        for line in pre_tool.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("action:"):
                return stripped.split(":", 1)[-1].strip()
        return pre_tool.strip()

    def _parse_response(
        self, response: str, orig_w: int, orig_h: int
    ) -> Tuple[str, List[str]]:
        """Parse <tool_call> JSON blocks into pyautogui code strings."""
        low_level = ""
        code: List[str] = []

        if not response or not response.strip():
            return low_level, code

        def adjust(x: float, y: float) -> Tuple[int, int]:
            # Owl1.5 emits coordinates in a 1000x1000 grid.
            return int(x / 1000 * orig_w), int(y / 1000 * orig_h)

        def parse_coordinate(raw):
            if isinstance(raw, list) and len(raw) >= 2:
                return raw[0], raw[1]
            if isinstance(raw, str):
                try:
                    j = json.loads(raw)
                    if isinstance(j, list) and len(j) >= 2:
                        return j[0], j[1]
                except Exception:
                    return None
            return None

        def py_str(text: str) -> str:
            return json.dumps("" if text is None else str(text), ensure_ascii=False)

        def process(args: Dict) -> None:
            action = args.get("action")
            if not action:
                return
            coord = parse_coordinate(args.get("coordinate"))

            if action in ("left_click", "click"):
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.click({x}, {y})")
                else:
                    code.append("pyautogui.click()")
            elif action == "right_click":
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.rightClick({x}, {y})")
                else:
                    code.append("pyautogui.rightClick()")
            elif action == "middle_click":
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.middleClick({x}, {y})")
                else:
                    code.append("pyautogui.middleClick()")
            elif action == "double_click":
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.doubleClick({x}, {y})")
                else:
                    code.append("pyautogui.doubleClick()")
            elif action == "triple_click":
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.tripleClick({x}, {y})")
                else:
                    code.append("pyautogui.tripleClick()")
            elif action == "mouse_move":
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.moveTo({x}, {y})")
            elif action == "left_click_drag":
                if coord:
                    x, y = adjust(*coord)
                    code.append(f"pyautogui.dragTo({x}, {y}, duration=0.5)")
            elif action == "type":
                text_val = args.get("text", "")
                code.append(
                    f"pyperclip.copy({py_str(text_val)}); "
                    f"pyautogui.hotkey('ctrl', 'v'); time.sleep(0.1)"
                )
            elif action == "key":
                raw_keys = args.get("keys", [])
                if isinstance(raw_keys, str):
                    try:
                        raw_keys = json.loads(raw_keys)
                    except Exception:
                        raw_keys = [raw_keys]
                keys = [str(k).strip() for k in raw_keys] if isinstance(raw_keys, list) else [str(raw_keys)]
                keys_str = ", ".join(py_str(k) for k in keys)
                if len(keys) > 1:
                    code.append(f"pyautogui.hotkey({keys_str})")
                elif keys:
                    code.append(f"pyautogui.press({keys_str})")
            elif action in ("scroll", "hscroll"):
                try:
                    pixels = int(float(args.get("pixels", 0)))
                except Exception:
                    pixels = 0
                code.append(f"pyautogui.scroll({pixels})")
            elif action == "wait":
                code.append("WAIT")
            elif action == "terminate":
                code.append("DONE" if args.get("status") == "success" else "FAIL")
            elif action == "answer":
                code.append("DONE")

        for tc in re.finditer(r"<tool_call>(.*?)</tool_call>", response, re.DOTALL):
            try:
                obj = json.loads(tc.group(1).strip())
            except json.JSONDecodeError as e:
                logger.error(f"Bad tool_call JSON: {e}")
                continue
            if obj.get("name") != "computer_use":
                continue
            process(obj.get("arguments") or {})

        if not code:
            for line in response.splitlines():
                stripped = line.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("name") == "computer_use":
                        process(obj.get("arguments") or {})

        low_level = self._extract_conclusion(response)
        if not low_level and code:
            first = code[0]
            if first in ("DONE", "FAIL", "WAIT"):
                low_level = first.capitalize()
            elif "." in first:
                low_level = f"Performing {first.split('.', 1)[1].split('(', 1)[0]} action"
            else:
                low_level = "Performing action"

        return low_level, code
