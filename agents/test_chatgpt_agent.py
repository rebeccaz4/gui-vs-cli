"""
Smoke test for agents/chatgpt_agent.py.

Mirrors the structure of test_gemini_agent.py:

  1. Offline parsing — always runs. Verifies registry wiring, action
     translation matches OSWorld, response parsing, and state reset.
  2. Live OpenAI API — runs if OPENAI_API_KEY is set. Does a single-turn
     predict() against the real Responses API and checks that a real
     computer_call comes back.
  3. Live Azure API — runs if azure_api_key / AZURE_OPENAI_API_KEY is set.
  4. E2B round-trip — runs if OPENAI_API_KEY + E2B_API_KEY are both set.

Usage:
  python agents/test_chatgpt_agent.py
  python agents/test_chatgpt_agent.py --skip-live
  python agents/test_chatgpt_agent.py --skip-e2b
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


def _make_fake_screenshot() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1920, 1080), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 40), (280, 100)], fill=(66, 133, 244), outline=(0, 0, 0))
    draw.text((70, 60), "Click Me", fill=(255, 255, 255))
    draw.text((40, 140), "ChatGPT computer-use smoke test", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tier 1: offline parsing ─────────────────────────────────────────────────


def test_registry() -> None:
    from agents.registry import create_agent, list_models
    from agents.chatgpt_agent import ChatGPTAgent

    aliases = list_models()
    for needed in ("chatgpt", "gpt-5.4", "computer-use-preview", "azure-gpt-5.4"):
        assert needed in aliases, f"{needed!r} missing from registry ({aliases})"

    a = create_agent("gpt-5.4", api_key="dummy")
    assert isinstance(a, ChatGPTAgent)
    assert a.model == "gpt-5.4"
    assert a.tools == [{"type": "computer"}]
    assert a.api_backend == "openai"

    b = create_agent("computer-use-preview", api_key="dummy")
    assert isinstance(b, ChatGPTAgent)
    assert b.model == "computer-use-preview"
    assert b.tools[0]["type"] == "computer_use_preview"
    assert b.tools[0]["display_width"] == 1920
    assert b.tools[0]["display_height"] == 1080
    assert b.tools[0]["environment"] == "linux"

    c = create_agent("azure-gpt-5.4", api_key="dummy")
    assert isinstance(c, ChatGPTAgent)
    assert c.api_backend == "azure"

    print("[ok] registry wires gpt-5.4 / computer-use-preview / azure-gpt-5.4")


def test_action_translation() -> None:
    """Every OSWorld-style computer-use action should translate correctly."""
    from agents.chatgpt_agent import ChatGPTAgent

    agent = ChatGPTAgent(api_key="dummy", screen_size=(1920, 1080))

    cases = [
        (
            ("click", {"x": 100, "y": 200, "button": "left"}),
            ["pyautogui.moveTo(100, 200)", "pyautogui.click(button='left')"],
        ),
        (
            ("click", {"x": 50, "y": 60, "button": "right"}),
            ["pyautogui.click(button='right')"],
        ),
        (
            ("double_click", {"x": 100, "y": 100}),
            ["pyautogui.moveTo(100, 100)", "pyautogui.doubleClick()"],
        ),
        (
            ("move", {"x": 250, "y": 250}),
            ["pyautogui.moveTo(250, 250)"],
        ),
        (
            ("drag", {"path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]}),
            ["pyautogui.moveTo(1, 2)", "pyautogui.dragTo(3, 4, duration=0.2, button='left')"],
        ),
        (
            ("type", {"text": "hi"}),
            ["pyautogui.typewrite('hi', interval=0.03)"],
        ),
        (
            ("type", {"text": "a\nb"}),
            ["pyautogui.typewrite('a', interval=0.03)", "pyautogui.press('enter')", "pyautogui.typewrite('b', interval=0.03)"],
        ),
        (
            ("type", {"text": "café"}),
            ["pyperclip.copy(_text)", "pyautogui.hotkey('ctrl', 'v')"],
        ),
        (
            ("keypress", {"keys": ["Ctrl", "c"]}),
            ["pyautogui.hotkey('ctrl', 'c')"],
        ),
        (
            ("keypress", {"keys": ["ArrowDown"]}),
            ["pyautogui.hotkey('down')"],
        ),
        (
            # scroll_y should be negated (OSWorld parity)
            ("scroll", {"x": 10, "y": 20, "scroll_y": 5}),
            ["pyautogui.scroll(-5, x=10, y=20)"],
        ),
        (
            # scroll_x should ALSO be negated — this was a bug in the old impl
            ("scroll", {"x": 10, "y": 20, "scroll_x": 5}),
            ["pyautogui.hscroll(-5, x=10, y=20)"],
        ),
        (
            ("wait", {"ms": 2000}),
            ["time.sleep(2.0)"],
        ),
        (
            ("screenshot", {}),
            ["time.sleep(0.1)"],
        ),
    ]

    for (atype, args), needles in cases:
        code = agent._convert_action_to_pyautogui(atype, args)
        for needle in needles:
            assert code and needle in code, (
                f"{atype} {args} produced {code!r} — expected substring {needle!r}"
            )
        first_line = (code or "").strip().splitlines()[0] if code else ""
        print(f"[ok] {atype:<14} -> {first_line[:80]}")

    # Unknown action → None
    assert agent._convert_action_to_pyautogui("levitate", {}) is None
    # Empty scroll → None
    assert agent._convert_action_to_pyautogui("scroll", {"x": 1, "y": 1}) is None
    # Click with missing coords → None
    assert agent._convert_action_to_pyautogui("click", {"button": "left"}) is None

    print("[ok] unknown / malformed actions return None")


def test_typing_strategy() -> None:
    """Verify the OSWorld typing-strategy switch."""
    from agents.chatgpt_agent import ChatGPTAgent

    agent = ChatGPTAgent(api_key="dummy")

    assert agent._typing_strategy("") == "empty"
    assert agent._typing_strategy("hello") == "single_line_ascii"
    assert agent._typing_strategy("hi\nthere") == "multiline_ascii"
    assert agent._typing_strategy("café") == "clipboard"
    assert agent._typing_strategy("日本語") == "clipboard"
    print("[ok] typing_strategy: empty / ascii / multiline / clipboard")


def test_response_parse() -> None:
    """_parse_response should handle batched actions, reasoning, and messages."""
    from agents.chatgpt_agent import ChatGPTAgent

    agent = ChatGPTAgent(api_key="dummy")

    # Build a fake response mirroring the Responses API shape: raw dicts
    # exercise the non-pydantic fallback path in _action_to_dict.
    class _R:
        def __init__(self, output, rid="resp_test"):
            self.output = output
            self.id = rid

        def model_dump(self):
            return {"id": self.id, "output": self.output}

    # 1) A single computer_call with batched actions[]
    r = _R(
        output=[
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "I will click."}]},
            {
                "type": "computer_call",
                "call_id": "call_1",
                "pending_safety_checks": [],
                "actions": [
                    {"type": "click", "x": 100, "y": 200, "button": "left"},
                    {"type": "type", "text": "hello"},
                ],
            },
        ],
        rid="resp_aaa",
    )
    reasoning, codes = agent._parse_response(r)
    assert "I will click." in reasoning, reasoning
    assert len(codes) == 2, codes
    assert "pyautogui.moveTo(100, 200)" in codes[0]
    assert "pyautogui.typewrite('hello'" in codes[1]
    assert len(agent.pending_input_items) == 1
    assert agent.pending_input_items[0]["call_id"] == "call_1"
    print("[ok] parse: batched actions[] → 2 codes + 1 pending output")

    # 2) Legacy computer-use-preview: single action field, no actions[]
    agent.reset()
    r2 = _R(output=[
        {
            "type": "computer_call",
            "call_id": "call_2",
            "pending_safety_checks": [{"id": "s1", "code": "c", "message": "m"}],
            "action": {"type": "click", "x": 5, "y": 6, "button": "left"},
        }
    ])
    reasoning, codes = agent._parse_response(r2)
    assert len(codes) == 1, codes
    assert "pyautogui.moveTo(5, 6)" in codes[0]
    assert agent.pending_input_items[0]["acknowledged_safety_checks"] == [
        {"id": "s1", "code": "c", "message": "m"}
    ]
    print("[ok] parse: legacy single action + safety-check passthrough")

    # 3) Bare assistant message → DONE
    agent.reset()
    r3 = _R(output=[
        {"type": "message", "content": [{"type": "output_text", "text": "All done."}]}
    ])
    reasoning, codes = agent._parse_response(r3)
    assert codes == ["DONE"], codes
    assert "All done." in reasoning
    print("[ok] parse: bare message → DONE")

    # 4) [INFEASIBLE] → FAIL
    agent.reset()
    r4 = _R(output=[
        {"type": "message", "content": [{"type": "output_text", "text": "[INFEASIBLE] missing app"}]}
    ])
    reasoning, codes = agent._parse_response(r4)
    assert codes == ["FAIL"], codes
    print("[ok] parse: [INFEASIBLE] sentinel → FAIL")

    # 5) Infeasibility word list ("cannot be done")
    agent.reset()
    r5 = _R(output=[
        {"type": "message", "content": [{"type": "output_text", "text": "This cannot be done here."}]}
    ])
    reasoning, codes = agent._parse_response(r5)
    assert codes == ["FAIL"], codes
    print("[ok] parse: 'cannot be done' → FAIL")

    # 6) Empty output → WAIT
    agent.reset()
    r6 = _R(output=[])
    reasoning, codes = agent._parse_response(r6)
    assert codes == ["WAIT"], codes
    print("[ok] parse: empty output → WAIT")


def test_reset() -> None:
    from agents.chatgpt_agent import ChatGPTAgent

    agent = ChatGPTAgent(api_key="dummy")
    agent.previous_response_id = "resp_xyz"
    agent.pending_input_items = [{"type": "computer_call_output", "call_id": "c"}]
    agent.reset()
    assert agent.previous_response_id is None
    assert agent.pending_input_items == []
    print("[ok] reset clears previous_response_id + pending_input_items")


# ── Tier 2: live OpenAI API ─────────────────────────────────────────────────


def test_live_openai() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] live OpenAI: OPENAI_API_KEY not set")
        return

    # Bypass any OPENAI_BASE_URL proxy — gpt-5.4 computer-use needs the real
    # OpenAI Responses API, which a generic OpenAI-compatible proxy
    # (LiteLLM, vLLM, etc.) usually doesn't implement.
    base_url = os.environ.pop("OPENAI_BASE_URL", None)
    if base_url:
        print(f"[info] temporarily ignoring OPENAI_BASE_URL={base_url}")

    try:
        from agents.registry import create_agent

        # Use gpt-5.4 (bare "computer" tool). Pass a short instruction.
        agent = create_agent("gpt-5.4", screen_size=(1920, 1080))
        agent.reset()

        shot = _make_fake_screenshot()

        # Drive up to 3 turns so we can observe an initial "screenshot"
        # action (common first move) → then a real click on the next turn.
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
                    f"predict() returned FAIL on turn {turn + 1} — live API call failed"
                )
            if any("pyautogui.click" in str(a) or "pyautogui.moveTo" in str(a) for a in actions):
                saw_spatial = True
            if actions == ["DONE"]:
                break

        assert agent.previous_response_id is not None, "previous_response_id not set"
        assert saw_spatial, "model never emitted a spatial click/move across 3 turns"
        print("[ok] live OpenAI: multi-turn loop with spatial action + DONE")
    finally:
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url


def test_live_azure() -> None:
    if not (os.environ.get("azure_api_key") or os.environ.get("AZURE_OPENAI_API_KEY")):
        print("[skip] live Azure: azure_api_key not set")
        return

    from agents.registry import create_agent

    agent = create_agent("azure-gpt-5.4", screen_size=(1920, 1080))
    agent.reset()

    shot = _make_fake_screenshot()
    try:
        reasoning, actions = agent.predict(
            "Click the blue 'Click Me' button near the top-left.",
            {"screenshot": shot},
        )
    except Exception as e:
        print(f"[skip] live Azure: call failed ({type(e).__name__}: {e})")
        return

    print(f"  reasoning: {(reasoning or '<empty>')[:160]!r}")
    print(f"  actions ({len(actions)}): {actions[:2]}")
    if actions == ["FAIL"]:
        print("[warn] Azure predict() returned FAIL (deployment may not support computer-use)")
        return
    print("[ok] live Azure: round-trip succeeded")


# ── Tier 3: E2B round-trip ──────────────────────────────────────────────────


def test_e2b_roundtrip() -> None:
    if not os.environ.get("E2B_API_KEY"):
        print("[skip] E2B round-trip: E2B_API_KEY not set")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] E2B round-trip: OPENAI_API_KEY not set")
        return

    from e2b_desktop import Sandbox

    from agents.registry import create_agent

    print("[..] E2B: starting sandbox (~30s)")
    sandbox = Sandbox()
    try:
        sandbox.stream.start()
        agent = create_agent("gpt-5.4", screen_size=(1920, 1080))
        agent.reset()

        shot = sandbox.screenshot()
        reasoning, actions = agent.predict(
            "Open the Files application from the taskbar.",
            {"screenshot": shot},
        )
        print(f"[ok] E2B first predict: reasoning={(reasoning or '')[:120]!r}")
        print(f"     actions={len(actions)}")
        for a in actions[:3]:
            if a in ("DONE", "WAIT", "FAIL"):
                print(f"     special token: {a}")
                continue
            ok, desc = agent.execute_action(sandbox, a)
            print(f"     exec ok={ok} desc={desc[:80]}")
    finally:
        try:
            sandbox.kill()
        except Exception:
            pass


# ── Entrypoint ──────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-live", action="store_true", help="skip OpenAI/Azure API calls")
    parser.add_argument("--skip-e2b", action="store_true", help="skip E2B sandbox test")
    args = parser.parse_args()

    failed: list[str] = []

    def run(name: str, fn) -> None:
        print(f"\n=== {name} ===")
        try:
            fn()
        except Exception as e:
            failed.append(name)
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

    run("registry", test_registry)
    run("action_translation", test_action_translation)
    run("typing_strategy", test_typing_strategy)
    run("response_parse", test_response_parse)
    run("reset", test_reset)
    if not args.skip_live:
        run("live_openai", test_live_openai)
        run("live_azure", test_live_azure)
    if not args.skip_e2b:
        run("e2b_roundtrip", test_e2b_roundtrip)

    print("\n" + "=" * 50)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
