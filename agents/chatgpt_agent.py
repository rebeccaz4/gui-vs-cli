"""
ChatGPT (OpenAI) computer-use agent.

Mirrors the OSWorld reference implementation in
``OSWorld/mm_agents/gpt54_agent.py``, wrapped in the ``BaseAgent``
interface used by this repo.

Three backends are supported:

* ``api_backend="openai"`` (default) — direct OpenAI Responses API.
  Env vars: ``OPENAI_API_KEY`` (required), ``OPENAI_BASE_URL`` (optional,
  for OpenAI-compatible proxies).
* ``api_backend="azure"`` — Azure OpenAI Responses API.
  Env vars: ``azure_api_key`` (or ``AZURE_OPENAI_API_KEY``),
  ``AZURE_OPENAI_ENDPOINT`` (optional override).
  ``model`` becomes the Azure *deployment name*.
* ``api_backend="bltcy"`` — bltcy.ai OpenAI-compatible proxy.
  Env var: ``bitcy_api_key`` (or ``BLTCY_API_KEY``). Base URL is
  hard-coded to ``https://api.bltcy.ai/v1`` but can be overridden
  via the ``base_url`` kwarg.

The newer GPT-5.x computer-use tool uses ``{"type": "computer"}`` and
returns batched actions via ``computer_call.actions``. The legacy
``computer-use-preview`` model uses
``{"type": "computer_use_preview", "display_width": ..., "display_height": ...,
"environment": ...}`` and returns a single ``computer_call.action``.
"""

import base64
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseAgent

logger = logging.getLogger("agents.chatgpt")

API_RETRY_TIMES = 5

# OpenAI-compatible proxy exposing the Responses API + computer tool.
# Auth via the `bitcy_api_key` env var.
BLTCY_BASE_URL = "https://api.bltcy.ai/v1"


OPERATOR_PROMPT = """

Here are some helpful tips:
- You are operating an {PLATFORM} desktop with internet access.
- My computer password is "{CLIENT_PASSWORD}" when sudo is needed.
- The current date is {CURRENT_DATE}.
- The home directory is "{HOME_DIR}".
- Stick to the website or application already opened for the task when possible.
- Prefer Chrome over Firefox/Chromium unless the task says otherwise.
- You can act without asking for confirmation.
- If content may be off-screen, scroll or zoom out before deciding it is unavailable.
- When possible, bundle multiple GUI actions into one computer-use turn.
- If the task is infeasible because of missing apps, permissions, contradictory requirements, or other hard blockers, output exactly "[INFEASIBLE]".
"""


def _encode_image(image_content: bytes) -> str:
    return base64.b64encode(image_content).decode("utf-8")


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if isinstance(value, list):
        return [_model_dump(item) for item in value]
    if isinstance(value, dict):
        return {k: _model_dump(v) for k, v in value.items()}
    return value


def _get_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _preview_text(text: str, limit: int = 120) -> str:
    sanitized = text.replace("\n", "\\n")
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[:limit] + "..."


def _sanitize_for_log(value: Any) -> Any:
    value = _model_dump(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if k == "image_url" and isinstance(v, str) and v.startswith("data:image/"):
                out[k] = "<image>"
            else:
                out[k] = _sanitize_for_log(v)
        return out
    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value]
    return value


class ChatGPTAgent(BaseAgent):
    """OpenAI Responses API computer-use agent — matches OSWorld gpt54_agent."""

    KEY_MAPPING = {
        "alt": "alt",
        "arrowdown": "down",
        "arrowleft": "left",
        "arrowright": "right",
        "arrowup": "up",
        "backspace": "backspace",
        "capslock": "capslock",
        "cmd": "command",
        "command": "command",
        "ctrl": "ctrl",
        "delete": "delete",
        "end": "end",
        "enter": "enter",
        "esc": "esc",
        "home": "home",
        "insert": "insert",
        "option": "option",
        "pagedown": "pagedown",
        "pageup": "pageup",
        "shift": "shift",
        "space": "space",
        "super": "super",
        "tab": "tab",
        "win": "win",
    }

    def __init__(
        self,
        model: str = "gpt-5.4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_backend: str = "openai",
        azure_endpoint: Optional[str] = None,
        azure_api_version: str = "preview",
        environment: str = "linux",
        reasoning_effort: str = "medium",
        reasoning_summary: str = "concise",
        truncation: str = "auto",
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        # OSWorld gpt54 defaults max_tokens to None; don't send one unless
        # the caller explicitly asked for it.
        kwargs.pop("max_tokens", None)
        super().__init__(model=model, max_tokens=max_tokens, **kwargs)

        self.api_backend = api_backend.lower()
        self.azure_endpoint = (
            azure_endpoint
            or os.environ.get("AZURE_OPENAI_ENDPOINT")
            or "https://bridg-mns6q12s-eastus2.cognitiveservices.azure.com/"
        )
        self.azure_api_version = azure_api_version

        if self.api_backend == "azure":
            self.api_key = (
                api_key
                or os.environ.get("azure_api_key")
                or os.environ.get("AZURE_OPENAI_API_KEY")
            )
            self.base_url = base_url
        elif self.api_backend == "bltcy":
            self.api_key = (
                api_key
                or os.environ.get("bitcy_api_key")
                or os.environ.get("BLTCY_API_KEY")
            )
            self.base_url = base_url or BLTCY_BASE_URL
        else:
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
            self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")

        self.environment = environment
        self.reasoning_effort = reasoning_effort
        self.reasoning_summary = reasoning_summary
        self.truncation = truncation

        # Tool spec: bare "computer" for GA; verbose for legacy preview.
        model_lower = self.model.lower()
        if "computer-use-preview" in model_lower:
            self.tools: List[Dict[str, Any]] = [
                {
                    "type": "computer_use_preview",
                    "display_width": self.screen_size[0],
                    "display_height": self.screen_size[1],
                    "environment": self.environment,
                }
            ]
        else:
            self.tools = [{"type": "computer"}]

        # Conversation chaining state (OSWorld parity).
        self.previous_response_id: Optional[str] = None
        self.pending_input_items: List[Dict[str, Any]] = []

    # ── Public interface ────────────────────────────────────────────────

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        instructions_text = self._system_prompt()
        screenshot_b64 = _encode_image(obs["screenshot"])

        if not self.previous_response_id:
            request_input: List[Dict[str, Any]] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instruction},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{screenshot_b64}",
                            "detail": "original",
                        },
                    ],
                }
            ]
        else:
            # Attach the fresh screenshot to each queued computer_call_output
            # and send them back to the Responses API.
            request_input = []
            for item in self.pending_input_items:
                item_copy = dict(item)
                item_copy["output"] = {
                    "type": "computer_screenshot",
                    "image_url": f"data:image/png;base64,{screenshot_b64}",
                    "detail": "original",
                }
                request_input.append(item_copy)
            self.pending_input_items = []
            if not request_input:
                # Previous turn was a bare assistant message (no computer_call)
                # — task is complete from the model's perspective.
                return "", ["DONE"]

        response = self._create_response(
            request_input, instructions_text, screenshot_b64
        )
        if response is None:
            return "", ["FAIL"]

        self.previous_response_id = _get_field(response, "id")

        try:
            self.last_raw_response = (
                response.model_dump()
                if hasattr(response, "model_dump")
                else _model_dump(response)
            )
        except Exception:
            self.last_raw_response = {"id": _get_field(response, "id")}

        reasoning_text, codes = self._parse_response(response)
        return reasoning_text, codes

    def reset(self) -> None:
        self.previous_response_id = None
        self.pending_input_items = []

    # ── Request helpers ─────────────────────────────────────────────────

    def _client(self):
        from openai import AzureOpenAI, OpenAI

        if self.api_backend == "azure":
            return AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.azure_endpoint,
                api_version=self.azure_api_version,
            )
        # "openai" (direct) and "bltcy" (OpenAI-compatible proxy) both use
        # the OpenAI client; base_url differs.
        if self.base_url:
            return OpenAI(api_key=self.api_key, base_url=self.base_url)
        return OpenAI(api_key=self.api_key)

    def _create_response(
        self,
        request_input: List[Dict[str, Any]],
        instructions: str,
        screenshot_b64: str,
    ):
        from openai import APIConnectionError, APIError, APIStatusError

        request: Dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": request_input,
            "tools": self.tools,
            "parallel_tool_calls": False,
            "truncation": self.truncation,
        }
        if self.reasoning_effort or self.reasoning_summary:
            reasoning: Dict[str, Any] = {}
            if self.reasoning_effort:
                reasoning["effort"] = self.reasoning_effort
            if self.reasoning_summary:
                reasoning["summary"] = self.reasoning_summary
            request["reasoning"] = reasoning
        if self.max_tokens:
            request["max_output_tokens"] = self.max_tokens
        if self.temperature is not None:
            request["temperature"] = self.temperature
        if self.top_p is not None:
            request["top_p"] = self.top_p
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id

        last_error: Optional[Exception] = None
        for attempt in range(API_RETRY_TIMES):
            try:
                client = self._client()
                logger.info(
                    "Sending %s request with previous_response_id=%s and %d input item(s)",
                    self.model,
                    self.previous_response_id,
                    len(request_input),
                )
                logger.debug(
                    "Request input items: %s", _sanitize_for_log(request_input)
                )
                response = client.responses.create(**request)
                err = _get_field(_get_field(response, "error", {}), "message")
                if err:
                    raise RuntimeError(err)
                if _get_field(response, "status") == "failed":
                    raise RuntimeError("Responses API request failed.")
                logger.debug(
                    "Raw response output: %s",
                    _sanitize_for_log(_get_field(response, "output", [])),
                )
                return response
            except (APIError, APIStatusError, APIConnectionError, RuntimeError) as e:
                last_error = e
                logger.error(
                    "OpenAI API error (attempt %d/%d): %s",
                    attempt + 1,
                    API_RETRY_TIMES,
                    e,
                )
                # Refresh the image on the last input item before retrying,
                # matching OSWorld's CUA retry behavior.
                last = request["input"][-1] if request["input"] else None
                if last:
                    if "output" in last and isinstance(last["output"], dict):
                        last["output"]["image_url"] = (
                            f"data:image/png;base64,{screenshot_b64}"
                        )
                    elif "content" in last and isinstance(last["content"], list):
                        for part in last["content"]:
                            if _get_field(part, "type") == "input_image":
                                part["image_url"] = (
                                    f"data:image/png;base64,{screenshot_b64}"
                                )
                                break
                time.sleep(min(5, (attempt + 1) * 2))

        logger.critical("OpenAI API failed too many times: %s", last_error)
        return None

    def _system_prompt(self) -> str:
        home_dir = (
            "C:\\Users\\user"
            if self.platform.lower().startswith("win")
            else "/home/user"
        )
        return OPERATOR_PROMPT.format(
            CLIENT_PASSWORD=self.password,
            CURRENT_DATE=datetime.now().strftime("%A, %B %d, %Y"),
            HOME_DIR=home_dir,
            PLATFORM=self.platform,
        )

    # ── Response parsing ────────────────────────────────────────────────

    def _parse_response(self, response) -> Tuple[str, List[str]]:
        raw_output = _get_field(response, "output", []) or []
        codes: List[str] = []
        responses: List[str] = []
        saw_message = False
        saw_call = False
        infeasible = False
        infeasible_words = (
            "[infeasible]",
            "infeasible",
            "unfeasible",
            "impossible",
            "cannot be done",
            "not feasible",
        )

        self.pending_input_items = []

        for item in raw_output:
            item_type = _get_field(item, "type")
            if item_type == "message":
                text = self._message_text(item)
                if text:
                    responses.append(text)
                    lower = text.lower()
                    if any(w in lower for w in infeasible_words):
                        infeasible = True
                saw_message = True
            elif item_type == "reasoning":
                rtext = self._reasoning_text(item)
                if rtext:
                    responses.append(rtext)
            elif item_type == "computer_call":
                saw_call = True
                raw_actions = _get_field(item, "actions")
                if raw_actions is None:
                    single = _get_field(item, "action")
                    raw_actions = [single] if single is not None else []
                raw_actions = list(raw_actions)

                call_id = _get_field(item, "call_id", "") or ""
                pending_checks = (
                    _model_dump(_get_field(item, "pending_safety_checks", [])) or []
                )

                for raw_action in raw_actions:
                    action_info = self._action_to_dict(raw_action)
                    logger.info(
                        "Raw tool action for call_id=%s: %s",
                        call_id,
                        _sanitize_for_log(action_info),
                    )
                    code = self._convert_action_to_pyautogui(
                        action_info["type"], action_info["args"]
                    )
                    if not code:
                        responses.append(
                            f"Unsupported computer action: {action_info['type']}"
                        )
                        continue
                    codes.append(code)

                # Queue one output per computer_call; predict() will fill in
                # the fresh screenshot on the next turn.
                output_item: Dict[str, Any] = {
                    "type": "computer_call_output",
                    "call_id": call_id,
                    "output": {
                        "type": "computer_screenshot",
                        "image_url": "",
                        "detail": "original",
                    },
                }
                if pending_checks:
                    output_item["acknowledged_safety_checks"] = pending_checks
                self.pending_input_items.append(output_item)

        reasoning = "\n".join(r for r in responses if r).strip()

        if infeasible:
            return reasoning, ["FAIL"]
        if not codes:
            if saw_message and not saw_call:
                return reasoning, ["DONE"]
            return reasoning, ["WAIT"]
        return reasoning, codes

    @staticmethod
    def _message_text(item: Any) -> str:
        content = _get_field(item, "content", [])
        if not content:
            return ""
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if _get_field(part, "type") == "output_text":
                    t = _get_field(part, "text", "")
                    if t:
                        parts.append(t)
            return "\n".join(parts)
        return str(content)

    @staticmethod
    def _reasoning_text(item: Any) -> str:
        summary = _get_field(item, "summary", [])
        if not summary:
            return ""
        if isinstance(summary, list):
            parts: List[str] = []
            for part in summary:
                t = _get_field(part, "text", "")
                if t:
                    parts.append(t)
            return "\n".join(parts)
        return str(summary)

    @staticmethod
    def _action_to_dict(action: Any) -> Dict[str, Any]:
        if isinstance(action, dict):
            action_type = action.get("type")
            args = {k: _model_dump(v) for k, v in action.items() if k != "type"}
            return {"type": action_type, "args": args}
        if hasattr(action, "model_dump"):
            try:
                raw = action.model_dump()
                action_type = raw.get("type")
                args = {k: _model_dump(v) for k, v in raw.items() if k != "type"}
                return {"type": action_type, "args": args}
            except Exception:
                pass
        if hasattr(action, "to_dict"):
            try:
                raw = action.to_dict()
                action_type = raw.get("type")
                args = {k: _model_dump(v) for k, v in raw.items() if k != "type"}
                return {"type": action_type, "args": args}
            except Exception:
                pass
        action_type = getattr(action, "type", None)
        args: Dict[str, Any] = {}
        for attr in dir(action):
            if attr.startswith("_") or attr == "type":
                continue
            try:
                args[attr] = _model_dump(getattr(action, attr))
            except Exception:
                continue
        return {"type": action_type, "args": args}

    # ── Action → pyautogui translation (matches OSWorld gpt54_agent) ────

    def _convert_action_to_pyautogui(
        self, action_type: Optional[str], args: Dict[str, Any]
    ) -> Optional[str]:
        if not action_type:
            return None
        try:
            if action_type == "click":
                x = args.get("x")
                y = args.get("y")
                button = args.get("button", "left")
                if x is None or y is None:
                    return None
                if button not in ("left", "middle", "right"):
                    button = "left"
                return (
                    f"import pyautogui\n"
                    f"pyautogui.moveTo({x}, {y})\n"
                    f"pyautogui.click(button='{button}')"
                )

            if action_type == "double_click":
                x = args.get("x")
                y = args.get("y")
                if x is None or y is None:
                    return None
                return (
                    f"import pyautogui\n"
                    f"pyautogui.moveTo({x}, {y})\n"
                    f"pyautogui.doubleClick()"
                )

            if action_type == "move":
                x = args.get("x")
                y = args.get("y")
                if x is None or y is None:
                    return None
                return f"import pyautogui\npyautogui.moveTo({x}, {y})"

            if action_type == "drag":
                return self._convert_drag_path(args)

            if action_type == "type":
                text = args.get("text", "")
                summary = self._summarize_type_payload(text)
                logger.info("Type action payload: %s", summary)
                if text == "":
                    return "import time\ntime.sleep(0.1)"
                strategy = summary["strategy"]
                if strategy == "multiline_ascii":
                    return self._build_multiline_ascii_type_command(text)
                if strategy == "clipboard":
                    return self._build_clipboard_paste_command(text)
                return (
                    f"import pyautogui\n"
                    f"pyautogui.typewrite({repr(text)}, interval=0.03)"
                )

            if action_type == "keypress":
                keys = args.get("keys")
                if not keys and args.get("key"):
                    keys = [args.get("key")]
                if not keys:
                    return None
                if not isinstance(keys, (list, tuple)):
                    keys = [keys]
                mapped = [
                    self.KEY_MAPPING.get(str(k).lower(), str(k).lower())
                    for k in keys
                ]
                keys_str = ", ".join(repr(k) for k in mapped)
                return f"import pyautogui\npyautogui.hotkey({keys_str})"

            if action_type == "scroll":
                x = args.get("x")
                y = args.get("y")
                scroll_x = int(
                    args.get("scroll_x")
                    or args.get("delta_x")
                    or args.get("deltaX")
                    or 0
                )
                scroll_y = int(
                    args.get("scroll_y")
                    or args.get("delta_y")
                    or args.get("deltaY")
                    or 0
                )
                position = (
                    f", x={x}, y={y}" if x is not None and y is not None else ""
                )
                if scroll_y:
                    return (
                        f"import pyautogui\n"
                        f"pyautogui.scroll({scroll_y * -1}{position})"
                    )
                if scroll_x:
                    return (
                        f"import pyautogui\n"
                        f"pyautogui.hscroll({scroll_x * -1}{position})"
                    )
                return None

            if action_type == "wait":
                secs = max(0.1, float(args.get("ms", 1000)) / 1000.0)
                return f"import time\ntime.sleep({secs})"

            if action_type == "screenshot":
                return "import time\ntime.sleep(0.1)"
        except Exception:
            logger.exception("Failed to convert computer action: %s", action_type)
            return None

        logger.warning("Unsupported computer action: %s", action_type)
        return None

    @staticmethod
    def _convert_drag_path(args: Dict[str, Any]) -> Optional[str]:
        path = args.get("path")
        if not path and args.get("from") and args.get("to"):
            path = [args["from"], args["to"]]
        if not path or len(path) < 2:
            return None

        def point_xy(p: Any) -> Tuple[Any, Any]:
            if isinstance(p, (list, tuple)) and len(p) == 2:
                return p[0], p[1]
            if isinstance(p, dict):
                return p.get("x"), p.get("y")
            return getattr(p, "x", None), getattr(p, "y", None)

        first_x, first_y = point_xy(path[0])
        if first_x is None or first_y is None:
            return None

        lines = [f"import pyautogui\npyautogui.moveTo({first_x}, {first_y})"]
        for p in path[1:]:
            x, y = point_xy(p)
            if x is None or y is None:
                return None
            lines.append(f"pyautogui.dragTo({x}, {y}, duration=0.2, button='left')")
        return "\n".join(lines)

    @staticmethod
    def _typing_strategy(text: str) -> str:
        if text == "":
            return "empty"
        if not text.isascii():
            return "clipboard"
        if "\n" in text:
            return "multiline_ascii"
        if text.isascii():
            return "single_line_ascii"
        return "clipboard"

    def _summarize_type_payload(self, text: str) -> Dict[str, Any]:
        return {
            "strategy": self._typing_strategy(text),
            "chars": len(text),
            "lines": len(text.split("\n")) if text else 0,
            "ascii": text.isascii(),
            "trailing_newline": text.endswith("\n"),
            "preview": _preview_text(text),
        }

    @staticmethod
    def _build_multiline_ascii_type_command(text: str) -> str:
        lines = ["import pyautogui"]
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if part:
                lines.append(f"pyautogui.typewrite({repr(part)}, interval=0.03)")
            if i < len(parts) - 1:
                lines.append("pyautogui.press('enter')")
        return "\n".join(lines)

    @staticmethod
    def _build_clipboard_paste_command(
        text: str, paste_keys: Tuple[str, ...] = ("ctrl", "v")
    ) -> str:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        keys = ", ".join(repr(k) for k in paste_keys)
        return (
            "import base64, time, pyautogui, pyperclip\n"
            f"_text = base64.b64decode('{encoded}').decode('utf-8')\n"
            "pyperclip.copy(_text)\n"
            "time.sleep(0.1)\n"
            f"pyautogui.hotkey({keys})\n"
            "time.sleep(0.1)"
        )
