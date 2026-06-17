# galculator Verifier

Programmatic state inspection for **galculator** (GTK-based calculator) running in an E2B desktop sandbox.

## Verification Channels

| Priority | Channel | What it reads |
|----------|---------|---------------|
| 1 (primary) | **AT-SPI** (accessibility tree) | Display value, buttons, mode, window info |
| 2 (fallback) | **xdotool** | Window existence, title, position/size |

galculator has **no CLI, no API, and no file-based state**. AT-SPI is the only way to read the calculator display programmatically.

## Requirements

- `galculator` running in the sandbox
- `python3-gi` with `Atspi 2.0` (`gir1.2-atspi-2.0`, `at-spi2-core`)
- `xdotool` (fallback)

Install in sandbox:
```bash
sudo apt-get install -y python3-gi gir1.2-atspi-2.0 at-spi2-core xdotool
```

## CLI Usage

```bash
# Upload to sandbox, then run:
python3 /home/user/verifiers/galculator.py <command> [args...]

# Examples:
python3 /home/user/verifiers/galculator.py display
python3 /home/user/verifiers/galculator.py check-display-value 42
python3 /home/user/verifiers/galculator.py buttons
python3 /home/user/verifiers/galculator.py --help
```

All output is JSON printed to stdout.

## Commands

### Query

| Command | Description |
|---------|-------------|
| `display` | Read the current calculator display value |
| `window-info` | Get galculator window info (title, position, size) |
| `buttons` | List available buttons from AT-SPI tree |
| `mode` | Detect calculator mode (basic, scientific, etc.) |

### Check

| Command | Args | Description |
|---------|------|-------------|
| `check-running` | — | Check if galculator is running (pgrep) |
| `check-display-value` | `<expected>` | Display shows expected value (exact match) |
| `check-display-contains` | `<text>` | Display contains text (substring match) |
| `check-window-exists` | — | galculator window exists |

## Python Usage

```python
from verifiers.galculator import GalculatorVerifier

v = GalculatorVerifier()
display = v.get_display()        # {"display": "42", "source": "atspi"}
buttons = v.get_buttons()        # {"buttons": ["1", "2", ...], "count": 20}
mode = v.get_mode()              # {"mode": "basic", ...}
running = v.check_running()      # {"running": true, "pid": "12345"}
```

## AT-SPI Tree Walking

The verifier finds the display value by:

1. Getting the desktop via `Atspi.get_desktop(0)`
2. Iterating applications to find one named "galculator"
3. Recursively walking children looking for text-bearing widgets
4. Checking `entry`, `text`, `editbar`, and `label` roles
5. Returning the text content from the display widget

galculator typically exposes its display as a `GtkEntry` (role: `entry`) or `GtkLabel` (role: `label`).

## Example Test Flow

```python
# Type keys with xdotool, then verify with the verifier
sandbox.commands.run("xdotool key 1 2 3 plus 4 5 6 Return")
result = sandbox.commands.run("python3 /home/user/verifiers/galculator.py check-display-value 579")
data = json.loads(result.stdout)
assert data["match"] is True
```

## Running Tests

```bash
python verifiers/galculator/test_galculator.py
```

Requires `e2b_desktop` and a valid E2B API key. Tests launch galculator in a sandbox, type keys via xdotool, and verify the display via AT-SPI.
