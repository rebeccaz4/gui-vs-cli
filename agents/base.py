"""
Base agent interface that all model-specific agents implement.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("agents")

PYAUTOGUI_PREAMBLE = "import pyautogui; import pyperclip; import time; pyautogui.FAILSAFE = False; "


class BaseAgent(ABC):
    """
    Common interface for all GUI automation agents.

    Every agent:
      - Takes a task instruction + screenshot observation
      - Calls an LLM API
      - Parses the response into pyautogui code strings
      - Returns (reasoning, actions)
      - Executes actions on an E2B sandbox via execute_action()

    Actions are either:
      - pyautogui code strings  (e.g. "pyautogui.click(960, 540)")
      - Special tokens: "DONE", "FAIL", "WAIT"
    """

    def __init__(
        self,
        model: str,
        platform: str = "ubuntu",
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        screen_size: Tuple[int, int] = (1920, 1080),
        max_steps: int = 30,
        password: str = "password",
        **kwargs,
    ):
        self.model = model
        self.platform = platform.lower()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.screen_size = screen_size
        self.max_steps = max_steps
        self.password = password
        self.last_raw_response = None  # Set by predict(); serializable model response

    @abstractmethod
    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        """
        Predict the next action(s) given a task instruction and observation.

        Args:
            instruction: Natural language task description.
            obs: Dictionary with at least {"screenshot": bytes} (PNG).

        Returns:
            (reasoning, actions) where actions is a list of pyautogui code
            strings or special tokens ("DONE", "FAIL", "WAIT").
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear all conversation / step history for a new task."""
        ...

    def execute_action(self, sandbox, action_code: str) -> Tuple[bool, str]:
        """Execute a single action string on a desktop environment backend.

        Runs the pyautogui code inside the sandbox via python3 -c.
        Subclasses can override for non-pyautogui action formats.

        Args:
            sandbox: A desktop environment object exposing `.commands.run(...)`.
            action_code: A pyautogui code string returned by predict().

        Returns:
            (success, description) tuple.
        """
        return _run_pyautogui_in_sandbox(sandbox, action_code)

    @property
    def name(self) -> str:
        return f"{self.__class__.__name__}({self.model})"


def _run_pyautogui_in_sandbox(sandbox, code: str) -> Tuple[bool, str]:
    """Run pyautogui code string inside the desktop environment via python3 -c."""
    from computer_env.backends.base import CommandExitException

    # Collapse multi-line code into semicolons for -c usage
    lines = [l.strip() for l in code.strip().splitlines() if l.strip()]
    oneliner = PYAUTOGUI_PREAMBLE + "; ".join(lines)

    try:
        result = sandbox.commands.run(
            f"DISPLAY=:0 python3 -c {_shell_quote(oneliner)}",
            timeout=100,
        )
        output = (result.stdout or "") + (result.stderr or "")
        # Build a short description from the code for logging
        desc = lines[0][:60] if lines else "ok"
        return True, desc
    except CommandExitException as e:
        err = (e.stdout or "") + (e.stderr or "")
        return False, err.strip()[:500]
    except Exception as e:
        return False, str(e)[:500]


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell use via $'...' syntax."""
    escaped = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return f"$'{escaped}'"
