"""
Mano agent — uses UITARS-style action space with bounding box coordinates.

Env vars required:
  MANO_API_URL + MANO_API_KEY
"""

import ast
import base64
import logging
import math
import os
import re
import time
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .base import BaseAgent

logger = logging.getLogger("agents.mano")

IMAGE_FACTOR = 28
MIN_PIXELS = 100 * 28 * 28
MAX_PIXELS = 16384 * 28 * 28

MANO_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action desp: ...
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
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part.

## Note
- Use {language} in `Thought` part.
- Write a small plan and finally summarize your next action in one sentence in `Action desp` part.

## User Instruction
{instruction}
"""


def _escape_single_quotes(text):
    return re.sub(r"(?<!\\)'", r"\\'", text)


def _parse_action(action_str):
    """Parse an action string like click(start_box='(123,456)') into function name + kwargs."""
    try:
        node = ast.parse(action_str, mode="eval")
        if not isinstance(node, ast.Expression) or not isinstance(node.body, ast.Call):
            return None
        call = node.body
        func_name = call.func.id if isinstance(call.func, ast.Name) else (call.func.attr if isinstance(call.func, ast.Attribute) else None)
        kwargs = {}
        for kw in call.keywords:
            val = kw.value.value if isinstance(kw.value, ast.Constant) else (kw.value.s if isinstance(kw.value, ast.Str) else None)
            kwargs[kw.arg] = str(val) if val is not None else None
        return {"function": func_name, "args": kwargs}
    except Exception:
        return None


def _add_box_token(text):
    """Add box tokens to coordinate values if missing."""
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


def _extract_action_desp(text):
    """Extract Action desp from response text."""
    desp_match = re.search(r"Action desp:(.*?)(?=\nAction:|$)", text, re.DOTALL)
    if desp_match:
        return desp_match.group(0).strip()
    return None


def _parse_action_to_structured(text, factor, resized_h, resized_w, model_type="qwen25vl", max_pixels=MAX_PIXELS, min_pixels=MIN_PIXELS):
    """Parse Mano model output to structured action dicts."""
    text = text.strip()

    if model_type == "qwen25vl":
        smart_h, smart_w = _smart_resize(resized_h, resized_w)
    else:
        smart_h, smart_w = resized_h, resized_w

    thought = None
    if "Thought:" in text:
        thought_match = re.search(r"Thought: (.+?)(?=\s*Action desp:|Action:|$)", text, re.DOTALL)
        if thought_match:
            thought = thought_match.group(1).strip()

    assert "Action:" in text, f"No Action found in: {text}"
    action_str = text.split("Action:")[-1]

    all_actions = action_str.split("\n\n")
    parsed = []
    for act in all_actions:
        act = act.strip()
        if not act:
            continue
        # Handle type content escaping
        if "type(content" in act:
            content_match = re.search(r"type\(content='(.*?)'\)", act)
            if content_match:
                content = content_match.group(1)
                act = "type(content='" + _escape_single_quotes(content) + "')"

        p = _parse_action(act.replace("\n", "\\n").lstrip())
        if p is None:
            continue

        action_inputs = {}
        for k, v in p["args"].items():
            if v == "" or v is None:
                continue
            action_inputs[k.strip()] = v

            if "start_box" in k or "end_box" in k:
                nums = v.replace("(", "").replace(")", "").split(",")
                if model_type == "qwen25vl":
                    floats = []
                    for idx, n in enumerate(nums):
                        n = float(n)
                        floats.append(float(n / smart_w) if (idx + 1) % 2 == 1 else float(n / smart_h))
                else:
                    floats = [float(n) / factor for n in nums]
                if len(floats) == 2:
                    floats = [floats[0], floats[1], floats[0], floats[1]]
                action_inputs[k.strip()] = str(floats)

        parsed.append({
            "thought": thought,
            "action_type": p["function"],
            "action_inputs": action_inputs,
            "text": text,
        })
    return parsed


def _smart_resize(height, width, factor=IMAGE_FACTOR, min_pixels=MIN_PIXELS, max_pixels=MAX_PIXELS):
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def _to_pyautogui(responses, img_h, img_w, input_swap=True):
    """Convert parsed action dict(s) to pyautogui code string.

    Ported from OSWorld/mm_agents/mano_agent.py parsing_response_to_pyautogui_code.
    E2B adaptation: no import preamble (BaseAgent adds it), no triple-quoted
    comment blocks (they break when collapsed to python3 -c one-liners).
    """
    pyautogui_code = ""
    if isinstance(responses, dict):
        responses = [responses]
    for response_id, response in enumerate(responses):
        if response_id > 0:
            pyautogui_code += "\ntime.sleep(1)\n"

        action_type = response.get("action_type")
        action_inputs = response.get("action_inputs", {})

        if action_type == "hotkey":
            if "key" in action_inputs:
                hotkey = action_inputs.get("key", "")
            else:
                hotkey = action_inputs.get("hotkey", "")

            key_map = {"arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down"}
            hotkey = key_map.get(hotkey, hotkey)

            if hotkey:
                keys = hotkey.split()
                convert_keys = []
                for key in keys:
                    if key == "space":
                        key = ' '
                    convert_keys.append(key)
                pyautogui_code += f"\npyautogui.hotkey({', '.join([repr(k) for k in convert_keys])})"

        elif action_type == "press":
            if "key" in action_inputs:
                key_to_press = action_inputs.get("key", "")
            else:
                key_to_press = action_inputs.get("press", "")

            key_map = {"arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down", "space": " "}
            key_to_press = key_map.get(key_to_press, key_to_press)

            if key_to_press:
                pyautogui_code += f"\npyautogui.press({repr(key_to_press)})"

        elif action_type == "keyup":
            key_to_up = action_inputs.get("key", "")
            pyautogui_code += f"\npyautogui.keyUp({repr(key_to_up)})"

        elif action_type == "keydown":
            key_to_down = action_inputs.get("key", "")
            pyautogui_code += f"\npyautogui.keyDown({repr(key_to_down)})"

        elif action_type == "type":
            content = action_inputs.get("content", "")
            content = _escape_single_quotes(content)
            stripped_content = content
            if content.endswith("\n") or content.endswith("\\n"):
                stripped_content = stripped_content.rstrip("\\n").rstrip("\n")
            if content:
                if input_swap:
                    pyautogui_code += f"\nimport pyperclip"
                    pyautogui_code += f"\npyperclip.copy('{stripped_content}')"
                    pyautogui_code += f"\npyautogui.hotkey('ctrl', 'v')"
                    pyautogui_code += f"\ntime.sleep(0.5)\n"
                    if content.endswith("\n") or content.endswith("\\n"):
                        pyautogui_code += f"\npyautogui.press('enter')"
                else:
                    pyautogui_code += f"\npyautogui.write('{stripped_content}', interval=0.1)"
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
            scroll_amount = action_inputs.get("scroll_amount", None)

            if scroll_amount is not None:
                try:
                    scroll_amount = int(scroll_amount)
                except (ValueError, TypeError):
                    scroll_amount = None

            if scroll_amount is not None:
                if "up" in direction.lower():
                    scroll_value = abs(scroll_amount)
                elif "down" in direction.lower():
                    scroll_value = -abs(scroll_amount)
                else:
                    scroll_value = -abs(scroll_amount)
            else:
                if "up" in direction.lower():
                    scroll_value = 5
                elif "down" in direction.lower():
                    scroll_value = -5
                else:
                    scroll_value = -5

            if x is None:
                pyautogui_code += f"\npyautogui.scroll({scroll_value})"
            else:
                pyautogui_code += f"\npyautogui.scroll({scroll_value}, x={x}, y={y})"

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
                    continue
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


class ManoAgent(BaseAgent):
    """
    Mano agent — UITARS-style action space with bounding box coordinates.
    """

    def __init__(
        self,
        model: str = "mano",
        model_type: str = "qwen25vl",
        language: str = "English",
        input_swap: bool = True,
        history_n: int = 3,
        max_pixels: int = MAX_PIXELS,
        min_pixels: int = MIN_PIXELS,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.model_type = model_type
        self.language = language
        self.input_swap = input_swap
        self.history_n = history_n
        self.max_pixels = max_pixels
        self.min_pixels = min_pixels

        self.thoughts: List[str] = []
        self.actions: List[list] = []
        self.observations: List[Dict] = []
        self.history_images: List[bytes] = []
        self.history_responses: List[str] = []

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        from openai import OpenAI

        self.history_images.append(obs["screenshot"])
        self.observations.append({"screenshot": obs["screenshot"], "accessibility_tree": None})

        # Trim image history
        if len(self.history_images) > self.history_n:
            self.history_images = self.history_images[-self.history_n :]

        # Process images
        images = []
        for img_bytes in self.history_images:
            img = Image.open(BytesIO(img_bytes))
            if img.width * img.height > self.max_pixels:
                factor = math.sqrt(self.max_pixels / (img.width * img.height))
                img = img.resize((int(img.width * factor), int(img.height * factor)))
            if img.width * img.height < self.min_pixels:
                factor = math.sqrt(self.min_pixels / (img.width * img.height))
                img = img.resize((math.ceil(img.width * factor), math.ceil(img.height * factor)))
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)

        user_prompt = MANO_PROMPT.format(instruction=instruction, language=self.language)

        # Build single-turn message with history
        user_content = [{"type": "text", "text": user_prompt}]

        if self.history_responses:
            for i, resp in enumerate(self.history_responses):
                try:
                    desp_match = re.search(r"Action desp:(.*?)(?=\nAction:|$)", resp, re.DOTALL)
                    desp = desp_match.group(0).strip() if desp_match else f"Step {i + 1}"
                except Exception:
                    desp = f"Step {i + 1}"

                user_content.append({"type": "text", "text": f"\nStep {i + 1}: {desp}"})

                # Add image for recent steps
                avail = len(images) - 1
                img_idx = avail - (len(self.history_responses) - 1 - i)
                if 0 <= img_idx < avail:
                    buf = BytesIO()
                    images[img_idx].save(buf, format="PNG")
                    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

        # Current screenshot
        user_content.append({"type": "text", "text": "\nCurrent screenshot:"})
        buf = BytesIO()
        images[-1].save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

        messages = [
            {"role": "system", "content": [{"type": "text", "text": "You are a helpful assistant."}]},
            {"role": "user", "content": user_content},
        ]

        # Call API
        client = OpenAI(base_url=os.environ["MANO_API_URL"], api_key=os.environ["MANO_API_KEY"])
        prediction = None
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model="mano",
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature or 0.0,
                )
                prediction = resp.choices[0].message.content.strip()
                break
            except Exception as e:
                logger.error(f"Mano API error (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    time.sleep(5)

        if prediction is None:
            return "client error", ["FAIL"]

        self.last_raw_response = {"content": prediction}
        self.history_responses.append(prediction)
        self.thoughts.append(prediction)

        # Parse
        try:
            parsed = _parse_action_to_structured(
                prediction, 1000, images[-1].height, images[-1].width,
                self.model_type, self.max_pixels, self.min_pixels,
            )
        except Exception as e:
            logger.error(f"Parse error: {e}")
            self.actions.append([])
            return f"Parse error: {e}", ["FAIL"]

        actions = []
        for p in parsed:
            if p["action_type"] == "finished":
                self.actions.append(actions)
                return prediction, ["DONE"]
            elif p["action_type"] == "wait":
                self.actions.append(actions)
                return prediction, ["WAIT"]

            code = _to_pyautogui(p, images[-1].height, images[-1].width, self.input_swap)
            if code:
                actions.append(code)

        self.actions.append(actions)

        if len(self.history_responses) >= self.max_steps:
            actions = ["FAIL"]

        reasoning = parsed[0].get("thought", "") if parsed else ""
        return reasoning, actions or ["FAIL"]

    def reset(self) -> None:
        self.thoughts = []
        self.actions = []
        self.observations = []
        self.history_images = []
        self.history_responses = []
