"""
Interactive Chrome verifier demo — launches a sandbox, runs a few
verifier commands, and prints the sandbox desktop URL so you can
watch what's happening in the browser.

Usage:
    python verifiers/chrome/demo_chrome.py
"""

import json
import time
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "chrome.py"
VERIFIER_REMOTE = "/home/user/verifiers/chrome.py"
V = f"python3 {VERIFIER_REMOTE}"


def run(sandbox, cmd, timeout=30):
    try:
        r = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return json.loads(r.stdout)
    except CommandExitException as e:
        try:
            return json.loads(e.stdout)
        except Exception:
            return {"error": e.stderr[:300]}
    except Exception as e:
        return {"error": str(e)}


def pp(label, data):
    print(f"\n--- {label} ---")
    print(json.dumps(data, indent=2)[:600])


def main():
    print("Creating sandbox...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        sandbox.stream.start()
    except RuntimeError:
        pass
    stream_url = sandbox.stream.get_url(resize="scale")
    print(f"\n{'='*60}")
    print(f"Sandbox ID : {sandbox.sandbox_id}")
    print(f"Desktop URL: {stream_url}")
    print(f"{'='*60}")
    print("Open the Desktop URL above to watch the sandbox screen.\n")

    try:
        # Upload verifier
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())
        sandbox.commands.run("pip install websocket-client -q", timeout=60)

        # Launch Chrome
        print("Launching Chrome...")
        sandbox.commands.run(
            "google-chrome --no-first-run --no-default-browser-check "
            "--no-sandbox --disable-dev-shm-usage --disable-gpu "
            "--disable-background-networking --disable-sync "
            "--disable-translate --disable-extensions "
            "--remote-debugging-port=9222 "
            "--remote-allow-origins=* "
            "--user-data-dir=/tmp/chrome-test-profile "
            "about:blank > /tmp/chrome.log 2>&1",
            background=True,
        )

        # Wait for CDP
        for i in range(20):
            try:
                r = sandbox.commands.run("curl -s http://127.0.0.1:9222/json", timeout=3)
                if r.stdout.strip().startswith("["):
                    print(f"Chrome CDP ready (attempt {i+1})")
                    break
            except (CommandExitException, Exception):
                pass
            time.sleep(1)
        else:
            print("WARNING: CDP not ready")

        # ---------- Demo commands ----------

        pp("tabs", run(sandbox, "tabs"))

        pp("navigate to example.com",
           run(sandbox, "navigate https://example.com", timeout=15))
        time.sleep(3)

        pp("current url", run(sandbox, "url"))
        pp("page title", run(sandbox, "title"))
        pp("page text", run(sandbox, "text"))

        pp("eval document.title",
           run(sandbox, "eval 'document.title'"))

        pp("navigate to github.com",
           run(sandbox, "navigate https://github.com", timeout=15))
        time.sleep(3)

        pp("current url", run(sandbox, "url"))
        pp("check-tab-open github.com",
           run(sandbox, "check-tab-open github.com"))

        pp("check-page-contains 'GitHub'",
           run(sandbox, 'check-page-contains "GitHub"'))

        time.sleep(3)
        pp("history", run(sandbox, "history"))

        pp("check-url-visited example.com",
           run(sandbox, "check-url-visited example.com"))

        pp("bookmarks", run(sandbox, "bookmarks"))
        pp("cookies", run(sandbox, "cookies"))
        pp("extensions", run(sandbox, "extensions"))

        # Keep sandbox alive so you can inspect the desktop
        print(f"\n{'='*60}")
        print("Sandbox is still running. Press Enter to kill it.")
        print(f"Desktop URL: {stream_url}")
        print(f"{'='*60}")
        input()

    finally:
        sandbox.kill()
        print("Sandbox killed.")


if __name__ == "__main__":
    main()
