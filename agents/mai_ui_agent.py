"""
MAI-UI agent — adapted from MAI-UI/src/mai_naivigation_agent.py.

MAI-UI is a family of GUI agent models from Alibaba Tongyi (2B / 8B / 32B / 235B).
The model emits responses in the form

    <thinking>...</thinking>
    <tool_call>{"name": "mobile_use", "arguments": {"action": ..., ...}}</tool_call>

with coordinates on a 999x999 normalized grid. We rescale to the original
screenshot dimensions and translate the action vocabulary into pyautogui code
that the framework's sandbox executor can run.

Env vars (OpenAI-compatible vLLM endpoint):
  OPENAI_BASE_URL   e.g. http://localhost:8000/v1
  OPENAI_API_KEY    any string ("empty" works for vLLM)

Typical launch (per MAI-UI/README.md):
  python -m vllm.entrypoints.openai.api_server \
      --model Tongyi-MAI/MAI-UI-8B \
      --served-model-name MAI-UI-8B --host 0.0.0.0 --port 8000 \
      --tensor-parallel-size 1 --trust-remote-code

  python evaluation/run_eval.py --model mai-ui-8b --endpoint-port 8000
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import re
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.mai_ui")

MAX_RETRY_TIMES = 3
SCALE_FACTOR = 999

# MAI-UI ships a mobile-style system prompt. We keep the same output contract
# (thinking + mobile_use tool_call) so the model stays in distribution, then
# translate the emitted action into desktop pyautogui inside this agent.
MAI_UI_SYSTEM_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
For each function call, return the thinking process in <thinking> </thinking> tags, and a json object with function name and arguments within <tool_call></tool_call> XML tags:
```
<thinking>
...
</thinking>
<tool_call>
{"name": "mobile_use", "arguments": <args-json-object>}
</tool_call>
```

## Action Space

{"action": "click", "coordinate": [x, y]}
{"action": "double_click", "coordinate": [x, y]}
{"action": "long_press", "coordinate": [x, y]}
{"action": "type", "text": ""}
{"action": "swipe", "direction": "up or down or left or right", "coordinate": [x, y]}  # "coordinate" is optional.
{"action": "drag", "start_coordinate": [x1, y1], "end_coordinate": [x2, y2]}
{"action": "system_button", "button": "button_name"}  # Options: back, home, menu, enter
{"action": "wait"}
{"action": "terminate", "status": "success or fail"}
{"action": "answer", "text": "xxx"}

## Note
- Coordinates are in a 999x999 grid, so x and y must be integers in [0, 999].
- Write a small plan and finally summarize your next action (with its target element) in one sentence in <thinking></thinking>.
- You must follow the Action Space strictly, and return the correct json object within <thinking></thinking> and <tool_call></tool_call> XML tags.
""".strip()


def _resize_for_model(image_bytes: bytes, max_pixels: int = 4_000_000) -> Tuple[str, int, int, int, int]:
    """Return (base64_png, orig_w, orig_h, proc_w, proc_h)."""
    image = Image.open(BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    orig_w, orig_h = image.size

    px = orig_w * orig_h
    if px > max_pixels:
        import math
        scale = math.sqrt(max_pixels / px)
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
        image = image.resize((new_w, new_h))

    buf = BytesIO()
    image.save(buf, format="PNG")
    return (
        base64.b64encode(buf.getvalue()).decode("utf-8"),
        orig_w,
        orig_h,
        image.size[0],
        image.size[1],
    )


def _parse_tagged(text: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extract the <thinking> block and the JSON tool_call payload."""
    if not text:
        return None, None
    if "</think>" in text and "</thinking>" not in text:
        text = text.replace("</think>", "</thinking>")
        if "<thinking>" not in text:
            text = "<thinking>" + text

    thinking_match = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    thinking = thinking_match.group(1).strip() if thinking_match else None

    tool_call: Optional[Dict[str, Any]] = None
    for tc_match in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        body = tc_match.group(1).strip().strip('"')
        try:
            tool_call = json.loads(body)
            break
        except json.JSONDecodeError:
            continue

    if tool_call is None:
        # Fallback: bare JSON line containing "name": "mobile_use"
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("{") and stripped.endswith("}") and "mobile_use" in stripped:
                try:
                    tool_call = json.loads(stripped)
                    break
                except json.JSONDecodeError:
                    continue

    return thinking, tool_call


def _py_string(text: Any) -> str:
    return json.dumps("" if text is None else str(text), ensure_ascii=False)


class MAIUIAgent(BaseAgent):
    """
    Agent driving Alibaba's MAI-UI models via an OpenAI-compatible endpoint.

    The model emits ``<thinking>...</thinking><tool_call>{...}</tool_call>``
    blocks with coordinates on a 999x999 grid; we rescale to the original
    screenshot, then emit pyautogui code strings that the framework's
    BaseAgent.execute_action runs in the sandbox.
    """

    def __init__(
        self,
        model: str = "MAI-UI-8B",
        api_backend: str = "openai",
        history_n: int = 3,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        top_p: float = 1.0,
        top_k: int = -1,
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
        self.top_k = int(top_k)

        # Rolling history (assistant responses + processed screenshots).
        self.responses: List[str] = []
        self.screenshots: List[str] = []

    # ── Public interface ────────────────────────────────────────────────

    def reset(self) -> None:
        self.responses = []
        self.screenshots = []
        self.last_raw_response = None

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        screenshot_bytes = obs["screenshot"]

        b64, orig_w, orig_h, _proc_w, _proc_h = _resize_for_model(screenshot_bytes)
        self.screenshots.append(b64)

        messages = self._build_messages(instruction)

        response_text = self._call_llm(messages)
        logger.info("MAI-UI output: %s", response_text)
        self.responses.append(response_text or "")
        self.last_raw_response = {"content": response_text}

        thinking, tool_call = _parse_tagged(response_text or "")
        reasoning, actions = self._tool_call_to_pyautogui(
            thinking, tool_call, orig_w, orig_h
        )
        return reasoning, actions

    # ── Message construction ────────────────────────────────────────────

    def _build_messages(self, instruction: str) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": [{"type": "text", "text": MAI_UI_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "text", "text": instruction}]},
        ]

        total = len(self.screenshots)
        history_keep = min(self.history_n, total)
        start = total - history_keep  # index of first kept screenshot

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
            raise ValueError(f"Unknown api_backend for MAI-UI: {self.api_backend}")

        import openai

        base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "empty")
        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=600)

        extra_body: Dict[str, Any] = {"repetition_penalty": 1.0}
        if self.top_k is not None and self.top_k >= 0:
            extra_body["top_k"] = self.top_k

        for attempt in range(MAX_RETRY_TIMES):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature if self.temperature is not None else 0.0,
                    top_p=self.top_p if self.top_p is not None else 1.0,
                    extra_body=extra_body,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                logger.error("MAI-UI request failed (attempt %d): %s", attempt + 1, exc)
                if attempt < MAX_RETRY_TIMES - 1:
                    time.sleep(2 * (attempt + 1))
        return ""

    # ── Action translation ─────────────────────────────────────────────

    def _tool_call_to_pyautogui(
        self,
        thinking: Optional[str],
        tool_call: Optional[Dict[str, Any]],
        orig_w: int,
        orig_h: int,
    ) -> Tuple[str, List[str]]:
        reasoning = (thinking or "").strip()
        code: List[str] = []

        if not tool_call:
            return reasoning or "no parsable action", code

        args = (tool_call or {}).get("arguments") or {}
        action = args.get("action")

        def to_xy(coord: Any) -> Optional[Tuple[int, int]]:
            if not isinstance(coord, (list, tuple)):
                return None
            if len(coord) == 2:
                cx, cy = coord
            elif len(coord) == 4:
                x1, y1, x2, y2 = coord
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            else:
                return None
            try:
                fx = float(cx) / SCALE_FACTOR
                fy = float(cy) / SCALE_FACTOR
            except (TypeError, ValueError):
                return None
            return int(fx * orig_w), int(fy * orig_h)

        if action == "click":
            xy = to_xy(args.get("coordinate"))
            code.append(f"pyautogui.click({xy[0]}, {xy[1]})" if xy else "pyautogui.click()")

        elif action == "double_click":
            xy = to_xy(args.get("coordinate"))
            code.append(
                f"pyautogui.doubleClick({xy[0]}, {xy[1]})" if xy else "pyautogui.doubleClick()"
            )

        elif action == "long_press":
            xy = to_xy(args.get("coordinate"))
            duration = args.get("time", 1.0)
            try:
                duration = float(duration)
            except (TypeError, ValueError):
                duration = 1.0
            if xy:
                code.append(f"pyautogui.moveTo({xy[0]}, {xy[1]})")
                code.append(f"pyautogui.mouseDown(); time.sleep({duration}); pyautogui.mouseUp()")
            else:
                code.append(f"pyautogui.mouseDown(); time.sleep({duration}); pyautogui.mouseUp()")

        elif action == "type":
            text = args.get("text", "")
            code.append(
                f"pyperclip.copy({_py_string(text)}); "
                f"pyautogui.hotkey('ctrl', 'v'); time.sleep(0.1)"
            )

        elif action == "swipe":
            direction = (args.get("direction") or "").lower()
            xy = to_xy(args.get("coordinate"))
            amount = 5
            if direction in ("up", "right"):
                step = amount
            else:  # down, left, or unknown → scroll down
                step = -amount
            if xy:
                code.append(f"pyautogui.moveTo({xy[0]}, {xy[1]})")
            code.append(f"pyautogui.scroll({step})")

        elif action == "drag":
            start = to_xy(args.get("start_coordinate"))
            end = to_xy(args.get("end_coordinate"))
            if start and end:
                code.append(f"pyautogui.moveTo({start[0]}, {start[1]})")
                code.append(f"pyautogui.dragTo({end[0]}, {end[1]}, duration=0.5)")

        elif action == "system_button":
            button = (args.get("button") or "").lower()
            mapping = {
                "back": "escape",
                "home": "win",
                "menu": "menu",
                "enter": "enter",
            }
            key = mapping.get(button)
            if key:
                code.append(f"pyautogui.press({_py_string(key)})")

        elif action == "open":
            # MAI-UI's mobile-only `open app_name` has no desktop equivalent in
            # the sandbox launcher. Emit a no-op so the run doesn't crash.
            app_name = args.get("text") or args.get("app_name") or ""
            logger.warning("MAI-UI 'open' action ignored on desktop: %s", app_name)

        elif action == "wait":
            code.append("WAIT")

        elif action == "terminate":
            status = (args.get("status") or "").lower()
            code.append("DONE" if status != "fail" else "FAIL")

        elif action == "answer":
            # Treat answer as task completion.
            code.append("DONE")

        elif action is None:
            logger.warning("MAI-UI tool_call missing 'action': %s", args)

        else:
            logger.warning("MAI-UI unsupported action %r (args=%s)", action, args)

        if not reasoning:
            if action:
                reasoning = f"MAI-UI action: {action}"
            else:
                reasoning = "no parsable action"

        return reasoning, code
