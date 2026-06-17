"""
Dart GUI agent — UITARS-style action space with multi-turn dialogue management.

Env vars required:
  DART_API_URL + DART_API_KEY   (or DOUBAO_API_URL + DOUBAO_API_KEY)
"""

import ast
import base64
import logging
import math
import os
import re
import time
from copy import deepcopy
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.dart")

IMAGE_FACTOR = 28
MIN_PIXELS = 100 * 28 * 28
MAX_PIXELS = 16384 * 28 * 28
FINISH_WORD = "finished"
WAIT_WORD = "wait"
ENV_FAIL_WORD = "error_env"
CALL_USER = "call_user"

COMPUTER_USE_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(start_box='<|box_start|>(x1,y1)<|box_end|>')
left_double(start_box='<|box_start|>(x1,y1)<|box_end|>')
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>')
hotkey(key='')
type(content='') #If you want to submit your input, use "\\n" at the end of `content`.
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up or right or left')
wait() #Sleep for 5s and take a screenshot to check for any changes.
finished(content='xxx')

## Note
- Use {language} in `Thought` part.
- Write a small plan and finally summarize your next action in one sentence in `Thought` part.
- My computer's password is 'password', feel free to use it when you need sudo rights.

## User Instruction
{instruction}
"""


def _escape_single_quotes(text):
    return re.sub(r"(?<!\\)'", r"\\'", text)


def _pil_to_base64(image_data) -> str:
    if isinstance(image_data, bytes):
        img = Image.open(BytesIO(image_data))
    else:
        img = image_data
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _add_box_token(text):
    if "Action: " in text and "start_box=" in text:
        suffix = text.split("Action: ")[0] + "Action: "
        actions = text.split("Action: ")[1:]
        processed = []
        for action in actions:
            action = action.strip()
            coords = re.findall(r"(start_box|end_box)='\((\d+),\s*(\d+)\)'", action)
            for ct, x, y in coords:
                action = action.replace(f"{ct}='({x},{y})'", f"{ct}='<|box_start|>({x},{y})<|box_end|>'")
            processed.append(action)
        return suffix + "\n\n".join(processed)
    return text


def _parse_action(action_str):
    try:
        node = ast.parse(action_str, mode="eval")
        if not isinstance(node, ast.Expression) or not isinstance(node.body, ast.Call):
            return None
        call = node.body
        func_name = call.func.id if isinstance(call.func, ast.Name) else None
        kwargs = {}
        for kw in call.keywords:
            val = kw.value.value if isinstance(kw.value, ast.Constant) else None
            kwargs[kw.arg] = str(val) if val is not None else None
        return {"function": func_name, "args": kwargs}
    except Exception:
        return None


def _smart_resize(h, w, factor=IMAGE_FACTOR, min_px=MIN_PIXELS, max_px=MAX_PIXELS):
    h_bar = max(factor, round(h / factor) * factor)
    w_bar = max(factor, round(w / factor) * factor)
    if h_bar * w_bar > max_px:
        beta = math.sqrt((h * w) / max_px)
        h_bar = math.floor(h / beta / factor) * factor
        w_bar = math.floor(w / beta / factor) * factor
    elif h_bar * w_bar < min_px:
        beta = math.sqrt(min_px / (h * w))
        h_bar = math.ceil(h * beta / factor) * factor
        w_bar = math.ceil(w * beta / factor) * factor
    return h_bar, w_bar


def _parse_to_structured(text, factor, img_h, img_w, model_type="qwen25vl", max_px=MAX_PIXELS, min_px=MIN_PIXELS):
    text = text.strip()
    smart_h, smart_w = _smart_resize(img_h, img_w) if model_type == "qwen25vl" else (img_h, img_w)

    thought = None
    thought_m = re.search(r"Thought: (.+?)(?=\s*Action:|$)", text, re.DOTALL)
    if thought_m:
        thought = thought_m.group(1).strip()

    assert "Action:" in text, f"No Action found"
    action_str = text.split("Action:")[-1]

    results = []
    for act in action_str.split("\n\n"):
        act = act.strip()
        if not act:
            continue
        if "type(content" in act:
            cm = re.search(r"type\(content='(.*?)'\)", act)
            if cm:
                act = "type(content='" + _escape_single_quotes(cm.group(1)) + "')"

        p = _parse_action(act.replace("\n", "\\n").lstrip())
        if not p:
            continue

        inputs = {}
        for k, v in p["args"].items():
            if not v:
                continue
            inputs[k.strip()] = v
            if "box" in k:
                nums = v.replace("(", "").replace(")", "").split(",")
                if model_type == "qwen25vl":
                    floats = [float(nums[i]) / (smart_w if i % 2 == 0 else smart_h) for i in range(len(nums))]
                else:
                    floats = [float(n) / factor for n in nums]
                if len(floats) == 2:
                    floats = [floats[0], floats[1], floats[0], floats[1]]
                inputs[k.strip()] = str(floats)

        results.append({"thought": thought, "action_type": p["function"], "action_inputs": inputs, "text": text})
    return results


def _to_pyautogui(responses, img_h, img_w, input_swap=False):
    """Convert parsed action dict(s) to pyautogui code string.

    Ported from OSWorld/mm_agents/uitars_agent.py parsing_response_to_pyautogui_code.
    E2B adaptation: no import preamble (BaseAgent adds it), no triple-quoted
    comment blocks (they break when collapsed to python3 -c one-liners).
    """
    pyautogui_code = ""
    if isinstance(responses, dict):
        responses = [responses]
    for response_id, response in enumerate(responses):
        if response_id > 0:
            pyautogui_code += "\ntime.sleep(3)\n"

        action_type = response.get("action_type")
        action_inputs = response.get("action_inputs", {})

        if action_type == "hotkey":
            key = action_inputs.get("key", action_inputs.get("hotkey", ""))
            if key:
                keys = key.split()
                pyautogui_code += f"\npyautogui.hotkey({', '.join([repr(k) for k in keys])})"

        elif action_type == "type":
            content = action_inputs.get("content", "")
            content = _escape_single_quotes(content)
            if content:
                if input_swap:
                    stripped = content.rstrip("\\n").rstrip("\n")
                    pyautogui_code += f"\nimport pyperclip"
                    pyautogui_code += f"\npyperclip.copy('{stripped}')"
                    pyautogui_code += f"\npyautogui.hotkey('ctrl', 'v')"
                    pyautogui_code += f"\ntime.sleep(0.5)\n"
                    if content.endswith("\n") or content.endswith("\\n"):
                        pyautogui_code += f"\npyautogui.press('enter')"
                else:
                    pyautogui_code += f"\npyautogui.write('{content.strip()}', interval=0.1)"
                    pyautogui_code += f"\ntime.sleep(0.5)\n"
                    if content.endswith("\n") or content.endswith("\\n"):
                        pyautogui_code += f"\npyautogui.press('enter')"

        elif action_type in ("drag", "select"):
            start_box = action_inputs.get("start_box")
            end_box = action_inputs.get("end_box")
            if start_box and end_box:
                x1, y1, x2, y2 = eval(start_box)
                sx = round(float((x1 + x2) / 2) * img_w, 3)
                sy = round(float((y1 + y2) / 2) * img_h, 3)
                x1, y1, x2, y2 = eval(end_box)
                ex = round(float((x1 + x2) / 2) * img_w, 3)
                ey = round(float((y1 + y2) / 2) * img_h, 3)
                pyautogui_code += (
                    f"\npyautogui.moveTo({sx}, {sy})\n"
                    f"\npyautogui.dragTo({ex}, {ey}, duration=1.0)\n"
                )

        elif action_type == "scroll":
            start_box = action_inputs.get("start_box")
            if start_box:
                x1, y1, x2, y2 = eval(start_box)
                x = round(float((x1 + x2) / 2) * img_w, 3)
                y = round(float((y1 + y2) / 2) * img_h, 3)
            else:
                x = None
                y = None
            direction = action_inputs.get("direction", "")

            if x is None:
                if "up" in direction.lower():
                    pyautogui_code += f"\npyautogui.scroll(5)"
                elif "down" in direction.lower():
                    pyautogui_code += f"\npyautogui.scroll(-5)"
            else:
                if "up" in direction.lower():
                    pyautogui_code += f"\npyautogui.scroll(5, x={x}, y={y})"
                elif "down" in direction.lower():
                    pyautogui_code += f"\npyautogui.scroll(-5, x={x}, y={y})"

        elif action_type in ("click", "left_single", "left_double", "right_single", "hover"):
            start_box = action_inputs.get("start_box")
            start_box = str(start_box)
            if start_box:
                start_box = eval(start_box)
                if len(start_box) == 4:
                    x1, y1, x2, y2 = start_box
                elif len(start_box) == 2:
                    x1, y1 = start_box
                    x2, y2 = x1, y1
                else:
                    return pyautogui_code
                x = round(float((x1 + x2) / 2) * img_w, 3)
                y = round(float((y1 + y2) / 2) * img_h, 3)
                if action_type == "left_single" or action_type == "click":
                    pyautogui_code += f"\npyautogui.click({x}, {y}, button='left')"
                elif action_type == "left_double":
                    pyautogui_code += f"\npyautogui.doubleClick({x}, {y}, button='left')"
                elif action_type == "right_single":
                    pyautogui_code += f"\npyautogui.click({x}, {y}, button='right')"
                elif action_type == "hover":
                    pyautogui_code += f"\npyautogui.moveTo({x}, {y})"

        elif action_type in ("finished",):
            pyautogui_code = "DONE"

        else:
            pyautogui_code += f"\n# Unrecognized action type: {action_type}"

    return pyautogui_code


class DartAgent(BaseAgent):
    """
    Dart GUI agent — UITARS-style action space with dialogue trimming.
    """

    def __init__(
        self,
        model: str,
        model_type: str = "qwen25vl",
        language: str = "English",
        input_swap: bool = False,
        max_images: int = 5,
        max_texts: int = 35,
        max_pixels: int = MAX_PIXELS,
        min_pixels: int = MIN_PIXELS,
        dart_api_url: Optional[str] = None,
        dart_api_key: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.model_type = model_type
        self.language = language
        self.input_swap = input_swap
        self.max_images = max_images
        self.max_texts = max_texts
        self.max_pixels = max_pixels
        self.min_pixels = min_pixels
        self.dart_api_url = dart_api_url or os.environ.get("DART_API_URL", os.environ.get("DOUBAO_API_URL", ""))
        self.dart_api_key = dart_api_key or os.environ.get("DART_API_KEY", os.environ.get("DOUBAO_API_KEY", ""))

        self.actions: List[list] = []
        self.observations: List[Dict] = []
        self.thoughts: List[str] = []
        self.history_responses: List[str] = []

        # Dialogue management
        self.base_messages: List[dict] = []
        self.prompt_dialogue: List[dict] = []
        self.image_refs: List[dict] = []

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        # Init base messages on first call
        if not self.base_messages:
            self.base_messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": [
                    {"type": "text", "text": COMPUTER_USE_PROMPT.format(instruction=instruction, language=self.language)},
                ]},
            ]

        self.observations.append({"screenshot": obs["screenshot"]})

        # Add screenshot
        b64 = _pil_to_base64(obs["screenshot"])
        if len(self.observations) == 1:
            # First frame goes into base_messages
            self.base_messages[1]["content"].append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            )
            self.image_refs.append({"source": "base", "msg_idx": 1, "content_idx": len(self.base_messages[1]["content"]) - 1})
        else:
            self.prompt_dialogue.append({
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}],
            })
            self.image_refs.append({"source": "dialogue", "msg_idx": len(self.prompt_dialogue) - 1})
            self._trim()

        # Build messages
        messages = self.base_messages + self.prompt_dialogue

        # Call model
        prediction = self._call_model(messages)
        if prediction is None:
            return "client error", ["FAIL"]

        # Store response
        self.last_raw_response = {"content": prediction}
        self.history_responses.append(prediction)
        self.thoughts.append(prediction)
        self.prompt_dialogue.append({"role": "assistant", "content": _add_box_token(prediction)})
        self._trim()

        # Parse actions
        try:
            img = Image.open(BytesIO(obs["screenshot"]))
            parsed = _parse_to_structured(prediction, 1000, img.height, img.width, self.model_type, self.max_pixels, self.min_pixels)
        except Exception as e:
            logger.error(f"Parse error: {e}")
            self.actions.append([])
            return f"Parse error: {e}", ["FAIL"]

        actions = []
        for p in parsed:
            if p["action_type"] == FINISH_WORD:
                self.actions.append(actions)
                return prediction, ["DONE"]
            elif p["action_type"] == WAIT_WORD:
                self.actions.append(actions)
                return prediction, ["WAIT"]
            elif p["action_type"] == ENV_FAIL_WORD:
                self.actions.append(actions)
                return prediction, ["FAIL"]
            elif p["action_type"] == CALL_USER:
                self.actions.append(actions)
                return prediction, ["FAIL"]
            code = _to_pyautogui(p, img.height, img.width, self.input_swap)
            if code:
                actions.append(code)

        self.actions.append(actions)

        if len(self.history_responses) >= self.max_steps:
            actions = ["FAIL"]

        reasoning = parsed[0].get("thought", "") if parsed else ""
        return reasoning, actions or ["FAIL"]

    def reset(self) -> None:
        self.actions = []
        self.observations = []
        self.thoughts = []
        self.history_responses = []
        self.base_messages = []
        self.prompt_dialogue = []
        self.image_refs = []

    def _trim(self):
        img_cnt = len(self.image_refs)
        txt_cnt = sum(1 for m in self.prompt_dialogue if m["role"] == "assistant")
        while img_cnt > self.max_images or txt_cnt > self.max_texts:
            if img_cnt > self.max_images and self.image_refs:
                ref = self.image_refs.pop(0)
                if ref["source"] == "base":
                    self.base_messages[ref["msg_idx"]]["content"].pop(ref["content_idx"])
                elif ref["source"] == "dialogue" and ref["msg_idx"] < len(self.prompt_dialogue):
                    self.prompt_dialogue.pop(ref["msg_idx"])
                    self.image_refs = [
                        ({**r, "msg_idx": r["msg_idx"] - 1} if r["source"] == "dialogue" and r["msg_idx"] > ref["msg_idx"] else r)
                        for r in self.image_refs
                    ]
                img_cnt -= 1
                continue
            if txt_cnt > self.max_texts:
                for i, m in enumerate(self.prompt_dialogue):
                    if m["role"] == "assistant":
                        self.prompt_dialogue.pop(i)
                        txt_cnt -= 1
                        break

    def _call_model(self, messages: list) -> Optional[str]:
        from openai import OpenAI
        import requests

        # Use direct endpoint if URL contains /generate
        if "/generate" in self.dart_api_url:
            for attempt in range(3):
                try:
                    resp = requests.post(
                        self.dart_api_url,
                        json={"messages": messages, "model": self.model, "max_tokens": self.max_tokens,
                              "temperature": self.temperature or 0.0},
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.dart_api_key}"},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if "choices" in data:
                        return data["choices"][0]["message"]["content"]
                    return data.get("response", data.get("text", str(data)))
                except Exception as e:
                    logger.error(f"Dart direct endpoint error (attempt {attempt + 1}): {e}")
                    time.sleep(2)
            return None

        # OpenAI-compatible endpoint
        base_url = self.dart_api_url
        if base_url and not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        client = OpenAI(base_url=base_url, api_key=self.dart_api_key)

        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=self.model, messages=messages,
                    max_tokens=self.max_tokens, temperature=self.temperature or 0.0,
                    frequency_penalty=1,
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.error(f"Dart API error (attempt {attempt + 1}): {e}")
                time.sleep(2)
        return None
