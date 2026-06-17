"""
Smoke test for the bltcy.ai Anthropic-compatible Messages API proxy.

Endpoint: https://api.bltcy.ai/v1/messages
Key     : passed via the `bitcy_api_key` env var (also accepts BLTCY_API_KEY
          or the --api-key flag).

This exercises the *official* Anthropic request/response shape — i.e. the same
`client.beta.messages.create(...)` call you'd make against api.anthropic.com,
with base_url swapped to the proxy. No translation layer.

Tiers:
  1. Plain messages      — minimal text-only /v1/messages call to prove the
     proxy speaks Anthropic's wire format.
  2. Computer-use tool   — send a screenshot + the `computer_20251124` tool
     under the `computer-use-2025-11-24` beta and check that the model
     responds with a `tool_use` block targeting the `computer` tool.
  3. End-to-end agent    — drive ClaudeAgent(api_backend="bltcy") through a
     short multi-turn loop on a synthetic screenshot, using the same harness
     the pipeline uses.

Usage:
  python agents/test_bltcy_claude_api.py
  python agents/test_bltcy_claude_api.py --api-key sk-xxxxx
  python agents/test_bltcy_claude_api.py --model claude-sonnet-4-6
  python agents/test_bltcy_claude_api.py --skip-agent   # direct SDK calls only
"""

from __future__ import annotations

import argparse
import base64
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


# Anthropic SDK appends `/v1/messages` itself, so base_url is the API root.
BASE_URL = "https://api.bltcy.ai"

COMPUTER_USE_BETA_FLAG = "computer-use-2025-11-24"
COMPUTER_USE_TYPE = "computer_20251124"

DISPLAY_W = 1280
DISPLAY_H = 720


def _make_fake_screenshot() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (DISPLAY_W, DISPLAY_H), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 40), (280, 100)], fill=(66, 133, 244), outline=(0, 0, 0))
    draw.text((70, 60), "Click Me", fill=(255, 255, 255))
    draw.text((40, 140), "bltcy claude proxy smoke test", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tier 1: plain /v1/messages ─────────────────────────────────────────────


def test_plain_messages(api_key: str, model: str) -> None:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key, base_url=BASE_URL)
    resp = client.messages.create(
        model=model,
        max_tokens=32,
        messages=[{"role": "user", "content": "Reply with exactly the single word: pong"}],
    )
    print(f"  id       : {getattr(resp, 'id', '?')}")
    print(f"  model    : {getattr(resp, 'model', '?')}")
    print(f"  stop     : {getattr(resp, 'stop_reason', '?')}")
    usage = getattr(resp, "usage", None)
    if usage is not None:
        print(
            f"  usage    : in={getattr(usage, 'input_tokens', '?')} "
            f"out={getattr(usage, 'output_tokens', '?')}"
        )

    text = ""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += getattr(block, "text", "") or ""
    print(f"  text     : {text!r}")
    assert text, "proxy returned no assistant text"
    print("[ok] plain messages API: round-trip + non-empty text")


# ── Tier 2: computer-use tool ──────────────────────────────────────────────


def test_computer_tool(api_key: str, model: str) -> None:
    """Verify the proxy forwards the Anthropic computer-use tool shape."""
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key, base_url=BASE_URL).with_options(
        default_headers={"anthropic-beta": COMPUTER_USE_BETA_FLAG}
    )

    screenshot_b64 = base64.b64encode(_make_fake_screenshot()).decode("ascii")

    system = [
        {
            "type": "text",
            "text": (
                "You are a computer-use agent. Given a screenshot, use the "
                "`computer` tool to click the blue 'Click Me' button. "
                "Do not describe — act."
            ),
        }
    ]

    tools = [
        {
            "name": "computer",
            "type": COMPUTER_USE_TYPE,
            "display_width_px": DISPLAY_W,
            "display_height_px": DISPLAY_H,
            "display_number": 0,
        }
    ]

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
                {
                    "type": "text",
                    "text": "Click the blue 'Click Me' button near the top-left.",
                },
            ],
        }
    ]

    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=tools,
            betas=[COMPUTER_USE_BETA_FLAG],
        )
    except Exception as e:
        print(f"  proxy rejected computer tool: {type(e).__name__}: {e}")
        raise

    print(f"  id       : {getattr(resp, 'id', '?')}")
    print(f"  stop     : {getattr(resp, 'stop_reason', '?')}")

    saw_tool_use = False
    saw_text = False
    for block in getattr(resp, "content", []) or []:
        btype = getattr(block, "type", None)
        print(f"  content block: type={btype}")
        if btype == "tool_use":
            saw_tool_use = True
            name = getattr(block, "name", None)
            inp = getattr(block, "input", None)
            print(f"     tool name : {name}")
            print(f"     tool input: {inp}")
        elif btype == "text":
            saw_text = True
            text = getattr(block, "text", "") or ""
            print(f"     text      : {text[:140]!r}")

    if saw_tool_use:
        print("[ok] computer tool supported — got tool_use block back")
    elif saw_text:
        print("[warn] proxy accepted the tool but returned only plain text "
              "(no tool_use) — model may not be computer-use-capable")
    else:
        print("[warn] proxy accepted the tool but produced no recognised output")


# ── Tier 3: end-to-end via ClaudeAgent ─────────────────────────────────────


def test_agent_roundtrip(api_key: str, model: str) -> None:
    from agents.claude_agent import ClaudeAgent

    agent = ClaudeAgent(
        model=model,
        api_backend="bltcy",
        api_key=api_key,
        base_url=BASE_URL,
        screen_size=(DISPLAY_W, DISPLAY_H),
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


# ── Entrypoint ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-key",
        default=os.environ.get("bitcy_api_key") or os.environ.get("BLTCY_API_KEY"),
        help="bltcy.ai API key (or set bitcy_api_key / BLTCY_API_KEY in env)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="model to probe (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--skip-agent", action="store_true", help="skip ClaudeAgent multi-turn test"
    )
    parser.add_argument(
        "--skip-computer", action="store_true", help="skip computer-tool probe"
    )
    args = parser.parse_args()

    if not args.api_key:
        print("error: no api key — pass --api-key or set bitcy_api_key / BLTCY_API_KEY")
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

    run("plain_messages", test_plain_messages, args.api_key, args.model)
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
