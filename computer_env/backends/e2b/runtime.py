from __future__ import annotations

import atexit
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from computer_env.backends.base import (
    BackgroundCommandHandle,
    BaseComputerEnvironment,
    CommandExitException,
    CommandResult,
)
from computer_env.config import EnvCreateOptions

E2B_SCREENSHOT_ATTEMPTS = 3
E2B_SCREENSHOT_COMMAND_TIMEOUT = 15
E2B_SCREENSHOT_READ_TIMEOUT = 30
E2B_SCREENSHOT_RETRY_DELAY_SECONDS = 1.0
_ACTIVE_SANDBOXES: dict[str, Any] = {}
_ACTIVE_SANDBOXES_LOCK = threading.Lock()


def _ensure_vendor_paths() -> None:
    project_root = Path(__file__).resolve().parents[3]
    sdk_paths = [
        project_root / "E2B" / "packages" / "python-sdk",
        project_root / "desktop" / "packages" / "python-sdk",
    ]
    for path in sdk_paths:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)


def _load_e2b_sdk():
    _ensure_vendor_paths()
    try:
        from e2b.sandbox.commands.command_handle import CommandExitException as E2BCommandExitException
        from e2b_desktop import Sandbox as E2BSandbox
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "E2B SDK is not available. Install the local SDKs with "
            "`pip install -r requirements.txt` or activate the existing E2B environment."
        ) from exc
    return E2BSandbox, E2BCommandExitException


def _sandbox_id(sandbox: Any) -> str | None:
    sandbox_id = getattr(sandbox, "sandbox_id", None)
    if sandbox_id is None:
        return None
    return str(sandbox_id)


def _register_active_sandbox(sandbox: Any) -> None:
    sandbox_id = _sandbox_id(sandbox)
    if sandbox_id is None:
        return
    with _ACTIVE_SANDBOXES_LOCK:
        _ACTIVE_SANDBOXES[sandbox_id] = sandbox


def _unregister_active_sandbox(sandbox_or_id: Any) -> None:
    sandbox_id = sandbox_or_id if isinstance(sandbox_or_id, str) else _sandbox_id(sandbox_or_id)
    if sandbox_id is None:
        return
    with _ACTIVE_SANDBOXES_LOCK:
        _ACTIVE_SANDBOXES.pop(sandbox_id, None)


def _kill_sandbox_with_api_fallback(sandbox: Any) -> bool:
    sandbox_id = _sandbox_id(sandbox)
    killed = False

    try:
        sandbox.kill(request_timeout=10)
        return True
    except TypeError:
        try:
            sandbox.kill()
            return True
        except Exception:
            pass
    except Exception:
        pass

    if sandbox_id is None:
        return False

    try:
        from .cleanup_sandboxes import kill_sandbox

        killed = kill_sandbox(sandbox_id)
    except Exception:
        killed = False

    return killed


def cleanup_active_e2b_sandboxes() -> list[str]:
    with _ACTIVE_SANDBOXES_LOCK:
        sandboxes = list(_ACTIVE_SANDBOXES.items())

    cleaned: list[str] = []
    for sandbox_id, sandbox in sandboxes:
        killed = _kill_sandbox_with_api_fallback(sandbox)
        _unregister_active_sandbox(sandbox_id)
        if killed:
            cleaned.append(sandbox_id)

    return cleaned


def cleanup_e2b_sandboxes_by_metadata(metadata: dict[str, str]) -> list[str]:
    if not metadata:
        return []

    try:
        from .cleanup_sandboxes import kill_sandbox, list_sandboxes
    except Exception:
        return []

    cleaned: list[str] = []
    try:
        sandboxes = list_sandboxes()
    except Exception:
        return []

    for sandbox in sandboxes:
        if not all(sandbox.metadata.get(key) == value for key, value in metadata.items()):
            continue
        try:
            if kill_sandbox(sandbox.sandbox_id):
                cleaned.append(sandbox.sandbox_id)
        except Exception:
            continue

    return cleaned


atexit.register(cleanup_active_e2b_sandboxes)


class E2BCommandsClient:
    def __init__(self, sandbox, e2b_exit_exception) -> None:
        self._sandbox = sandbox
        self._e2b_exit_exception = e2b_exit_exception

    def run(self, command: str, timeout: int | None = None, background: bool = False):
        try:
            result = self._sandbox.commands.run(command, timeout=timeout, background=background)
        except self._e2b_exit_exception as exc:
            raise CommandExitException(
                command=command,
                exit_code=getattr(exc, "exit_code", 1),
                stdout=getattr(exc, "stdout", ""),
                stderr=getattr(exc, "stderr", ""),
            ) from exc

        if background:
            return BackgroundCommandHandle(
                command=command,
                backend="e2b",
                pid=getattr(result, "pid", None),
                raw_handle=result,
            )

        return CommandResult(
            command=command,
            stdout=getattr(result, "stdout", "") or "",
            stderr=getattr(result, "stderr", "") or "",
            exit_code=getattr(result, "exit_code", 0) or 0,
        )


class E2BFilesClient:
    def __init__(self, sandbox) -> None:
        self._sandbox = sandbox

    def write(self, path: str, data) -> None:
        self._sandbox.files.write(path, data)

    def read(self, path: str, format: str = "text"):
        return self._sandbox.files.read(path, format=format)

    def remove(self, path: str) -> None:
        self._sandbox.files.remove(path)


class E2BStreamClient:
    def __init__(self, sandbox) -> None:
        self._sandbox = sandbox

    def start(self, **kwargs):
        return self._sandbox.stream.start(**kwargs)

    def get_url(self, **kwargs):
        return self._sandbox.stream.get_url(**kwargs)

    def stop(self):
        return self._sandbox.stream.stop()


class E2BEnvironment(BaseComputerEnvironment):
    backend_name = "e2b"

    def __init__(self, sandbox, e2b_exit_exception) -> None:
        self._sandbox = sandbox
        _register_active_sandbox(sandbox)
        self.commands = E2BCommandsClient(sandbox, e2b_exit_exception)
        self.files = E2BFilesClient(sandbox)
        self.stream = E2BStreamClient(sandbox)

    def screenshot(self):
        last_error = None

        for attempt in range(1, E2B_SCREENSHOT_ATTEMPTS + 1):
            screenshot_path = f"/tmp/gui_synth_env_screenshot_{uuid4().hex}.png"
            try:
                self.commands.run(
                    f"scrot --pointer {screenshot_path}",
                    timeout=E2B_SCREENSHOT_COMMAND_TIMEOUT,
                )
                data = self._sandbox.files.read(
                    screenshot_path,
                    format="bytes",
                    request_timeout=E2B_SCREENSHOT_READ_TIMEOUT,
                )
                self.commands.run(f"rm -f {screenshot_path}", timeout=5)
                return bytes(data)
            except Exception as exc:
                last_error = exc
                try:
                    self.commands.run(f"rm -f {screenshot_path}", timeout=5)
                except Exception:
                    pass
                if attempt < E2B_SCREENSHOT_ATTEMPTS:
                    time.sleep(E2B_SCREENSHOT_RETRY_DELAY_SECONDS)

        diagnostics = []
        for label, command in (
            ("focused_window", "xdotool getwindowfocus getwindowname 2>/dev/null || true"),
            ("desktop_processes", "pgrep -af 'scrot|xfce4-session|xfwm4|Xvfb' || true"),
        ):
            try:
                result = self.commands.run(command, timeout=5)
                output = result.stdout.strip() or result.stderr.strip() or "<empty>"
            except Exception as exc:
                output = f"<diagnostic failed: {exc}>"
            diagnostics.append(f"{label}={output}")

        raise RuntimeError(
            "E2B screenshot failed after "
            f"{E2B_SCREENSHOT_ATTEMPTS} attempts: {last_error}. "
            + "; ".join(diagnostics)
        )

    def kill(self) -> None:
        sandbox_id = _sandbox_id(self._sandbox)
        try:
            if not _kill_sandbox_with_api_fallback(self._sandbox):
                raise RuntimeError(f"failed to kill E2B sandbox {sandbox_id or '<unknown>'}")
        finally:
            _unregister_active_sandbox(sandbox_id or self._sandbox)

    def create_snapshot(self):
        return self._sandbox.create_snapshot()

    def get_screen_size(self):
        return self._sandbox.get_screen_size()


def create_e2b_env(options: EnvCreateOptions) -> E2BEnvironment:
    sandbox_cls, e2b_exit_exception = _load_e2b_sdk()
    sandbox = sandbox_cls.create(
        template=options.template,
        timeout=options.timeout,
        resolution=options.resolution,
        metadata=options.e2b_metadata,
    )
    return E2BEnvironment(sandbox, e2b_exit_exception)
