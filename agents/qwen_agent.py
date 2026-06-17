"""
Qwen agent — supports Qwen 2.5-VL, Qwen 3-VL, and Qwen 3.5 models
via DashScope or OpenAI-compat API.

Qwen 3.5 uses an XML tool-call format (<function=...><parameter=...>) per
the official OSWorld agent, while earlier models use JSON inside <tool_call>.

Env vars required (pick one):
  DASHSCOPE_API_KEY + DASHSCOPE_BASE_URL   (for DashScope native)
  OPENAI_API_KEY + OPENAI_BASE_URL         (for OpenAI-compatible endpoint)
"""

import base64
import json
import logging
import math
import os
import re
import time
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.qwen")

MAX_RETRY_TIMES = 5


def _is_qwen3_family(model: str) -> bool:
    """Return True for Qwen 3 / 3.5 style model IDs, including HF paths."""
    normalized = (model or "").strip().lower()
    tail = normalized.rsplit("/", 1)[-1]
    return tail.startswith("qwen3")


def _is_qwen35_family(model: str) -> bool:
    """Return True for Qwen 3.5 model IDs (use XML tool-call format)."""
    normalized = (model or "").strip().lower()
    tail = normalized.rsplit("/", 1)[-1]
    return tail.startswith("qwen3.5") or tail.startswith("qwen35")


def _smart_resize(height: int, width: int, factor: int = 28, min_pixels: int = 56 * 56, max_pixels: int = 16384 * 28 * 28) -> Tuple[int, int]:
    """Resize dimensions to be divisible by factor while respecting pixel limits."""
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


def _process_image(image_bytes: bytes, factor: int = 32, max_pixels: int = 16 * 16 * 4 * 12800) -> str:
    """Resize and encode an image for Qwen VL models."""
    image = Image.open(BytesIO(image_bytes))
    w, h = image.size
    new_h, new_w = _smart_resize(h, w, factor=factor, max_pixels=max_pixels)
    image = image.resize((new_w, new_h))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── Tool definition (shared by Qwen 2.5 and 3) ─────────────────────────

def _tools_def(description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name_for_human": "computer_use",
            "name": "computer_use",
            "description": description,
            "parameters": {
                "properties": {
                    "action": {
                        "description": (
                            "* `key`: Press key(s).\n"
                            "* `type`: Type text.\n"
                            "* `mouse_move`: Move cursor.\n"
                            "* `left_click`: Left click.\n"
                            "* `left_click_drag`: Click and drag.\n"
                            "* `right_click`: Right click.\n"
                            "* `middle_click`: Middle click.\n"
                            "* `double_click`: Double click.\n"
                            "* `scroll`: Scroll.\n"
                            "* `wait`: Wait.\n"
                            "* `terminate`: End task."
                        ),
                        "enum": [
                            "key", "type", "mouse_move", "left_click",
                            "left_click_drag", "right_click", "middle_click",
                            "double_click", "scroll", "wait", "terminate",
                        ],
                        "type": "string",
                    },
                    "keys": {"description": "Required only by `action=key`.", "type": "array"},
                    "text": {"description": "Required only by `action=type`.", "type": "string"},
                    "coordinate": {"description": "The x,y coordinates.", "type": "array"},
                    "pixels": {"description": "Scroll amount.", "type": "number"},
                    "time": {"description": "Seconds to wait.", "type": "number"},
                    "status": {
                        "description": "Task status.",
                        "type": "string",
                        "enum": ["success", "failure"],
                    },
                },
                "required": ["action"],
                "type": "object",
            },
            "args_format": "Format the arguments as a JSON object.",
        },
    }


SYSTEM_PROMPT_TEMPLATE = """# Tools

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
2) A single <tool_call>...</tool_call> block containing only the JSON: {{"name": <function-name>, "arguments": <args-json-object>}}.

Rules:
- Output exactly in the order: Action, <tool_call>.
- Be brief: one sentence for Action.
- Do not output anything else outside those parts.
- If finishing, use action=terminate in the tool call."""

# Qwen 3.5 uses XML parameter format per the official OSWorld agent
SYSTEM_PROMPT_TEMPLATE_35 = (
    "You are a multi-purpose intelligent assistant. Based on my requests, "
    "you can use tools to help me complete various tasks.\n\n"
    "# Tools\n\n"
    "You have access to the following functions:\n\n"
    "<tools>\n"
    "{tools_json}\n"
    "</tools>\n\n"
    "If you choose to call a function ONLY reply in the following format with NO suffix:\n\n"
    "<tool_call>\n"
    "<function=example_function_name>\n"
    "<parameter=example_parameter_1>\n"
    "value_1\n"
    "</parameter>\n"
    "<parameter=example_parameter_2>\n"
    "This is the value for the second parameter\n"
    "that can span\n"
    "multiple lines\n"
    "</parameter>\n"
    "</function>\n"
    "</tool_call>\n\n"
    "<IMPORTANT>\n"
    "Reminder:\n"
    "- Function calls MUST follow the specified format: an inner <function=...></function> "
    "block must be nested within <tool_call></tool_call> XML tags\n"
    "- Required parameters MUST be specified\n"
    "- You may provide optional reasoning for your function call in natural language "
    "BEFORE the function call, but NOT after\n"
    "- If there is no function call available, answer the question like normal with your "
    "current knowledge and do not tell the user about function calls\n"
    "- The current date is {current_date}.\n"
    "</IMPORTANT>\n\n"
    "# Response format\n\n"
    "Response format for every step:\n"
    "1) Action: a short imperative describing what to do in the UI.\n"
    "2) A single <tool_call>...</tool_call> block.\n\n"
    "Rules:\n"
    "- Output exactly in the order: Action, <tool_call>.\n"
    "- Be brief: one sentence for Action.\n"
    "- Do not output anything else outside those parts.\n"
    "- If finishing, use action=terminate in the tool call."
)


class QwenAgent(BaseAgent):
    """
    Agent powered by Qwen VL models (2.5 and 3 series) and Qwen 3.5.

    Qwen 2.5/3: JSON tool-call format inside <tool_call> tags.
    Qwen 3.5: XML tool-call format (<function=...><parameter=...>) per OSWorld.
    """

    COLLAPSED_SCREENSHOT_TEXT = "This screenshot has been collapsed."

    def __init__(
        self,
        model: str = "qwen3-vl",
        api_backend: str = "dashscope",
        coordinate_type: str = "relative",
        history_n: int = 4,
        enable_thinking: bool = False,
        thinking_budget: int = 32768,
        image_max: int = 20,
        fold_size: int = 10,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.api_backend = api_backend  # "dashscope" or "openai"
        self.coordinate_type = coordinate_type
        self.history_n = history_n
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget
        self.is_35 = _is_qwen35_family(model)
        self.image_max = int(image_max)
        self.fold_size = int(fold_size)

        self.actions: List[str] = []
        self.responses: List[str] = []
        self.screenshots: List[str] = []  # base64 encoded processed screenshots
        self.folded_prefix_k = 0

    # ── Public interface ────────────────────────────────────────────────

    def _update_folding_state(self, total_screenshots: int) -> None:
        """Fold old screenshots to stay under image_max budget."""
        while (total_screenshots - self.folded_prefix_k) > self.image_max:
            self.folded_prefix_k += self.fold_size
        if self.folded_prefix_k > total_screenshots:
            self.folded_prefix_k = total_screenshots

    def _should_collapse_step(self, step_num_1based: int) -> bool:
        return step_num_1based <= self.folded_prefix_k

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        screenshot_bytes = obs["screenshot"]

        # Get original dimensions
        orig_img = Image.open(BytesIO(screenshot_bytes))
        orig_w, orig_h = orig_img.size

        # Process image for Qwen
        processed_b64 = _process_image(screenshot_bytes)
        proc_img = Image.open(BytesIO(base64.b64decode(processed_b64)))
        proc_w, proc_h = proc_img.size

        self.screenshots.append(processed_b64)

        if self.is_35:
            self._update_folding_state(len(self.screenshots))

        # Build messages
        messages = self._build_messages(instruction, processed_b64)

        # Call LLM
        response = self._call_llm(messages)
        logger.info(f"Qwen output: {response}")
        self.responses.append(response or "")

        # Store raw response for logging
        self.last_raw_response = {"content": response}

        # Parse response
        low_level, code = self._parse_response(
            response or "", orig_w, orig_h, proc_w, proc_h
        )
        self.actions.append(low_level)

        return low_level, code

    def reset(self) -> None:
        self.actions = []
        self.responses = []
        self.screenshots = []
        self.folded_prefix_k = 0

    # ── Message construction ────────────────────────────────────────────

    @staticmethod
    def _wrap_tool_response(parts: List[Dict]) -> List[Dict]:
        """Wrap screenshot parts in <tool_response> tags for Qwen 3.5."""
        return (
            [{"type": "text", "text": "<tool_response>\n"}]
            + parts
            + [{"type": "text", "text": "\n</tool_response>"}]
        )

    def _build_messages(self, instruction: str, current_screenshot_b64: str) -> list:
        if self.is_35:
            return self._build_messages_35(instruction, current_screenshot_b64)
        return self._build_messages_legacy(instruction, current_screenshot_b64)

    def _build_messages_legacy(self, instruction: str, current_screenshot_b64: str) -> list:
        """Build messages for Qwen 2.5/3 (JSON tool-call format)."""
        if self.coordinate_type == "absolute":
            proc_img = Image.open(BytesIO(base64.b64decode(current_screenshot_b64)))
            res_text = f"The screen's resolution is {proc_img.size[0]}x{proc_img.size[1]}."
        else:
            res_text = "The screen's resolution is 1000x1000."

        description = (
            "Use a mouse and keyboard to interact with a computer, and take screenshots.\n"
            "* This is an interface to a desktop GUI.\n"
            f"* {res_text}\n"
            "* Consult a screenshot to determine coordinates before clicking.\n"
            "* Click the center of elements, not edges."
        )
        tools_json = json.dumps(_tools_def(description))
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tools_json=tools_json)

        current_step = len(self.actions)
        history_start = max(0, current_step - self.history_n)

        prev_actions = []
        for i in range(history_start):
            if i < len(self.actions):
                prev_actions.append(f"Step {i + 1}: {self.actions[i]}")
        prev_actions_str = "\n".join(prev_actions) if prev_actions else "None"

        instruction_prompt = (
            f"Please generate the next move according to the UI screenshot, "
            f"instruction and previous actions.\n\n"
            f"Instruction: {instruction}\n\n"
            f"Previous actions:\n{prev_actions_str}"
        )

        messages = [
            {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
        ]

        history_len = min(self.history_n, len(self.responses))
        if history_len > 0:
            history_responses = self.responses[-history_len:]
            history_screenshots = self.screenshots[-history_len - 1 : -1]

            for idx in range(history_len):
                if idx < len(history_screenshots):
                    img_url = f"data:image/png;base64,{history_screenshots[idx]}"
                    if idx == 0:
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": img_url}},
                                    {"type": "text", "text": instruction_prompt},
                                ],
                            }
                        )
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": img_url}},
                                ],
                            }
                        )
                messages.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": history_responses[idx]}],
                    }
                )

            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{current_screenshot_b64}"},
                        }
                    ],
                }
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{current_screenshot_b64}"},
                        },
                        {"type": "text", "text": instruction_prompt},
                    ],
                }
            )

        return messages

    def _build_messages_35(self, instruction: str, current_screenshot_b64: str) -> list:
        """Build messages for Qwen 3.5 (XML tool-call format, image folding)."""
        proc_img = Image.open(BytesIO(base64.b64decode(current_screenshot_b64)))
        proc_w, proc_h = proc_img.size

        if self.coordinate_type == "absolute":
            res_text = f"The screen's resolution is {proc_w}x{proc_h}."
        else:
            res_text = "The screen's resolution is 1000x1000."

        description_lines = [
            "Use a mouse and keyboard to interact with a computer, and take screenshots.",
            "* This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.",
            "* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions.",
            f"* {res_text}",
            "* Whenever you intend to move the cursor to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.",
            "* If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.",
            "* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked.",
        ]
        description = "\n".join(description_lines)

        action_description = (
            "* `key`: Performs key down presses on the arguments passed in order, then performs key releases in reverse order.\n"
            "* `type`: Type a string of text on the keyboard.\n"
            "* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.\n"
            "* `left_click`: Click the left mouse button. Optional `text` parameter for modifier keys.\n"
            "* `left_click_drag`: Click and drag the cursor to a specified (x, y) coordinate.\n"
            "* `right_click`: Click the right mouse button. Optional `text` parameter for modifier keys.\n"
            "* `middle_click`: Click the middle mouse button. Optional `text` parameter for modifier keys.\n"
            "* `double_click`: Double-click the left mouse button. Optional `text` parameter for modifier keys.\n"
            "* `triple_click`: Triple-click the left mouse button.\n"
            "* `scroll`: Performs a scroll of the mouse scroll wheel. Optional `text` for modifier key.\n"
            "* `wait`: Wait specified seconds for the change to happen.\n"
            "* `terminate`: Terminate the current task and report its completion status.\n"
            "* `answer`: Answer a question."
        )

        tools_def_35 = {
            "type": "function",
            "function": {
                "name": "computer_use",
                "description": description,
                "parameters": {
                    "type": "object",
                    "required": ["action"],
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": action_description,
                            "enum": [
                                "key", "type", "mouse_move", "left_click",
                                "left_click_drag", "right_click", "middle_click",
                                "double_click", "triple_click", "scroll",
                                "wait", "terminate", "answer",
                            ],
                        },
                        "keys": {"type": "array", "description": "Required only by `action=key`."},
                        "text": {
                            "type": "string",
                            "description": (
                                "Required by `action=type` and `action=answer`. Optional for click/scroll "
                                "actions to specify modifier keys (e.g., 'ctrl', 'shift', 'ctrl+shift')."
                            ),
                        },
                        "coordinate": {"type": "array", "description": "(x, y) coordinates."},
                        "pixels": {"type": "number", "description": "Scroll amount."},
                        "time": {"type": "number", "description": "Seconds to wait."},
                        "status": {
                            "type": "string",
                            "description": "Task status for terminate.",
                            "enum": ["success", "failure"],
                        },
                    },
                },
            },
        }

        tools_json = json.dumps(tools_def_35)
        system_prompt = SYSTEM_PROMPT_TEMPLATE_35.format(
            tools_json=tools_json,
            current_date=datetime.today().strftime("%A, %B %d, %Y"),
        )

        total_steps = len(self.screenshots)
        start_step = max(1, total_steps - self.history_n)

        prev_actions = [
            f"Step {i + 1}: {self.actions[i]}"
            for i in range(0, min(start_step - 1, len(self.actions)))
        ]
        prev_actions_str = "\n".join(prev_actions) if prev_actions else "None"

        instruction_prompt = (
            f"\nPlease generate the next move according to the UI screenshot, "
            f"instruction and previous actions.\n\n"
            f"Instruction: {instruction}\n\n"
            f"Previous actions:\n{prev_actions_str}"
        )

        messages: List[Dict] = [
            {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
        ]

        for step_num in range(start_step, total_steps + 1):
            is_first_turn = step_num == start_step
            is_collapsed = self._should_collapse_step(step_num)

            if is_collapsed:
                if is_first_turn:
                    user_content = [{"type": "text", "text": instruction_prompt}]
                else:
                    user_content = self._wrap_tool_response(
                        [{"type": "text", "text": self.COLLAPSED_SCREENSHOT_TEXT}]
                    )
                messages.append({"role": "user", "content": user_content})
            else:
                img_url = f"data:image/png;base64,{self.screenshots[step_num - 1]}"
                if is_first_turn:
                    user_content = [
                        {"type": "image_url", "image_url": {"url": img_url}},
                        {"type": "text", "text": instruction_prompt},
                    ]
                else:
                    user_content = self._wrap_tool_response(
                        [{"type": "image_url", "image_url": {"url": img_url}}]
                    )
                messages.append({"role": "user", "content": user_content})

            if step_num <= total_steps - 1 and (step_num - 1) < len(self.responses):
                messages.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": self.responses[step_num - 1]}],
                    }
                )

        return messages

    # ── LLM call ────────────────────────────────────────────────────────

    def _call_llm(self, messages: list) -> Optional[str]:
        if self.api_backend == "openai":
            return self._call_openai(messages)
        elif self.api_backend == "dashscope":
            return self._call_dashscope(messages)
        else:
            raise ValueError(f"Unknown API backend: {self.api_backend}")

    @staticmethod
    def _extract_content_text(content) -> str:
        """Normalize message.content (string, list-of-parts, or None) to a string."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if "text" in part:
                        parts.append(part.get("text", ""))
                else:
                    text = getattr(part, "text", None)
                    if text:
                        parts.append(text)
            return "".join(parts)
        return str(content)

    @staticmethod
    def _reconstruct_from_tool_calls(tool_calls) -> str:
        """Reconstruct text from native API tool_calls when content is null.

        vLLM auto-parses <tool_call> XML and moves data to message.tool_calls,
        leaving message.content as None.  We reconstruct the text so the parser
        can process it normally.
        """
        if not tool_calls:
            return ""
        parts = []
        for tc in tool_calls:
            func = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)
            if not func:
                continue
            name = getattr(func, "name", None) or (func.get("name") if isinstance(func, dict) else None)
            args_str = getattr(func, "arguments", None) or (func.get("arguments") if isinstance(func, dict) else None)
            if not name:
                continue
            # Try to parse arguments and reconstruct in XML format for Qwen 3.5
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
            except (json.JSONDecodeError, TypeError):
                args = {}

            param_lines = []
            for k, v in args.items():
                val = json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                param_lines.append(f"<parameter={k}>\n{val}\n</parameter>")
            params_block = "\n".join(param_lines)
            parts.append(
                f"<tool_call>\n<function={name}>\n{params_block}\n</function>\n</tool_call>"
            )
        return "\n".join(parts)

    def _call_openai(self, messages: list) -> str:
        import openai

        base_url = os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "sk-123")
        client = openai.OpenAI(base_url=base_url, api_key=api_key)

        for attempt in range(MAX_RETRY_TIMES):
            try:
                extra_body = {}
                if _is_qwen3_family(self.model):
                    extra_body["enable_thinking"] = self.enable_thinking
                    if self.enable_thinking:
                        extra_body["thinking_budget"] = self.thinking_budget

                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    extra_body=extra_body,
                )
                msg = resp.choices[0].message
                text = self._extract_content_text(msg.content)
                if not text:
                    tool_calls = getattr(msg, "tool_calls", None)
                    if tool_calls:
                        logger.info("Content was null; reconstructing from tool_calls")
                        text = self._reconstruct_from_tool_calls(tool_calls)
                return text
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
                call_params = {
                    "model": self.model,
                    "messages": ds_messages,
                    "max_tokens": self.max_tokens,
                    "vl_high_resolution_images": True,
                }
                if _is_qwen3_family(self.model):
                    call_params["enable_thinking"] = self.enable_thinking
                    if self.enable_thinking:
                        call_params["thinking_budget"] = self.thinking_budget

                resp = MultiModalConversation.call(**call_params)

                if getattr(resp, "status_code", None) not in (None, HTTPStatus.OK):
                    logger.warning(f"DashScope non-OK: {getattr(resp, 'code', '')} {getattr(resp, 'message', '')}")
                    time.sleep(1.5 * (attempt + 1))
                    continue

                text = self._extract_dashscope_text(resp)
                if not text:
                    raise ValueError("Empty DashScope response")
                return text

            except Exception as e:
                logger.error(f"DashScope error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRY_TIMES - 1:
                    time.sleep(1.5 * (attempt + 1))
        return ""

    # ── Response parsing ────────────────────────────────────────────────

    @staticmethod
    def _py_string(text: str) -> str:
        return json.dumps("" if text is None else str(text), ensure_ascii=False)

    def _parse_response(
        self,
        response: str,
        orig_w: int,
        orig_h: int,
        proc_w: int,
        proc_h: int,
    ) -> Tuple[str, List[str]]:
        """Dispatch to format-specific parser."""
        if self.is_35:
            return self._parse_response_xml(response, orig_w, orig_h, proc_w, proc_h)
        return self._parse_response_json(response, orig_w, orig_h, proc_w, proc_h)

    def _parse_response_json(
        self,
        response: str,
        orig_w: int,
        orig_h: int,
        proc_w: int,
        proc_h: int,
    ) -> Tuple[str, List[str]]:
        """Parse JSON tool calls inside <tool_call> tags (Qwen 2.5/3)."""
        low_level = ""
        code: List[str] = []

        if not response or not response.strip():
            return low_level, code

        def adjust(x: float, y: float) -> Tuple[int, int]:
            if self.coordinate_type == "absolute":
                if proc_w and proc_h:
                    return int(x * orig_w / proc_w), int(y * orig_h / proc_h)
                return int(x), int(y)
            return int(x * orig_w / 999), int(y * orig_h / 999)

        def process_tool_call(json_str: str) -> None:
            try:
                tc = json.loads(json_str)
                if tc.get("name") != "computer_use":
                    return
                args = tc["arguments"]
                action = args["action"]

                if action == "left_click":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        code.append(f"pyautogui.click({ax}, {ay})")
                    else:
                        code.append("pyautogui.click()")

                elif action == "right_click":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        code.append(f"pyautogui.rightClick({ax}, {ay})")
                    else:
                        code.append("pyautogui.rightClick()")

                elif action == "middle_click":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        code.append(f"pyautogui.middleClick({ax}, {ay})")
                    else:
                        code.append("pyautogui.middleClick()")

                elif action == "double_click":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        code.append(f"pyautogui.doubleClick({ax}, {ay})")
                    else:
                        code.append("pyautogui.doubleClick()")

                elif action == "triple_click":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        code.append(f"pyautogui.tripleClick({ax}, {ay})")
                    else:
                        code.append("pyautogui.tripleClick()")

                elif action == "type":
                    text = args.get("text", "")
                    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
                    code.append(f"pyperclip.copy('{escaped}'); pyautogui.hotkey('ctrl', 'v'); time.sleep(0.1)")

                elif action == "key":
                    keys = args.get("keys", [])
                    if isinstance(keys, list):
                        cleaned_keys = []
                        for key in keys:
                            if isinstance(key, str):
                                if key.startswith("keys=["):
                                    key = key[6:]
                                if key.endswith("]"):
                                    key = key[:-1]
                                if key.startswith("['") or key.startswith('["'):
                                    key = key[2:] if len(key) > 2 else key
                                if key.endswith("']") or key.endswith('"]'):
                                    key = key[:-2] if len(key) > 2 else key
                                key = key.strip()
                                cleaned_keys.append(key)
                            else:
                                cleaned_keys.append(key)
                        keys = cleaned_keys
                    keys_str = ", ".join(f"'{k}'" for k in keys)
                    if len(keys) > 1:
                        code.append(f"pyautogui.hotkey({keys_str})")
                    else:
                        code.append(f"pyautogui.press({keys_str})")

                elif action == "scroll":
                    pixels = args.get("pixels", 0)
                    code.append(f"pyautogui.scroll({pixels})")

                elif action == "wait":
                    code.append("WAIT")

                elif action == "terminate":
                    code.append("DONE")

                elif action == "mouse_move":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        code.append(f"pyautogui.moveTo({ax}, {ay})")
                    else:
                        code.append("pyautogui.moveTo(0, 0)")

                elif action == "left_click_drag":
                    if "coordinate" in args:
                        x, y = args["coordinate"]
                        ax, ay = adjust(x, y)
                        dur = args.get("duration", 0.5)
                        code.append(f"pyautogui.dragTo({ax}, {ay}, duration={dur})")
                    else:
                        code.append("pyautogui.dragTo(0, 0)")

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse tool call: {e}")

        lines = response.split("\n")
        inside_tc = False
        tc_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.lower().startswith(("action:", "step", "i will", "i'll", "now i")):
                if not low_level:
                    low_level = stripped
                continue

            if stripped.startswith("<tool_call>") or stripped.startswith("\u2697") or stripped.startswith("\U0001f4d0"):
                inside_tc = True
                continue
            elif stripped.startswith("</tool_call>") or stripped.startswith("\u2697") or stripped.startswith("\U0001f4d0"):
                if tc_lines:
                    process_tool_call("\n".join(tc_lines))
                    tc_lines = []
                inside_tc = False
                continue

            if inside_tc:
                tc_lines.append(stripped)
                continue

            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    obj = json.loads(stripped)
                    if "name" in obj and "arguments" in obj:
                        process_tool_call(stripped)
                except json.JSONDecodeError:
                    pass

        if tc_lines:
            process_tool_call("\n".join(tc_lines))

        if not low_level and code:
            low_level = f"Performing {code[0].split('.', 1)[1].split('(', 1)[0]} action"

        return low_level, code

    def _parse_response_xml(
        self,
        response: str,
        orig_w: int,
        orig_h: int,
        proc_w: int,
        proc_h: int,
    ) -> Tuple[str, List[str]]:
        """Parse XML tool calls for Qwen 3.5 (<function=computer_use><parameter=...>).

        Also handles JSON tool calls as fallback, since the model may produce
        either format depending on serving configuration.
        """
        low_level = ""
        code: List[str] = []

        if not response or not response.strip():
            return low_level, code

        def adjust(x: float, y: float) -> Tuple[int, int]:
            if self.coordinate_type == "absolute":
                if proc_w and proc_h:
                    return int(x * orig_w / proc_w), int(y * orig_h / proc_h)
                return int(x), int(y)
            return int(x * orig_w / 999), int(y * orig_h / 999)

        def parse_xml_tool_call(xml_content: str) -> Optional[Dict]:
            func_match = re.search(r"<function=([^>]+)>", xml_content)
            if not func_match or func_match.group(1) != "computer_use":
                return None
            params: Dict = {}
            for match in re.finditer(
                r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>",
                xml_content,
                re.DOTALL,
            ):
                name = match.group(1)
                value = match.group(2).strip()
                if value.startswith("[") or value.startswith("{"):
                    try:
                        params[name] = json.loads(value)
                        continue
                    except json.JSONDecodeError:
                        pass
                params[name] = value
            return params

        def parse_json_tool_call(json_str: str) -> Optional[Dict]:
            """Fallback: parse JSON tool calls if model outputs JSON format."""
            try:
                tc = json.loads(json_str)
                if tc.get("name") != "computer_use":
                    return None
                return tc.get("arguments", {})
            except (json.JSONDecodeError, KeyError):
                return None

        def parse_keys(raw_keys):
            if isinstance(raw_keys, str):
                try:
                    raw_keys = json.loads(raw_keys)
                except Exception:
                    raw_keys = [raw_keys]
            if isinstance(raw_keys, list):
                return [str(key).strip() for key in raw_keys]
            return [str(raw_keys).strip()]

        def parse_coordinate(raw_coord):
            if isinstance(raw_coord, str):
                try:
                    raw_coord = json.loads(raw_coord)
                except Exception:
                    return None
            if isinstance(raw_coord, list) and len(raw_coord) >= 2:
                return raw_coord[0], raw_coord[1]
            return None

        def process_params(params: Dict) -> None:
            action = params.get("action")
            if not action:
                return

            coordinate = parse_coordinate(params.get("coordinate"))
            text = params.get("text")

            def press_modifier_keys() -> None:
                if text:
                    for key in str(text).split("+"):
                        key = key.strip().lower()
                        if key:
                            code.append(f"pyautogui.keyDown({self._py_string(key)})")

            def release_modifier_keys() -> None:
                if text:
                    keys = [k.strip().lower() for k in str(text).split("+") if k.strip()]
                    for key in reversed(keys):
                        code.append(f"pyautogui.keyUp({self._py_string(key)})")

            if action == "left_click":
                press_modifier_keys()
                if coordinate:
                    x, y = adjust(*coordinate)
                    code.append(f"pyautogui.click({x}, {y})")
                else:
                    code.append("pyautogui.click()")
                release_modifier_keys()
            elif action == "right_click":
                press_modifier_keys()
                if coordinate:
                    x, y = adjust(*coordinate)
                    code.append(f"pyautogui.rightClick({x}, {y})")
                else:
                    code.append("pyautogui.rightClick()")
                release_modifier_keys()
            elif action == "middle_click":
                press_modifier_keys()
                if coordinate:
                    x, y = adjust(*coordinate)
                    code.append(f"pyautogui.middleClick({x}, {y})")
                else:
                    code.append("pyautogui.middleClick()")
                release_modifier_keys()
            elif action == "double_click":
                press_modifier_keys()
                if coordinate:
                    x, y = adjust(*coordinate)
                    code.append(f"pyautogui.doubleClick({x}, {y})")
                else:
                    code.append("pyautogui.doubleClick()")
                release_modifier_keys()
            elif action == "triple_click":
                press_modifier_keys()
                if coordinate:
                    x, y = adjust(*coordinate)
                    code.append(f"pyautogui.doubleClick({x}, {y})")
                else:
                    code.append("pyautogui.doubleClick()")
                release_modifier_keys()
            elif action == "type":
                text_val = params.get("text", "")
                code.append(
                    f"pyperclip.copy({self._py_string(text_val)}); "
                    f"pyautogui.hotkey('ctrl', 'v'); time.sleep(0.1)"
                )
            elif action == "key":
                keys = parse_keys(params.get("keys", []))
                keys_str = ", ".join(self._py_string(k) for k in keys)
                if len(keys) > 1:
                    code.append(f"pyautogui.hotkey({keys_str})")
                else:
                    code.append(f"pyautogui.press({keys_str})")
            elif action in {"scroll", "hscroll"}:
                press_modifier_keys()
                pixels = params.get("pixels", 0)
                try:
                    pixels = int(float(pixels))
                except Exception:
                    pixels = 0
                code.append(f"pyautogui.scroll({pixels})")
                release_modifier_keys()
            elif action == "wait":
                code.append("WAIT")
            elif action in {"terminate", "answer"}:
                code.append("DONE")
            elif action == "mouse_move":
                if coordinate:
                    x, y = adjust(*coordinate)
                    code.append(f"pyautogui.moveTo({x}, {y})")
                else:
                    code.append("pyautogui.moveTo(0, 0)")
            elif action == "left_click_drag":
                if coordinate:
                    x, y = adjust(*coordinate)
                    duration = 0.5
                    if "duration" in params:
                        try:
                            duration = float(params["duration"])
                        except Exception:
                            duration = 0.5
                    code.append(f"pyautogui.dragTo({x}, {y}, duration={duration})")
                else:
                    code.append("pyautogui.dragTo(0, 0)")

        # Extract Action: line
        for line in response.split("\n"):
            stripped = line.strip()
            if stripped.lower().startswith("action:"):
                low_level = stripped.split("Action:", 1)[-1].strip()
                break

        # Try XML parsing first (native Qwen 3.5 format)
        for tc_match in re.finditer(r"<tool_call>(.*?)</tool_call>", response, re.DOTALL):
            tc_content = tc_match.group(1)
            params = parse_xml_tool_call(tc_content)
            if params:
                process_params(params)
            else:
                # Fallback: try JSON parsing within the tool_call block
                json_params = parse_json_tool_call(tc_content.strip())
                if json_params:
                    process_params(json_params)

        # If no tool_call tags found, try bare JSON objects
        if not code:
            for line in response.split("\n"):
                stripped = line.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    json_params = parse_json_tool_call(stripped)
                    if json_params:
                        process_params(json_params)

        if not low_level and code:
            first_code = code[0]
            if first_code == "DONE":
                low_level = "Task completed"
            elif first_code == "WAIT":
                low_level = "Waiting"
            elif "." in first_code:
                low_level = f"Performing {first_code.split('.', 1)[1].split('(', 1)[0]} action"
            else:
                low_level = "Performing action"

        return low_level, code

    # ── DashScope helpers ───────────────────────────────────────────────

    @staticmethod
    def _to_dashscope_messages(messages: list) -> list:
        ds = []
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
            ds.append({"role": role, "content": dc})
        return ds

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

        reasoning = getattr(msg, "reasoning_content", None) if not isinstance(msg, dict) else msg.get("reasoning_content")

        if content:
            text = "".join(p.get("text", "") for p in content if isinstance(p, dict) and "text" in p)
        else:
            text = ""

        # Check for tool_calls when content is empty (same issue as OpenAI-compat)
        if not text:
            tool_calls = getattr(msg, "tool_calls", None) if not isinstance(msg, dict) else msg.get("tool_calls")
            if tool_calls:
                text = QwenAgent._reconstruct_from_tool_calls(tool_calls)

        if reasoning:
            return f"<think>\n{reasoning}\n</think>\n\n{text}"
        return text or None
