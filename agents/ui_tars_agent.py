"""
UI-TARS agent — adapted from ByteDance-Seed/UI-TARS.

UI-TARS-1.5 / UI-TARS-2 are GUI agent models that emit responses of the form

    Thought: ...
    Action: click(point='<point>x y</point>')

where coordinates are absolute pixels on the model's smart-resized view of the
image (qwen25vl convention). This agent runs the model behind an
OpenAI-compatible vLLM server, parses the Thought/Action block, rescales
coordinates onto the original screenshot, and emits pyautogui code strings
that the framework's BaseAgent.execute_action runs in the sandbox.

Env vars (OpenAI-compatible vLLM endpoint):
  OPENAI_BASE_URL   e.g. http://localhost:8001/v1
  OPENAI_API_KEY    any string ("empty" works for vLLM)

Typical launch:
  python -m vllm.entrypoints.openai.api_server \
      --model ByteDance-Seed/UI-TARS-1.5-7B \
      --served-model-name UI-TARS-1.5-7B --host 0.0.0.0 --port 8001 \
      --tensor-parallel-size 1 --trust-remote-code

  python evaluation/run_eval.py --model ui-tars-1.5-7b --endpoint-port 8001
"""

from __future__ import annotations

import ast
import base64
import json
import logging
import math
import os
import re
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.ui_tars")

MAX_RETRY_TIMES = 3

# ── qwen25vl smart_resize (mirror of UI-TARS action_parser) ─────────────
IMAGE_FACTOR = 28
MIN_PIXELS = 100 * 28 * 28
MAX_PIXELS = 16384 * 28 * 28
MAX_RATIO = 200


def _round_by(n: int, f: int) -> int:
    return round(n / f) * f


def _floor_by(n: float, f: int) -> int:
    return math.floor(n / f) * f


def _ceil_by(n: float, f: int) -> int:
    return math.ceil(n / f) * f


def _smart_resize(
    height: int,
    width: int,
    factor: int = IMAGE_FACTOR,
    min_pixels: int = MIN_PIXELS,
    max_pixels: int = MAX_PIXELS,
) -> Tuple[int, int]:
    if max(height, width) / max(1, min(height, width)) > MAX_RATIO:
        raise ValueError(
            f"absolute aspect ratio must be smaller than {MAX_RATIO}, "
            f"got {max(height, width) / max(1, min(height, width))}"
        )
    h_bar = max(factor, _round_by(height, factor))
    w_bar = max(factor, _round_by(width, factor))
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = _floor_by(height / beta, factor)
        w_bar = _floor_by(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil_by(height * beta, factor)
        w_bar = _ceil_by(width * beta, factor)
    return h_bar, w_bar


# ── COMPUTER_USE prompt template ────────────────────────────────────────
# Mirrors UI-TARS/codes/ui_tars/prompt.py::COMPUTER_USE_DOUBAO. The user
# instruction is appended at the end on every step.
COMPUTER_USE_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(point='<point>x1 y1</point>')
left_double(point='<point>x1 y1</point>')
right_single(point='<point>x1 y1</point>')
drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
hotkey(key='ctrl c') # Split keys with a space and use lowercase. Also, do not use more than 3 keys in one hotkey action.
type(content='xxx') # Use escape characters \\', \\\", and \\n in content part to ensure we can parse the content in normal python string format. If you want to submit your input, use \\n at the end of content.
scroll(point='<point>x1 y1</point>', direction='down or up or right or left') # Show more information on the `direction` side.
wait() #Sleep for 5s and take a screenshot to check for any changes.
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format.


## Note
- Use English in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
{instruction}
"""


def _encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def _escape_single_quotes(text: str) -> str:
    return re.sub(r"(?<!\\)'", r"\\'", text)


def _parse_call(action_str: str) -> Optional[Dict[str, Any]]:
    """Parse a single ``func(arg='val', ...)`` call into {function, args}."""
    try:
        node = ast.parse(action_str, mode="eval").body
        if not isinstance(node, ast.Call):
            return None
        if isinstance(node.func, ast.Name):
            fname = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fname = node.func.attr
        else:
            return None
        kwargs: Dict[str, Any] = {}
        for kw in node.keywords:
            if isinstance(kw.value, ast.Constant):
                kwargs[kw.arg] = kw.value.value
        return {"function": fname, "args": kwargs}
    except Exception as exc:
        logger.warning("UI-TARS could not parse action %r: %s", action_str, exc)
        return None


def _convert_point_tags(text: str) -> str:
    """Replace ``<point>x y</point>`` with ``(x,y)``."""
    pattern = r"<point>\s*(\d+)\s+(\d+)\s*</point>"
    return re.sub(pattern, lambda m: f"({m.group(1)},{m.group(2)})", text)


def _parse_response(text: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Return (thought, [parsed_call, ...]) from a UI-TARS response."""
    text = text.strip()
    if not text:
        return None, []

    text = _convert_point_tags(text)
    text = text.replace("start_point=", "start_box=").replace("end_point=", "end_box=")
    text = text.replace("point=", "start_box=")

    thought = None
    if "Thought:" in text:
        m = re.search(r"Thought:\s*(.+?)(?=\s*Action:\s*|$)", text, re.DOTALL)
        if m:
            thought = m.group(1).strip()
    elif "Action_Summary:" in text:
        m = re.search(r"Action_Summary:\s*(.+?)(?=\s*Action:\s*|$)", text, re.DOTALL)
        if m:
            thought = m.group(1).strip()

    if "Action:" not in text:
        return thought, []

    action_block = text.split("Action:", 1)[-1].strip()

    raw_actions = []
    # Multiple actions are separated by ")\n\n" per UI-TARS convention.
    for chunk in action_block.split(")\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.endswith(")"):
            chunk += ")"
        # Repair single-quote escaping inside type(content='...') so that
        # ast.parse can handle it.
        if chunk.startswith("type(content="):
            inner = re.match(r"type\(content='(.*)'\)\s*$", chunk, re.DOTALL)
            if inner:
                chunk = "type(content='" + _escape_single_quotes(inner.group(1)) + "')"
        raw_actions.append(chunk.replace("\n", "\\n"))

    parsed: List[Dict[str, Any]] = []
    for raw in raw_actions:
        call = _parse_call(raw)
        if call is None:
            continue
        parsed.append(call)
    return thought, parsed


def _box_to_xy(box_str: str) -> Optional[Tuple[float, float]]:
    """Parse ``(x,y)`` or ``(x1,y1,x2,y2)`` from action_parser output."""
    if not box_str:
        return None
    raw = box_str.strip()
    if raw.startswith("(") and raw.endswith(")"):
        nums = raw.strip("()").split(",")
    elif raw.startswith("[") and raw.endswith("]"):
        try:
            arr = json.loads(raw)
            return float(arr[0]), float(arr[1])
        except Exception:
            return None
    else:
        nums = raw.split(",")
    try:
        vals = [float(n.strip()) for n in nums if n.strip()]
    except ValueError:
        return None
    if len(vals) >= 4:
        return (vals[0] + vals[2]) / 2, (vals[1] + vals[3]) / 2
    if len(vals) >= 2:
        return vals[0], vals[1]
    return None


def _py_string(text: Any) -> str:
    return json.dumps("" if text is None else str(text), ensure_ascii=False)


class UITarsAgent(BaseAgent):
    """
    Agent driving ByteDance UI-TARS models via an OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        model: str = "UI-TARS-1.5-7B",
        api_backend: str = "openai",
        history_n: int = 5,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        top_p: float = 0.9,
        language: str = "English",
        input_swap: bool = True,
        **kwargs,
    ):
        super().__init__(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            **kwargs,
        )
        self.api_backend = api_backend
        self.history_n = max(1, int(history_n))
        self.language = language
        self.input_swap = bool(input_swap)

        self.responses: List[str] = []
        self.screenshots: List[str] = []  # base64 PNG strings (one per step)
        self.orig_sizes: List[Tuple[int, int]] = []

    # ── Public interface ────────────────────────────────────────────────

    def reset(self) -> None:
        self.responses = []
        self.screenshots = []
        self.orig_sizes = []
        self.last_raw_response = None

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        screenshot_bytes = obs["screenshot"]
        image = Image.open(BytesIO(screenshot_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        orig_w, orig_h = image.size

        b64 = _encode_image(screenshot_bytes)
        self.screenshots.append(b64)
        self.orig_sizes.append((orig_w, orig_h))

        messages = self._build_messages(instruction)

        response_text = self._call_llm(messages)
        logger.info("UI-TARS output: %s", response_text)
        self.responses.append(response_text or "")
        self.last_raw_response = {"content": response_text}

        thought, parsed = _parse_response(response_text or "")
        actions = self._parsed_to_pyautogui(parsed, orig_w, orig_h)

        reasoning = thought or ""
        if not reasoning and parsed:
            reasoning = f"UI-TARS action: {parsed[0].get('function')}"
        return reasoning, actions

    # ── Message construction ────────────────────────────────────────────

    def _build_messages(self, instruction: str) -> List[Dict[str, Any]]:
        sys_text = COMPUTER_USE_PROMPT.format(instruction=instruction).replace(
            "Use English in `Thought` part.",
            f"Use {self.language} in `Thought` part.",
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": [{"type": "text", "text": sys_text}]}
        ]

        total = len(self.screenshots)
        history_keep = min(self.history_n, total)
        start = total - history_keep

        for idx in range(start, total):
            img_url = f"data:image/png;base64,{self.screenshots[idx]}"
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": img_url}},
                    ],
                }
            )
            if idx < total - 1 and idx < len(self.responses):
                messages.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": self.responses[idx]}],
                    }
                )

        return messages

    # ── LLM call ────────────────────────────────────────────────────────

    def _call_llm(self, messages: List[Dict[str, Any]]) -> str:
        if self.api_backend != "openai":
            raise ValueError(f"Unknown api_backend for UI-TARS: {self.api_backend}")

        import openai

        base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:8001/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "empty")
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
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                logger.error("UI-TARS request failed (attempt %d): %s", attempt + 1, exc)
                if attempt < MAX_RETRY_TIMES - 1:
                    time.sleep(2 * (attempt + 1))
        return ""

    # ── Action translation ─────────────────────────────────────────────

    def _parsed_to_pyautogui(
        self,
        parsed: List[Dict[str, Any]],
        orig_w: int,
        orig_h: int,
    ) -> List[str]:
        if not parsed:
            return []

        # qwen25vl outputs absolute coords on the smart-resized canvas.
        try:
            sr_h, sr_w = _smart_resize(orig_h, orig_w)
        except ValueError:
            sr_h, sr_w = orig_h, orig_w

        def to_xy(point: Tuple[float, float]) -> Tuple[int, int]:
            x, y = point
            return int(round(x / sr_w * orig_w)), int(round(y / sr_h * orig_h))

        code: List[str] = []
        for action in parsed:
            atype = action["function"]
            args = action["args"] or {}

            if atype == "finished":
                code.append("DONE")
                continue
            if atype == "wait":
                code.append("WAIT")
                continue

            if atype in ("click", "left_single", "left_double", "right_single", "hover"):
                xy = _box_to_xy(str(args.get("start_box", "")))
                if not xy:
                    continue
                px, py = to_xy(xy)
                if atype in ("click", "left_single"):
                    code.append(f"pyautogui.click({px}, {py}, button='left')")
                elif atype == "left_double":
                    code.append(f"pyautogui.doubleClick({px}, {py}, button='left')")
                elif atype == "right_single":
                    code.append(f"pyautogui.click({px}, {py}, button='right')")
                elif atype == "hover":
                    code.append(f"pyautogui.moveTo({px}, {py})")

            elif atype in ("drag", "select"):
                start = _box_to_xy(str(args.get("start_box", "")))
                end = _box_to_xy(str(args.get("end_box", "")))
                if not (start and end):
                    continue
                sx, sy = to_xy(start)
                ex, ey = to_xy(end)
                code.append(f"pyautogui.moveTo({sx}, {sy})")
                code.append(f"pyautogui.dragTo({ex}, {ey}, duration=1.0)")

            elif atype == "scroll":
                xy = _box_to_xy(str(args.get("start_box", "")))
                direction = (args.get("direction") or "").lower()
                if "up" in direction:
                    delta = 5
                elif "down" in direction:
                    delta = -5
                else:
                    delta = 0
                if delta == 0:
                    continue
                if xy:
                    px, py = to_xy(xy)
                    code.append(f"pyautogui.scroll({delta}, x={px}, y={py})")
                else:
                    code.append(f"pyautogui.scroll({delta})")

            elif atype == "hotkey":
                hotkey = (args.get("key") or args.get("hotkey") or "").strip()
                if not hotkey:
                    continue
                key_map = {
                    "arrowleft": "left",
                    "arrowright": "right",
                    "arrowup": "up",
                    "arrowdown": "down",
                    "space": "space",
                }
                keys = [key_map.get(k, k) for k in hotkey.split()]
                keys_str = ", ".join(_py_string(k) for k in keys)
                if len(keys) > 1:
                    code.append(f"pyautogui.hotkey({keys_str})")
                elif keys:
                    code.append(f"pyautogui.press({keys_str})")

            elif atype in ("press", "keydown"):
                key = (args.get("key") or args.get("press") or "").strip()
                if key:
                    code.append(f"pyautogui.keyDown({_py_string(key)})")

            elif atype in ("release", "keyup"):
                key = (args.get("key") or args.get("press") or "").strip()
                if key:
                    code.append(f"pyautogui.keyUp({_py_string(key)})")

            elif atype == "type":
                content = args.get("content", "") or ""
                stripped = content
                ends_with_newline = stripped.endswith("\n") or stripped.endswith("\\n")
                if ends_with_newline:
                    stripped = stripped.rstrip("\\n").rstrip("\n")
                if not stripped:
                    if ends_with_newline:
                        code.append("pyautogui.press('enter')")
                    continue
                if self.input_swap:
                    code.append(
                        f"pyperclip.copy({_py_string(stripped)}); "
                        f"pyautogui.hotkey('ctrl', 'v'); time.sleep(0.5)"
                    )
                else:
                    code.append(f"pyautogui.write({_py_string(stripped)}, interval=0.1)")
                if ends_with_newline:
                    code.append("pyautogui.press('enter')")

            else:
                logger.warning("UI-TARS unsupported action %r (args=%s)", atype, args)

        return code
