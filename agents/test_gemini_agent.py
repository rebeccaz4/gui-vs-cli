"""
Smoke test for agents/gemini_agent.py.

The agent now uses gym-anything's text-based generic-desktop ``computer_use``
protocol (see ``gym-anything/agents/agents/claude_gemini.py`` for the
reference), so these tests exercise:

  1. Offline parsing  — always runs. Verifies the agent registers correctly
     and that every action in the tool vocabulary translates to a sane
     pyautogui string without hitting the network.
  2. Live Gemini API  — runs if ``google_ai_studio_api_key`` is set. Sends
     a synthetic screenshot + a trivial instruction and checks that a
     spatial tool_call comes back.
  3. E2B round-trip   — runs if both the Gemini key AND ``E2B_API_KEY``
     are set. Boots an E2B desktop sandbox, screenshots it, feeds that to
     Gemini, and executes the first returned action against the sandbox.

Usage:
  python agents/test_gemini_agent.py
  python agents/test_gemini_agent.py --skip-live
  python agents/test_gemini_agent.py --skip-e2b
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
    draw.text((40, 140), "Gemini computer-use smoke test", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tier 1: offline parsing ─────────────────────────────────────────────────


def test_registry() -> None:
    from agents.registry import create_agent, list_models
    from agents.gemini_agent import GeminiAgent

    aliases = list_models()
    for needed in ("gemini-3-flash", "gemini-3-flash-preview"):
        assert needed in aliases, f"{needed!r} missing from registry ({aliases})"

    a = create_agent("gemini-3-flash", api_key="dummy")
    assert isinstance(a, GeminiAgent)
    assert a.model == "gemini-3-flash-preview"

    b = create_agent("gemini-2.5-computer-use", api_key="dummy")
    assert isinstance(b, GeminiAgent)
    assert b.model == "gemini-2.5-computer-use-preview-10-2025"

    c = create_agent("gemini-99-flash", api_key="dummy")
    assert isinstance(c, GeminiAgent)
    assert c.model == "gemini-99-flash"

    print("[ok] registry wires gemini-3-flash / -preview / fallback")


def test_action_translation() -> None:
    """Every gym-anything-style action should translate without raising."""
    from agents.gemini_agent import GeminiAgent

    agent = GeminiAgent(api_key="dummy", screen_size=(1920, 1080))

    # (action_json, pyautogui substrings that must appear in the output)
    cases = [
        ({"action": "click", "coordinate": [500, 500]}, ["pyautogui.click(960, 540)"]),
        ({"action": "left_click", "coordinate": [500, 500]}, ["pyautogui.click(960, 540)"]),
        ({"action": "right_click", "coordinate": [250, 250]}, ["pyautogui.rightClick(480, 270)"]),
        ({"action": "middle_click", "coordinate": [250, 250]}, ["pyautogui.middleClick(480, 270)"]),
        ({"action": "double_click", "coordinate": [100, 100]}, ["pyautogui.doubleClick(192, 108)"]),
        ({"action": "mouse_move", "coordinate": [250, 250]}, ["pyautogui.moveTo(480, 270"]),
        (
            {"action": "drag", "coordinate": [100, 100], "coordinate2": [900, 900]},
            ["pyautogui.moveTo(192, 108", "pyautogui.dragTo(1728, 972"],
        ),
        (
            {"action": "type", "text": "hi", "clear": True, "enter": True},
            ["pyperclip.copy('hi')", "ctrl", "press('a')", "press('enter')"],
        ),
        ({"action": "key", "keys": ["ctrl", "a"]}, ["hotkey", "'ctrl'", "'a'"]),
        ({"action": "key", "keys": ["Return"]}, ["press('enter')"]),
        ({"action": "scroll", "pixels": -5}, ["pyautogui.scroll(-5)"]),
        (
            {"action": "scroll", "coordinate": [500, 500], "pixels": 3},
            ["pyautogui.scroll(3, 960, 540)"],
        ),
        ({"action": "wait", "time": 2.0}, ["time.sleep(2.0)"]),
    ]

    for action_json, needles in cases:
        code = agent._action_json_to_pyautogui(action_json)
        for needle in needles:
            assert code and needle in code, (
                f"{action_json} produced {code!r} — expected substring {needle!r}"
            )
        first_line = (code or "").strip().splitlines()[0] if code else ""
        print(f"[ok] {action_json['action']:<14} -> {first_line[:80]}")

    # terminate → special tokens
    assert agent._action_json_to_pyautogui({"action": "terminate", "status": "success"}) == "DONE"
    assert agent._action_json_to_pyautogui({"action": "terminate", "status": "failure"}) == "FAIL"
    print("[ok] terminate -> DONE/FAIL")


def test_trim_image_history() -> None:
    """After trim, every Part that remains must still carry valid data —
    no empty inline_data stubs (Gemini rejects those with 400 INVALID_ARGUMENT).
    """
    from google.genai import types

    from agents.gemini_agent import GeminiAgent

    agent = GeminiAgent(api_key="dummy", history_n=2)
    png = _make_fake_screenshot()

    # First turn: instruction text + screenshot.
    agent.contents.append(
        types.Content(role="user", parts=[
            types.Part(text="hello"),
            types.Part.from_bytes(data=png, mime_type="image/png"),
        ])
    )
    # Four more screenshot-only user turns → 5 images total, history_n=2 → 3 drops.
    for _ in range(4):
        agent.contents.append(
            types.Content(role="user", parts=[
                types.Part.from_bytes(data=png, mime_type="image/png"),
            ])
        )

    before = len(agent.contents)
    agent._trim_image_history(agent.history_n)

    # Walk every remaining Part; each must carry either real text or real bytes.
    total_images = 0
    for content in agent.contents:
        for part in content.parts or []:
            text = getattr(part, "text", None)
            inline = getattr(part, "inline_data", None)
            has_blob = inline is not None and getattr(inline, "data", None)
            assert text or has_blob, (
                f"Trim left an empty Part behind: role={content.role} part={part}"
            )
            if has_blob:
                total_images += 1

    # We asked to keep 2 images; dropping 3 should leave at most 2 behind.
    assert total_images <= agent.history_n, (
        f"Trim left {total_images} images but history_n={agent.history_n}"
    )
    # The first-turn instruction text must survive even if its image gets trimmed.
    first_texts = [
        (getattr(p, "text", None) or "")
        for p in (agent.contents[0].parts or [])
    ]
    assert any("hello" in t for t in first_texts), (
        "First-turn instruction text was lost during trim"
    )
    print(f"[ok] trim_image_history: {before} turns in, {len(agent.contents)} out, "
          f"{total_images} image(s) kept, every Part non-empty")


def test_response_parse() -> None:
    """Parsing <tool_call>…</tool_call> should yield reasoning + one action."""
    from agents.gemini_agent import GeminiAgent

    agent = GeminiAgent(api_key="dummy", screen_size=(1920, 1080))

    sample = (
        "I will click the blue button in the top-left corner.\n\n"
        '<tool_call>\n{"name": "computer_use", "arguments": '
        '{"action": "click", "coordinate": [83, 65]}}\n</tool_call>'
    )
    reasoning, actions, is_terminal = agent._parse_response(sample)
    assert "click the blue button" in reasoning, reasoning
    assert not is_terminal
    assert actions and "pyautogui.click(" in actions[0], actions
    print("[ok] tool_call parse: reasoning + 1 click extracted")

    # Terminate tool_call → is_terminal True, empty actions.
    term = (
        'done now\n<tool_call>{"name": "computer_use", "arguments": '
        '{"action": "terminate", "status": "success"}}</tool_call>'
    )
    reasoning, actions, is_terminal = agent._parse_response(term)
    assert is_terminal and not actions
    print("[ok] terminate tool_call → is_terminal flag set")

    # Missing tool_call → empty actions, not terminal.
    reasoning, actions, is_terminal = agent._parse_response("I'm thinking...")
    assert not actions and not is_terminal
    print("[ok] missing tool_call → empty actions + not terminal")

    # <think>...</think> reasoning block is stripped out of the body.
    thinky = (
        "<think>planning my next move</think>\n"
        "clicking now\n"
        '<tool_call>{"name": "computer_use", "arguments": '
        '{"action": "click", "coordinate": [500, 500]}}</tool_call>'
    )
    reasoning, actions, is_terminal = agent._parse_response(thinky)
    assert "planning my next move" in reasoning
    assert actions and "pyautogui.click(960, 540)" in actions[0]
    print("[ok] <think> block folded into reasoning")


# ── Tier 2: live Gemini API ─────────────────────────────────────────────────


def test_live_api() -> None:
    """Drive a real multi-turn computer_use loop against gemini-3-flash-preview."""
    from agents.registry import create_agent

    if not (
        os.environ.get("google_ai_studio_api_key")
        or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print("[skip] live API: no google_ai_studio_api_key set")
        return

    # history_n=2 so trimming kicks in deterministically below.
    # The real run_eval.py failure mode was "empty inline_data after trim"
    # → 400 INVALID_ARGUMENT, so we must verify a live API call succeeds
    # *after* trimming has run.
    agent = create_agent("gemini-3-flash", screen_size=(1920, 1080), history_n=2)
    agent.reset()

    screenshot = _make_fake_screenshot()
    saw_spatial = False

    for turn in range(2):
        reasoning, actions = agent.predict(
            "You see a mock desktop. Click the blue 'Click Me' button "
            "that is near the top-left of the screenshot. Use the click "
            "action with coordinates. When done, call terminate.",
            {"screenshot": screenshot},
        )
        print(f"\n--- turn {turn + 1} ---")
        print(f"  reasoning: {(reasoning or '<empty>')[:160]!r}")
        print(f"  translated actions ({len(actions)}):")
        for a in actions:
            print("      " + a.strip().replace("\n", " | ")[:200])

        # Peek at the last model Content to check the raw tool_call.
        last = agent.contents[-1] if agent.contents else None
        if last is not None and getattr(last, "role", None) == "model":
            raw = ""
            for part in (last.parts or []):
                t = getattr(part, "text", None)
                if t:
                    raw += t
            if "<tool_call>" in raw and any(
                k in raw for k in ("click", "mouse_move", "type", "drag", "scroll")
            ):
                saw_spatial = True

        if actions == ["FAIL"]:
            raise AssertionError(
                f"agent signalled FAIL on turn {turn + 1} — API call failed"
            )

    assert saw_spatial, "Gemini never emitted a spatial tool_call across turns"

    # Now deterministically drive the trim path: stuff in extra screenshot-only
    # user turns until we exceed history_n, then make one more real API call.
    # This directly reproduces the 400 INVALID_ARGUMENT we saw in run_eval.py.
    from google.genai import types as gt

    before_images = sum(
        1 for c in agent.contents for p in (c.parts or [])
        if getattr(p, "inline_data", None) and getattr(p.inline_data, "data", None)
    )
    # Pad with 3 extra screenshot-bearing user turns.
    for _ in range(3):
        agent.contents.append(
            gt.Content(role="user", parts=[
                gt.Part.from_bytes(data=screenshot, mime_type="image/png"),
            ])
        )
    assert before_images + 3 > agent.history_n, "test padding did not exceed history_n"

    print(f"\n[trim check] pre-trim contents: {len(agent.contents)} turns, "
          f"{before_images + 3} images. Firing one more predict()…")

    reasoning, actions = agent.predict(
        "Look at the current screenshot and briefly describe what you see.",
        {"screenshot": screenshot},
    )
    print(f"  post-trim reasoning: {(reasoning or '<empty>')[:160]!r}")
    print(f"  post-trim actions: {actions}")

    if actions == ["FAIL"]:
        raise AssertionError(
            "Post-trim predict() returned FAIL — this is the run_eval.py bug "
            "(likely 400 INVALID_ARGUMENT from empty inline_data). Trim path is broken."
        )

    # After trim, every Part must carry real content — this is exactly what
    # the API validates on us.
    for ci, content in enumerate(agent.contents):
        for pi, part in enumerate(content.parts or []):
            text = getattr(part, "text", None)
            inline = getattr(part, "inline_data", None)
            has_blob = inline is not None and getattr(inline, "data", None)
            fc = getattr(part, "function_call", None)
            fr = getattr(part, "function_response", None)
            assert text or has_blob or fc or fr, (
                f"Empty Part left at contents[{ci}].parts[{pi}] after trim"
            )

    print("\n[ok] live API: spatial tool_call + successful post-trim round-trip")


# ── Tier 3: E2B round-trip ──────────────────────────────────────────────────


def test_e2b_roundtrip() -> None:
    if not os.environ.get("E2B_API_KEY"):
        print("[skip] E2B round-trip: E2B_API_KEY not set")
        return
    if not (
        os.environ.get("google_ai_studio_api_key")
        or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print("[skip] E2B round-trip: google_ai_studio_api_key not set")
        return

    from e2b_desktop import Sandbox

    from agents.registry import create_agent

    print("[..] E2B: starting sandbox (this can take ~30s)")
    sandbox = Sandbox()
    try:
        sandbox.stream.start()
        agent = create_agent("gemini-3-flash", screen_size=(1920, 1080))
        agent.reset()

        shot = sandbox.screenshot()
        reasoning, actions = agent.predict(
            "Open the Files application from the taskbar.",
            {"screenshot": shot},
        )
        print(f"[ok] E2B first predict: reasoning={reasoning[:120]!r}")
        print(f"     actions={len(actions)}")
        for a in actions[:3]:
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
    parser.add_argument("--skip-live", action="store_true", help="skip Gemini API call")
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
    run("trim_image_history", test_trim_image_history)
    run("response_parse", test_response_parse)
    if not args.skip_live:
        run("live_api", test_live_api)
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
