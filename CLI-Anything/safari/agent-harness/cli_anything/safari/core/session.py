"""Session state for Safari CLI.

Safari MCP is stateless per call — each MCP invocation starts a fresh
process. The CLI keeps a tiny amount of in-memory state for REPL display
only:

- last_url: last URL the CLI navigated to (for the REPL prompt context)
- current_tab_index: last known active tab index (for the REPL prompt)

There is no filesystem-tree abstraction like DOMShell — Safari MCP works
with tabs and refs from snapshots.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    current_tab_index: Optional[int] = None
    last_url: str = ""

    def set_url(self, url: str) -> None:
        self.last_url = url

    def set_tab(self, index: int) -> None:
        self.current_tab_index = index

    def status(self) -> dict:
        return {
            "last_url": self.last_url or "(no navigation yet)",
            "current_tab_index": self.current_tab_index,
        }
