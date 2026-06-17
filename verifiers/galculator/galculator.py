"""
galculator Verifier — programmatic state inspection for galculator in E2B sandbox.

Verification channels (in order of preference):
  1. AT-SPI (accessibility tree) — read display value, buttons, mode, window info
  2. xdotool fallback — window existence, title, position/size

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/galculator.py display")
    sandbox.commands.run("python3 /home/user/verifiers/galculator.py check-display-value 42")
    sandbox.commands.run("python3 /home/user/verifiers/galculator.py buttons")

Usage from Python (inside sandbox or via E2B):
    from verifiers.galculator import GalculatorVerifier
    v = GalculatorVerifier()
    display = v.get_display()
    buttons = v.get_buttons()

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - galculator running
  - python3-gi with Atspi 2.0 (for AT-SPI queries)
  - xdotool (fallback for window queries)
"""

import json
import os
import subprocess
import sys
from typing import Any, Optional

# ---------------------------------------------------------------------------
# AT-SPI helpers
# ---------------------------------------------------------------------------

def _get_atspi():
    """Import and return the Atspi module, or None if unavailable."""
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        return Atspi
    except (ImportError, ValueError):
        return None


def _find_galculator_app(Atspi):
    """Find the galculator application in the AT-SPI tree.

    Returns the Atspi.Accessible for the galculator app, or None.
    """
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is None:
            continue
        name = app.get_name()
        if name and "galculator" in name.lower():
            return app
    return None


def _walk_tree(node, visitor, depth=0, max_depth=20):
    """Recursively walk AT-SPI tree, calling visitor(node, depth) on each node.

    visitor should return a value to collect, or None to skip.
    """
    if depth > max_depth:
        return []
    results = []
    val = visitor(node, depth)
    if val is not None:
        results.append(val)
    try:
        count = node.get_child_count()
    except Exception:
        return results
    for i in range(count):
        try:
            child = node.get_child_at_index(i)
            if child is not None:
                results.extend(_walk_tree(child, visitor, depth + 1, max_depth))
        except Exception:
            continue
    return results


def _get_node_text(node) -> Optional[str]:
    """Extract text from an AT-SPI node using multiple strategies."""
    # Try the Text interface
    try:
        iface = node.get_text_iface()
        if iface is not None:
            text = iface.get_text(0, iface.get_character_count())
            if text:
                return text
    except Exception:
        pass

    # Try the Value interface (some widgets expose numeric value)
    try:
        iface = node.get_value_iface()
        if iface is not None:
            return str(iface.get_current_value())
    except Exception:
        pass

    # Try the name property (labels often use this)
    try:
        name = node.get_name()
        if name:
            return name
    except Exception:
        pass

    return None


def _get_node_role_name(node) -> str:
    """Get the role name of an AT-SPI node."""
    try:
        return node.get_role_name()
    except Exception:
        return "unknown"


def _find_display_text(app) -> Optional[str]:
    """Walk the galculator AT-SPI tree to find the display widget text.

    galculator's display is typically a GtkEntry or GtkLabel. We look for
    text/label/entry roles that contain numeric-looking content, or the
    first substantial text widget in the window.
    """
    candidates = []

    def visitor(node, depth):
        role = _get_node_role_name(node)
        # The display is usually an entry, label, or text widget
        if role in ("text", "label", "entry", "editbar", "edit bar",
                     "status bar", "panel", "filler"):
            text = _get_node_text(node)
            if text is not None and text.strip():
                return {"role": role, "text": text.strip(), "depth": depth}
        return None

    candidates = _walk_tree(app, visitor)

    if not candidates:
        return None

    # Prefer entry/text roles (the actual display input)
    for c in candidates:
        if c["role"] in ("entry", "text", "editbar", "edit bar"):
            return c["text"]

    # Prefer labels that look numeric (calculator display)
    for c in candidates:
        if c["role"] == "label":
            t = c["text"]
            # Check if it looks like a number or expression
            cleaned = t.replace(",", "").replace(".", "").replace("-", "").replace("+", "").replace("e", "").replace("E", "").strip()
            if cleaned.isdigit() or t in ("0", "0.", "0.0"):
                return t

    # Fall back to first label
    for c in candidates:
        if c["role"] == "label":
            return c["text"]

    # Last resort: first candidate
    return candidates[0]["text"] if candidates else None


# ---------------------------------------------------------------------------
# xdotool fallback helpers
# ---------------------------------------------------------------------------

def _run_cmd(cmd: str, timeout: int = 5) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)


def _xdotool_find_window() -> Optional[str]:
    """Find galculator window ID using xdotool."""
    code, stdout, _ = _run_cmd("xdotool search --name galculator 2>/dev/null")
    if code == 0 and stdout.strip():
        # Return first window ID
        return stdout.strip().split("\n")[0]
    # Try class name
    code, stdout, _ = _run_cmd("xdotool search --class galculator 2>/dev/null")
    if code == 0 and stdout.strip():
        return stdout.strip().split("\n")[0]
    return None


def _xdotool_get_window_info(wid: str) -> dict:
    """Get window geometry and name via xdotool."""
    info = {"window_id": wid}
    code, stdout, _ = _run_cmd(f"xdotool getwindowname {wid}")
    if code == 0:
        info["title"] = stdout
    code, stdout, _ = _run_cmd(f"xdotool getwindowgeometry {wid}")
    if code == 0:
        # Parse "Window 12345\n  Position: 100,200 (screen: 0)\n  Geometry: 300x400"
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("Position:"):
                pos = line.split(":")[1].strip().split("(")[0].strip()
                parts = pos.split(",")
                if len(parts) == 2:
                    info["x"] = int(parts[0])
                    info["y"] = int(parts[1])
            elif line.startswith("Geometry:"):
                geo = line.split(":")[1].strip()
                parts = geo.split("x")
                if len(parts) == 2:
                    info["width"] = int(parts[0])
                    info["height"] = int(parts[1])
    return info


# ---------------------------------------------------------------------------
# GalculatorVerifier class
# ---------------------------------------------------------------------------

class GalculatorVerifier:
    """Stateless verifier — each method call is independent."""

    # === Query endpoints ===

    def get_display(self) -> dict:
        """Read the current calculator display value via AT-SPI.

        Returns:
            {"display": "42", "source": "atspi"} on success
            {"display": null, "error": "..."} on failure

        Falls back to xdotool window title if AT-SPI is unavailable.
        """
        Atspi = _get_atspi()
        if Atspi is not None:
            app = _find_galculator_app(Atspi)
            if app is not None:
                text = _find_display_text(app)
                if text is not None:
                    return {"display": text, "source": "atspi"}
                return {"display": None, "error": "Display widget not found in AT-SPI tree", "source": "atspi"}
            # AT-SPI available but galculator not found
            return {"display": None, "error": "galculator not found in AT-SPI tree. Is it running?"}

        # Fallback: xdotool window title (some apps put state in title)
        wid = _xdotool_find_window()
        if wid:
            code, title, _ = _run_cmd(f"xdotool getwindowname {wid}")
            if code == 0 and title:
                return {"display": title, "source": "xdotool_title",
                        "note": "AT-SPI unavailable; showing window title as fallback"}
        return {"display": None, "error": "AT-SPI unavailable and xdotool could not find galculator window"}

    def get_window_info(self) -> dict:
        """Get galculator window info (title, position, size, state).

        Tries AT-SPI first, then xdotool fallback.
        """
        Atspi = _get_atspi()
        if Atspi is not None:
            app = _find_galculator_app(Atspi)
            if app is not None:
                info = {"source": "atspi", "app_name": app.get_name()}
                # Get first window child
                try:
                    for i in range(app.get_child_count()):
                        child = app.get_child_at_index(i)
                        if child and _get_node_role_name(child) in ("frame", "window", "dialog"):
                            info["title"] = child.get_name() or ""
                            try:
                                comp = child.get_component_iface()
                                if comp:
                                    rect = comp.get_extents(0)  # 0 = screen coords
                                    info["x"] = rect.x
                                    info["y"] = rect.y
                                    info["width"] = rect.width
                                    info["height"] = rect.height
                            except Exception:
                                pass
                            break
                except Exception:
                    pass
                return info

        # Fallback: xdotool
        wid = _xdotool_find_window()
        if wid:
            info = _xdotool_get_window_info(wid)
            info["source"] = "xdotool"
            return info

        return {"error": "galculator window not found"}

    def get_buttons(self) -> dict:
        """List available buttons from the AT-SPI tree.

        Returns:
            {"buttons": ["1", "2", ..., "+", "-", "=", ...], "count": N}
        """
        Atspi = _get_atspi()
        if Atspi is None:
            return {"error": "AT-SPI (python3-gi Atspi) not available"}

        app = _find_galculator_app(Atspi)
        if app is None:
            return {"error": "galculator not found in AT-SPI tree. Is it running?"}

        buttons = []

        def visitor(node, depth):
            role = _get_node_role_name(node)
            if role in ("push button", "toggle button", "button"):
                name = ""
                try:
                    name = node.get_name() or ""
                except Exception:
                    pass
                if name:
                    return name
            return None

        buttons = _walk_tree(app, visitor)
        return {"buttons": buttons, "count": len(buttons)}

    def get_mode(self) -> dict:
        """Detect calculator mode (basic, scientific, etc.) from AT-SPI or window info.

        Heuristic: look at window title and number of buttons to distinguish modes.
        """
        Atspi = _get_atspi()
        if Atspi is not None:
            app = _find_galculator_app(Atspi)
            if app is not None:
                # Check window title for mode hints
                title = ""
                try:
                    for i in range(app.get_child_count()):
                        child = app.get_child_at_index(i)
                        if child and _get_node_role_name(child) in ("frame", "window"):
                            title = child.get_name() or ""
                            break
                except Exception:
                    pass

                # Count buttons as a heuristic
                btn_data = self.get_buttons()
                btn_count = btn_data.get("count", 0)
                btn_names = btn_data.get("buttons", [])

                # Detect mode from button set
                mode = "basic"
                sci_indicators = {"sin", "cos", "tan", "log", "ln", "exp", "pi",
                                  "sin(", "cos(", "tan(", "log(", "ln("}
                if any(b.lower() in sci_indicators for b in btn_names):
                    mode = "scientific"

                prog_indicators = {"AND", "OR", "XOR", "NOT", "hex", "dec", "oct", "bin",
                                   "and", "or", "xor", "not", "HEX", "DEC", "OCT", "BIN"}
                if any(b in prog_indicators for b in btn_names):
                    mode = "programming"

                return {
                    "mode": mode,
                    "title": title,
                    "button_count": btn_count,
                    "source": "atspi",
                }

        # Fallback: window title
        wid = _xdotool_find_window()
        if wid:
            code, title, _ = _run_cmd(f"xdotool getwindowname {wid}")
            mode = "unknown"
            if code == 0:
                tl = title.lower()
                if "scientific" in tl:
                    mode = "scientific"
                elif "programming" in tl or "programmer" in tl:
                    mode = "programming"
                elif "basic" in tl or "galculator" in tl:
                    mode = "basic"
            return {"mode": mode, "title": title, "source": "xdotool"}

        return {"error": "galculator not found"}

    # === Check endpoints ===

    def check_running(self) -> dict:
        """Check if galculator is running (pgrep).

        Returns:
            {"running": true, "pid": "12345"}
        """
        code, stdout, _ = _run_cmd("pgrep -x galculator")
        if code == 0 and stdout.strip():
            pids = stdout.strip().split("\n")
            return {"running": True, "pid": pids[0], "pid_count": len(pids)}
        # Also try broader match, excluding python/pgrep processes
        code, stdout, _ = _run_cmd(
            "pgrep -f galculator | while read pid; do "
            "  name=$(cat /proc/$pid/comm 2>/dev/null); "
            "  if [ \"$name\" = \"galculator\" ]; then echo $pid; fi; "
            "done"
        )
        if code == 0 and stdout.strip():
            pids = stdout.strip().split("\n")
            return {"running": True, "pid": pids[0], "pid_count": len(pids),
                    "note": "Found via pgrep -f (broad match)"}
        return {"running": False}

    def check_display_value(self, expected: str) -> dict:
        """Check if the calculator display shows the expected value exactly.

        Performs string comparison after stripping whitespace.

        Returns:
            {"match": true, "expected": "42", "actual": "42"}
        """
        result = self.get_display()
        actual = result.get("display")
        if actual is None:
            return {"match": False, "expected": expected, "actual": None,
                    "error": result.get("error", "Could not read display")}
        match = actual.strip() == expected.strip()
        return {"match": match, "expected": expected, "actual": actual}

    def check_display_contains(self, text: str) -> dict:
        """Check if the calculator display contains the given text.

        Returns:
            {"contains": true, "text": "42", "display": "42.0"}
        """
        result = self.get_display()
        actual = result.get("display")
        if actual is None:
            return {"contains": False, "text": text, "display": None,
                    "error": result.get("error", "Could not read display")}
        contains = text in actual
        return {"contains": contains, "text": text, "display": actual}

    def check_window_exists(self) -> dict:
        """Check if a galculator window exists.

        Tries AT-SPI first, then xdotool fallback.

        Returns:
            {"exists": true, "source": "atspi"}
        """
        Atspi = _get_atspi()
        if Atspi is not None:
            app = _find_galculator_app(Atspi)
            if app is not None:
                return {"exists": True, "source": "atspi"}
            # AT-SPI available but app not found; also try xdotool
            wid = _xdotool_find_window()
            if wid:
                return {"exists": True, "source": "xdotool"}
            return {"exists": False}

        # AT-SPI unavailable, try xdotool only
        wid = _xdotool_find_window()
        if wid:
            return {"exists": True, "source": "xdotool"}
        return {"exists": False}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query endpoints
    "display":       ("Read current calculator display value",
                      lambda v, args: v.get_display()),
    "window-info":   ("Get galculator window info (title, position, size)",
                      lambda v, args: v.get_window_info()),
    "buttons":       ("List available buttons from AT-SPI tree",
                      lambda v, args: v.get_buttons()),
    "mode":          ("Detect calculator mode (basic, scientific, etc.)",
                      lambda v, args: v.get_mode()),

    # Check endpoints
    "check-running":          ("Check if galculator is running",
                               lambda v, args: v.check_running()),
    "check-display-value":    ("Check display shows expected value",
                               lambda v, args: v.check_display_value(args[0])),
    "check-display-contains": ("Check display contains text",
                               lambda v, args: v.check_display_contains(args[0])),
    "check-window-exists":    ("Check galculator window exists",
                               lambda v, args: v.check_window_exists()),
}


def _print_usage():
    print("galculator Verifier — query galculator state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. Requires galculator running with AT-SPI enabled.")
    print("Fallback: xdotool for window-level queries.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = GalculatorVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
