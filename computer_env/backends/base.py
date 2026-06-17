from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class CommandResult:
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@dataclass
class BackgroundCommandHandle:
    command: str
    backend: str
    pid: int | None = None
    raw_handle: Any = None


class CommandExitException(RuntimeError):
    def __init__(
        self,
        command: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout or ""
        self.stderr = stderr or ""
        super().__init__(f"Command failed with exit code {exit_code}: {command}")


class CommandsClient(Protocol):
    def run(
        self,
        command: str,
        timeout: int | None = None,
        background: bool = False,
    ) -> CommandResult | BackgroundCommandHandle: ...


class FilesClient(Protocol):
    def write(self, path: str, data: Any) -> None: ...

    def read(self, path: str, format: str = "text") -> Any: ...

    def remove(self, path: str) -> None: ...


class StreamClient(Protocol):
    def start(self, **kwargs) -> Any: ...

    def get_url(self, **kwargs) -> str: ...

    def stop(self) -> Any: ...


class BaseComputerEnvironment(ABC):
    """Required runtime interface for every computer environment backend."""

    backend_name: str
    commands: CommandsClient
    files: FilesClient
    stream: StreamClient

    @abstractmethod
    def screenshot(self) -> bytes:
        """Return a PNG screenshot of the current desktop."""

    @abstractmethod
    def kill(self) -> None:
        """Release the backend environment and its resources."""

    def create_snapshot(self):
        raise NotImplementedError(f"{self.backend_name} does not support snapshots")

    def get_screen_size(self):
        raise NotImplementedError(f"{self.backend_name} does not expose screen size")
