"""
Gemini (Google AI Studio) general-desktop computer-use agent.

This agent mirrors the *protocol* used in
``gym-anything/agents/agents/claude_gemini.py`` (class ``Gemini3Agent``): we
do NOT use Gemini's native ``computer_use`` tool — that tool is
``ENVIRONMENT_BROWSER``-scoped and only exposes browser primitives
(``navigate``, ``go_back``, ``search``, …). Instead we ship a generic desktop
tool spec inside the system prompt and parse a ``<tool_call>…</tool_call>``
JSON block from the model's text response. Coordinates are emitted on a
0-1000 normalized grid and rescaled to ``self.screen_size`` before we emit
pyautogui calls so it plugs into the same E2B execution pipeline as the
other agents in this folder.

Unlike gym-anything (which calls Gemini through ``litellm``), this file calls
the model via the ``google-genai`` SDK that the rest of the repo already uses.
The protocol (system prompt + ``<tool_call>`` parsing + action vocabulary) is
the part that matches gym-anything.

Env vars:
  google_ai_studio_api_key   (preferred, matches the user's .env naming)
  GOOGLE_AI_STUDIO_API_KEY   (uppercase alias)
  GEMINI_API_KEY             (fallback)
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseAgent

logger = logging.getLogger("agents.gemini")

API_RETRY_TIMES = 5
API_RETRY_INTERVAL = 5

DEFAULT_MODEL = "gemini-3-flash-preview"


# Generic desktop tool spec — lifted from gym-anything/agents/shared/prompts.py
# (TOOL_DEFINITIONS) so the model's output vocabulary matches that codebase.
TOOL_DEFINITIONS: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "computer_use",
        "description": (
            "Use a mouse and keyboard to interact with a computer, and take screenshots.\n"
            "* This is an interface to a desktop GUI. You do not have access to a terminal "
            "or applications menu. You must click on desktop icons to start applications.\n"
            "* Some applications may take time to start or process actions, so you may need "
            "to wait and take successive screenshots to see the results of your actions. "
            "E.g. if you click on Firefox and a window doesn't open, try wait and taking "
            "another screenshot.\n"
            "* The screen's resolution is 1280x720.\n"
            "* Whenever you intend to move the cursor to click on an element like an icon, "
            "you should consult a screenshot to determine the coordinates of the element "
            "before moving the cursor.\n"
            "* If you tried clicking on a program or link but it failed to load even after "
            "waiting, try adjusting your cursor position so that the tip of the cursor "
            "visually falls on the element that you want to click.\n"
            "* Make sure to click any buttons, links, icons, etc with the cursor tip in the "
            "center of the element. Don't click boxes on their edges unless asked."
        ),
        "parameters": {
            "properties": {
                "action": {
                    "description": (
                        "The action to perform. The available actions are:\n"
                        "* `key`: Performs key down presses on the arguments passed in "
                        "order, then performs key releases in reverse order.\n"
                        "* `type`: Type a string of text on the keyboard.\n"
                        "* `mouse_move`: Move the cursor to a specified (x, y) pixel "
                        "coordinate on the screen.\n"
                        "* `click`: Click the left mouse button at a specified (x, y) "
                        "pixel coordinate on the screen.\n"
                        "* `left_click`: Click the left mouse button at a specified "
                        "(x, y) pixel coordinate on the screen.\n"
                        "* `drag`: Click and drag the cursor to a specified (x, y) pixel "
                        "coordinate on the screen.\n"
                        "* `right_click`: Click the right mouse button at a specified "
                        "(x, y) pixel coordinate on the screen.\n"
                        "* `middle_click`: Click the middle mouse button at a specified "
                        "(x, y) pixel coordinate on the screen.\n"
                        "* `double_click`: Double-click the left mouse button at a "
                        "specified (x, y) pixel coordinate on the screen.\n"
                        "* `scroll`: Performs a scroll of the mouse scroll wheel.\n"
                        "* `wait`: Wait specified seconds for the change to happen.\n"
                        "* `terminate`: Terminate the current task and report its "
                        "completion status."
                    ),
                    "enum": [
                        "key", "type", "mouse_move", "click", "left_click", "drag",
                        "right_click", "middle_click", "double_click", "scroll",
                        "wait", "terminate",
                    ],
                    "type": "string",
                },
                "keys": {"description": "Required only by `action=key`.", "type": "array"},
                "text": {"description": "Required only by `action=type`.", "type": "string"},
                "coordinate": {"description": "The x,y coordinates for mouse actions.", "type": "array"},
                "coordinate2": {
                    "description": "The x2,y2 coordinates for drag end position. Required only by `action=drag`.",
                    "type": "array",
                },
                "pixels": {"description": "The amount of scrolling.", "type": "number"},
                "time": {"description": "The seconds to wait.", "type": "number"},
                "status": {
                    "description": "The status of the task.",
                    "type": "string",
                    "enum": ["success", "failure"],
                },
            },
            "required": ["action"],
            "type": "object",
        },
    },
}


# System prompt template — lifted from gym-anything's
# ``GEMINI_SYSTEM_PROMPT_SINGLE_STEP`` and lightly extended with our
# date / sudo-password / infeasibility conventions.
GEMINI_SYSTEM_PROMPT_SINGLE_STEP = """<SYSTEM_CAPABILITY>
* You are utilising an virtual machine with internet access.
* You can feel free to do anything.
* Each turn you will be provided current screenshot of the screen.
* If you want to run a specific gui application, make sure to set the display variable to :1.
* When using your computer function calls, they take a while to run and send back to you.
* Enclose your tool call inside <tool_call></tool_call> tags.
* Important: Only use one tool call per turn.
* The current date is {date}. The sudo password, if asked, is '{password}'.
* If you determine that the task cannot be completed, output exactly "[INFEASIBLE]" (with brackets) anywhere in your reply — do not emit a tool call that turn.

You have access to the following tools:
<<TOOL_DEFINITIONS>>

Example tool call usage:

```
....thinking....
....response....

<tool_call>
{{"name": "computer_use", "arguments": {{"action": "click", "coordinate": [100, 200]}}}}
</tool_call>
```

The above example would make 1 tool call and click at coordinate [100, 200].

</SYSTEM_CAPABILITY>"""


class GeminiAgent(BaseAgent):
    """Gemini agent using gym-anything's generic-desktop text-tool protocol."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        thinking_budget: Optional[int] = None,
        history_n: int = 10,
        max_tokens: int = 16384,
        **kwargs,
    ):
        super().__init__(model=model, max_tokens=max_tokens, **kwargs)
        self.api_key = (
            api_key
            or os.environ.get("google_ai_studio_api_key")
            or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )

        self.thinking_budget = thinking_budget
        self.history_n = history_n

        # ``contents`` is a list of ``google.genai.types.Content`` alternating
        # user ↔ model turns. Built lazily inside predict() so we don't import
        # the SDK at module load.
        self.contents: list = []

    # ── Public interface ────────────────────────────────────────────────

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        from google import genai
        from google.genai import types

        if not self.api_key:
            raise RuntimeError(
                "Gemini API key not set. Export google_ai_studio_api_key in your "
                "environment or pass api_key=... to GeminiAgent."
            )

        screenshot_bytes = obs["screenshot"]

        # First turn: user message with instruction + first screenshot.
        # Subsequent turns: append a user message containing just the new screenshot.
        if not self.contents:
            self.contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=instruction),
                        types.Part.from_bytes(
                            data=screenshot_bytes, mime_type="image/png"
                        ),
                    ],
                )
            )
        else:
            self.contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(
                            data=screenshot_bytes, mime_type="image/png"
                        ),
                    ],
                )
            )

        self._trim_image_history(self.history_n)

        sys_text = GEMINI_SYSTEM_PROMPT_SINGLE_STEP.format(
            date=datetime.today().strftime("%A, %B %d, %Y"),
            password=self.password,
        ).replace("<<TOOL_DEFINITIONS>>", json.dumps(TOOL_DEFINITIONS))

        config_kwargs: Dict[str, Any] = {
            "system_instruction": sys_text,
            "temperature": self.temperature if self.temperature is not None else 1.0,
            "top_p": self.top_p if self.top_p is not None else 0.95,
            "max_output_tokens": self.max_tokens,
        }
        if self.thinking_budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=self.thinking_budget
            )
        config = types.GenerateContentConfig(**config_kwargs)

        client = genai.Client(api_key=self.api_key)

        response = None
        last_err: Optional[Exception] = None
        for attempt in range(API_RETRY_TIMES):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=self.contents,
                    config=config,
                )
                break
            except Exception as e:
                last_err = e
                logger.warning("Gemini API error (attempt %d): %s", attempt + 1, e)
                if attempt < API_RETRY_TIMES - 1:
                    time.sleep(API_RETRY_INTERVAL)

        if response is None:
            logger.error("All %d Gemini API attempts failed: %s", API_RETRY_TIMES, last_err)
            return "", ["FAIL"]

        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            return "", ["FAIL"]

        # Keep the raw model Content in history so the SDK can round-trip it.
        self.contents.append(candidate.content)

        # Flatten all text parts into a single string. A ``thought=True`` part
        # (reasoning, when enabled) is wrapped in <think>…</think> so that
        # ``_parse_response`` treats it as reasoning rather than body text.
        text_chunks: List[str] = []
        for part in candidate.content.parts or []:
            t = getattr(part, "text", None)
            if not t:
                continue
            if getattr(part, "thought", False):
                text_chunks.append(f"<think>{t}</think>")
            else:
                text_chunks.append(t)
        full_text = "\n".join(text_chunks)

        try:
            self.last_raw_response = response.model_dump()
        except Exception:
            self.last_raw_response = {"text": full_text}

        reasoning, actions, is_terminal = self._parse_response(full_text)

        if "[INFEASIBLE]" in full_text:
            return reasoning, ["FAIL"]
        if is_terminal:
            return reasoning, ["DONE"]
        if not actions:
            return reasoning, ["WAIT"]
        return reasoning, actions

    def reset(self) -> None:
        self.contents = []
        self.last_raw_response = None

    # ── Private helpers ─────────────────────────────────────────────────

    def _trim_image_history(self, keep_images: int) -> None:
        """Remove the oldest inline-image parts once we exceed ``keep_images``
        screenshots. We fully drop the image part (Gemini rejects a Part whose
        inline_data blob is empty), and if a Content ends up with no usable
        parts left we drop the whole Content too."""
        if keep_images <= 0:
            return

        # (content_idx, part_idx) for every inline-image part, oldest first.
        image_refs: List[Tuple[int, int]] = []
        for ci, content in enumerate(self.contents):
            for pi, part in enumerate(content.parts or []):
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    image_refs.append((ci, pi))

        drop = len(image_refs) - keep_images
        if drop <= 0:
            return

        # Track indices to drop per content, then apply in a second pass so the
        # part_idx values stay valid.
        to_drop: Dict[int, List[int]] = {}
        for ci, pi in image_refs[:drop]:
            to_drop.setdefault(ci, []).append(pi)

        kept_contents = []
        for ci, content in enumerate(self.contents):
            drop_pis = set(to_drop.get(ci, []))
            if not drop_pis:
                kept_contents.append(content)
                continue
            new_parts = [
                p for pi, p in enumerate(content.parts or []) if pi not in drop_pis
            ]
            # Only keep parts that still carry either text or a real blob.
            new_parts = [
                p for p in new_parts
                if (getattr(p, "text", None))
                or (getattr(p, "inline_data", None) is not None
                    and getattr(p.inline_data, "data", None))
                or getattr(p, "function_call", None) is not None
                or getattr(p, "function_response", None) is not None
            ]
            if not new_parts:
                # Whole turn is gone — skip it entirely.
                continue
            content.parts = new_parts
            kept_contents.append(content)

        self.contents = kept_contents

    def _parse_response(self, text: str) -> Tuple[str, List[str], bool]:
        """Extract reasoning text + pyautogui strings from the model's reply.

        Returns ``(reasoning, actions, is_terminal)``. If the model emits a
        ``terminate`` tool call, ``is_terminal`` is True and ``actions`` is
        empty. Unparseable / missing tool calls yield an empty action list so
        the caller falls back to WAIT.
        """
        if not text or not isinstance(text, str):
            return "", [], False

        # Split out <think>...</think> reasoning if present.
        reasoning = ""
        body = text
        if "</think>" in body:
            reasoning, _, body = body.partition("</think>")
            reasoning = reasoning.replace("<think>", "").strip()

        # Pull out the <tool_call>...</tool_call> JSON block if present.
        raw_call: Optional[str] = None
        if "<tool_call>" in body and "</tool_call>" in body:
            raw_call = body.split("<tool_call>")[-1].split("</tool_call>")[0].strip()
        else:
            # Fallback: try to pluck a bare {"name": "computer_use", ...} out.
            marker = '{"name": "computer_use"'
            if marker in body:
                try:
                    raw_call = marker + body.split(marker, 1)[1].split("}}")[0] + "}}"
                except Exception:
                    raw_call = None

        pre_call_text = body.split("<tool_call>")[0].strip() if "<tool_call>" in body else body.strip()
        if not reasoning:
            reasoning = pre_call_text
        elif pre_call_text:
            reasoning = f"{reasoning}\n{pre_call_text}".strip()

        if raw_call is None:
            return reasoning, [], False

        try:
            parsed = json.loads(raw_call)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse tool_call JSON: %s raw=%r", e, raw_call[:200])
            return reasoning, [], False

        if "arguments" in parsed:
            action_json = parsed["arguments"]
        elif "action" in parsed:
            action_json = parsed
        else:
            logger.warning("tool_call missing 'arguments'/'action' keys: %s", parsed)
            return reasoning, [], False

        if action_json.get("action") == "terminate":
            # status=success → DONE, status=failure → let caller treat as DONE too
            # (falling through to DONE matches gym-anything's terminal handling).
            return reasoning, [], True

        try:
            code = self._action_json_to_pyautogui(action_json)
        except Exception as e:
            logger.warning("Failed to translate action %s: %s", action_json, e)
            return reasoning, [], False

        if code is None:
            return reasoning, [], False
        if isinstance(code, str) and code in {"WAIT", "DONE", "FAIL"}:
            return reasoning, [code], code == "DONE"
        return reasoning, [code], False

    def _denorm(self, coord: Any) -> Tuple[int, int]:
        """Scale a 0-1000 grid coordinate to self.screen_size pixels.

        Matches gym-anything's ``convert_point_format_qwen3vl`` with
        ``scale_dims_ratio=(screen_w/1000, screen_h/1000)``.
        """
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            return 0, 0
        sw, sh = self.screen_size
        x = int(float(coord[0]) * sw / 1000.0)
        y = int(float(coord[1]) * sh / 1000.0)
        return x, y

    _KEY_ALIASES = {
        "control": "ctrl",
        "cmd": "command",
        "esc": "escape",
        "return": "enter",
        "del": "delete",
        "super": "win",
    }

    def _norm_keys(self, keys: List[str]) -> List[str]:
        out: List[str] = []
        for k in keys:
            if not isinstance(k, str):
                continue
            kl = k.strip().lower()
            out.append(self._KEY_ALIASES.get(kl, kl))
        return out

    def _action_json_to_pyautogui(self, a: Dict[str, Any]) -> Optional[str]:
        """Translate a gym-anything-style action dict into a pyautogui code
        string (or one of the special tokens ``WAIT``/``DONE``/``FAIL``)."""
        action = a.get("action")

        if action in {"click", "left_click"}:
            x, y = self._denorm(a.get("coordinate"))
            return f"pyautogui.click({x}, {y})\n"

        if action == "right_click":
            x, y = self._denorm(a.get("coordinate"))
            return f"pyautogui.rightClick({x}, {y})\n"

        if action == "middle_click":
            x, y = self._denorm(a.get("coordinate"))
            return f"pyautogui.middleClick({x}, {y})\n"

        if action == "double_click":
            x, y = self._denorm(a.get("coordinate"))
            return f"pyautogui.doubleClick({x}, {y})\n"

        if action == "mouse_move":
            x, y = self._denorm(a.get("coordinate"))
            return f"pyautogui.moveTo({x}, {y}, duration=0.3)\n"

        if action == "drag":
            x1, y1 = self._denorm(a.get("coordinate"))
            x2, y2 = self._denorm(a.get("coordinate2") or a.get("coordinate"))
            return (
                f"pyautogui.moveTo({x1}, {y1}, duration=0.3)\n"
                f"pyautogui.dragTo({x2}, {y2}, duration=0.5, button='left')\n"
            )

        if action == "type":
            text = a.get("text", "") or ""
            lines = []
            if a.get("clear"):
                lines.append(
                    "pyautogui.keyDown('ctrl'); pyautogui.press('a'); "
                    "pyautogui.keyUp('ctrl')"
                )
                lines.append("pyautogui.press('delete')")
            lines.append(f"pyperclip.copy({text!r})")
            lines.append(
                "pyautogui.keyDown('ctrl'); pyautogui.press('v'); "
                "pyautogui.keyUp('ctrl')"
            )
            if a.get("enter"):
                lines.append("pyautogui.press('enter')")
            return "\n".join(lines) + "\n"

        if action == "key":
            keys = a.get("keys") or []
            if isinstance(keys, str):
                keys = [keys]
            keys = self._norm_keys(list(keys))
            if not keys:
                return "WAIT"
            if len(keys) == 1:
                return f"pyautogui.press({keys[0]!r})\n"
            return f"pyautogui.hotkey({', '.join(repr(k) for k in keys)})\n"

        if action == "scroll":
            # gym-anything passes `pixels` (or legacy `scroll`). Positive →
            # scroll up in pyautogui, negative → scroll down.
            pixels = a.get("pixels")
            if pixels is None:
                pixels = a.get("scroll", 0)
            try:
                amount = int(pixels)
            except Exception:
                amount = 0
            if a.get("coordinate"):
                x, y = self._denorm(a.get("coordinate"))
                return f"pyautogui.scroll({amount}, {x}, {y})\n"
            return f"pyautogui.scroll({amount})\n"

        if action == "wait":
            try:
                t = float(a.get("time", 1.0))
            except Exception:
                t = 1.0
            return f"time.sleep({t})\n"

        if action == "terminate":
            status = a.get("status", "success")
            return "FAIL" if status == "failure" else "DONE"

        logger.info("Unhandled Gemini action_json: %s", a)
        return "WAIT"
