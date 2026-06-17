"""
Smoke test for the bltcy.ai OpenAI-compatible Responses API proxy.

Endpoint: https://api.bltcy.ai/v1
Key     : passed via BLTCY_API_KEY env var or --api-key flag.

Tiers:
  1. Plain Responses API    — minimal text-only request to prove the
     proxy implements /responses at all.
  2. Models list            — GET /v1/models, see which model IDs are
     actually served.
  3. Computer tool probe    — create a Responses request with the
     {"type": "computer"} tool to see if this proxy supports the
     computer-use surface.
  4. End-to-end via agent   — wire ChatGPTAgent against the proxy and
     drive a short multi-turn loop on a synthetic screenshot.

Usage:
  python agents/test_bltcy_api.py
  python agents/test_bltcy_api.py --api-key sk-xxxxx
  python agents/test_bltcy_api.py --model gpt-5.4
  python agents/test_bltcy_api.py --skip-agent   # offline-ish, only direct SDK calls
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import dotenv  # noqa: F401

    dotenv.load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass


BASE_URL = "https://api.bltcy.ai/v1"


def _make_fake_screenshot() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1920, 1080), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 40), (280, 100)], fill=(66, 133, 244), outline=(0, 0, 0))
    draw.text((70, 60), "Click Me", fill=(255, 255, 255))
    draw.text((40, 140), "bltcy proxy smoke test", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tier 1: plain Responses API ────────────────────────────────────────────


def test_plain_responses(api_key: str, model: str) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    resp = client.responses.create(
        model=model,
        input="Reply with exactly the single word: pong",
        max_output_tokens=16,
    )
    print(f"  status   : {getattr(resp, 'status', '?')}")
    print(f"  id       : {getattr(resp, 'id', '?')}")
    usage = getattr(resp, "usage", None)
    if usage is not None:
        print(
            f"  usage    : in={getattr(usage, 'input_tokens', '?')} "
            f"out={getattr(usage, 'output_tokens', '?')}"
        )

    # Pull assistant text out of response.output.
    text = ""
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for part in getattr(item, "content", []) or []:
                if getattr(part, "type", None) == "output_text":
                    text += getattr(part, "text", "") or ""

    # Some proxies also expose response.output_text directly.
    if not text:
        text = getattr(resp, "output_text", "") or ""

    print(f"  text     : {text!r}")
    assert text, "proxy returned no assistant text"
    print("[ok] plain Responses API: round-trip + non-empty text")


# ── Tier 2: models list ────────────────────────────────────────────────────


def test_models_list(api_key: str) -> None:
    import requests

    r = requests.get(
        f"{BASE_URL}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    print(f"  GET /models → HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  body: {r.text[:400]}")
        print("[skip] /models not supported by this proxy")
        return
    data = r.json()
    items = data.get("data") or data.get("models") or []
    print(f"  {len(items)} model(s) listed")
    ids = [m.get("id") or m.get("name") for m in items]
    wanted = ["gpt-5.4", "gpt-5", "gpt-5-chat", "computer-use-preview", "gpt-4o", "gpt-4.1"]
    for w in wanted:
        mark = "✅" if w in ids else "  "
        print(f"    {mark} {w}")
    # Print the first 20 IDs so we can eyeball what's available.
    print("  sample of available ids:")
    for mid in ids[:20]:
        print(f"    - {mid}")
    if len(ids) > 20:
        print(f"    … and {len(ids) - 20} more")
    print("[ok] /models endpoint reachable")


# ── Tier 3: computer tool probe ────────────────────────────────────────────


def test_computer_tool(api_key: str, model: str) -> None:
    """Does this proxy actually pass-through the computer-use tool shape?"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    screenshot_b64 = __import__("base64").b64encode(_make_fake_screenshot()).decode("ascii")

    try:
        resp = client.responses.create(
            model=model,
            instructions=(
                "You are a computer-use agent. Given the screenshot, use the "
                "computer tool to click the blue 'Click Me' button."
            ),
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Click the blue button near the top-left.",
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{screenshot_b64}",
                            "detail": "original",
                        },
                    ],
                }
            ],
            tools=[{"type": "computer"}],
            parallel_tool_calls=False,
            truncation="auto",
            reasoning={"effort": "medium", "summary": "concise"},
        )
    except Exception as e:
        # Typical rejection: "Tool 'computer' is not supported with <model>."
        print(f"  proxy rejected computer tool: {type(e).__name__}: {e}")
        raise

    saw_computer_call = False
    saw_message = False
    for item in getattr(resp, "output", []) or []:
        t = getattr(item, "type", None)
        print(f"  output item: type={t}")
        if t == "computer_call":
            saw_computer_call = True
            actions = getattr(item, "actions", None) or (
                [getattr(item, "action", None)]
                if getattr(item, "action", None) is not None
                else []
            )
            for a in actions:
                atype = getattr(a, "type", None) if not isinstance(a, dict) else a.get("type")
                print(f"     action: {atype}")
        elif t == "message":
            saw_message = True
            for part in getattr(item, "content", []) or []:
                if getattr(part, "type", None) == "output_text":
                    print(f"     message text: {getattr(part, 'text', '')[:140]!r}")

    if saw_computer_call:
        print("[ok] computer tool supported — got computer_call item back")
    elif saw_message:
        print("[warn] proxy accepted the tool but returned a plain message "
              "(no computer_call) — model may not be computer-use-capable")
    else:
        print("[warn] proxy accepted the tool but produced no recognised output")


# ── Tier 4: end-to-end via ChatGPTAgent ────────────────────────────────────


def test_agent_roundtrip(api_key: str, model: str) -> None:
    from agents.chatgpt_agent import ChatGPTAgent

    agent = ChatGPTAgent(
        model=model,
        api_key=api_key,
        base_url=BASE_URL,
        screen_size=(1920, 1080),
    )
    agent.reset()

    shot = _make_fake_screenshot()
    saw_spatial = False

    for turn in range(3):
        reasoning, actions = agent.predict(
            "Click the blue 'Click Me' button near the top-left of the screenshot.",
            {"screenshot": shot},
        )
        print(f"  --- turn {turn + 1} ---")
        print(f"    reasoning: {(reasoning or '<empty>')[:160]!r}")
        print(f"    actions ({len(actions)}):")
        for a in actions:
            print("        " + str(a).strip().replace("\n", " | ")[:200])
        print(f"    response_id: {agent.previous_response_id}")
        print(f"    pending    : {len(agent.pending_input_items)}")

        if actions == ["FAIL"]:
            raise AssertionError(
                f"agent returned FAIL on turn {turn + 1} — proxy did not drive the tool loop"
            )
        if any(
            "pyautogui.click" in str(a) or "pyautogui.moveTo" in str(a)
            for a in actions
        ):
            saw_spatial = True
        if actions == ["DONE"]:
            break

    if not saw_spatial:
        print("[warn] multi-turn loop completed but no spatial action emitted")
    else:
        print("[ok] multi-turn loop against proxy produced spatial actions")


# ── Entrypoint ──────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-key",
        default=os.environ.get("BLTCY_API_KEY"),
        help="bltcy.ai API key (or set BLTCY_API_KEY in env)",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.4",
        help="model to probe (default: gpt-5.4)",
    )
    parser.add_argument(
        "--skip-agent", action="store_true", help="skip ChatGPTAgent multi-turn test"
    )
    parser.add_argument(
        "--skip-computer", action="store_true", help="skip computer-tool probe"
    )
    args = parser.parse_args()

    if not args.api_key:
        print("error: no api key — pass --api-key or set BLTCY_API_KEY")
        return 2

    print(f"proxy : {BASE_URL}")
    print(f"model : {args.model}")
    print(f"key   : {args.api_key[:8]}… (len={len(args.api_key)})")

    failed: list[str] = []

    def run(name: str, fn, *a, **kw) -> None:
        print(f"\n=== {name} ===")
        try:
            fn(*a, **kw)
        except Exception as e:
            failed.append(name)
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

    run("models_list", test_models_list, args.api_key)
    run("plain_responses", test_plain_responses, args.api_key, args.model)
    if not args.skip_computer:
        run("computer_tool", test_computer_tool, args.api_key, args.model)
    if not args.skip_agent:
        run("agent_roundtrip", test_agent_roundtrip, args.api_key, args.model)

    print("\n" + "=" * 50)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
