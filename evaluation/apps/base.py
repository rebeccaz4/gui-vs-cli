from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

TaskDict = dict[str, Any]
AppHook = Callable[["AppContext"], None]
LaunchBuilder = Callable[["AppContext"], str]
ReadyCheck = Callable[[Any], bool]


def _always_ready(_sandbox) -> bool:
    return True


@dataclass(slots=True)
class AppContext:
    sandbox: Any
    app_spec: "AppSpec"
    task: TaskDict | None = None
    env_backend: str = "e2b"
    display_width: int = 1920
    display_height: int = 1080

    @property
    def task_files(self) -> list[dict[str, Any]]:
        if not self.task:
            return []
        return list(self.task.get("env", {}).get("files", []))

    def list_task_paths(
        self,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[str]:
        paths: list[str] = []
        for file_entry in self.task_files:
            if predicate is not None and not predicate(file_entry):
                continue
            sandbox_path = file_entry.get("sandbox_path")
            if sandbox_path:
                paths.append(str(sandbox_path))
        return paths

    def first_task_path(
        self,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> str | None:
        for file_entry in self.task_files:
            if predicate is not None and not predicate(file_entry):
                continue
            sandbox_path = file_entry.get("sandbox_path")
            if sandbox_path:
                return str(sandbox_path)
        return None

    def find_task_path(
        self,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> str | None:
        return self.first_task_path(predicate=predicate)

    def task_path_for_filename(self, filename: str) -> str | None:
        return self.first_task_path(
            predicate=lambda file_entry: file_entry.get("filename") == filename,
        )

    def common_parent(
        self,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> str | None:
        paths = self.list_task_paths(predicate=predicate)
        if not paths:
            return None
        parents = [str(Path(path).parent) for path in paths]
        try:
            common = os.path.commonpath(parents)
        except ValueError:
            return None
        return common or None

    def log_path(self, stem: str | None = None) -> str:
        name = stem or self.app_spec.app_id
        return f"/tmp/{name}.log"


@dataclass(frozen=True, slots=True)
class AppSpec:
    app_id: str
    verifier_local: Path
    verifier_remote: str
    canonical_launcher: str
    build_launch_command: LaunchBuilder
    ready_check: ReadyCheck = _always_ready
    save_shortcut: str | None = None
    save_window_name: str | None = None
    save_window_hints: dict[str, tuple[str, ...]] = field(default_factory=dict)
    supported_backends: frozenset[str] = frozenset({"docker", "e2b"})
    prepare_task_hooks: tuple[AppHook, ...] = ()
    prepare_profile_hooks: tuple[AppHook, ...] = ()
    post_launch_hooks: tuple[AppHook, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def supports_backend(self, backend: str) -> bool:
        return backend in self.supported_backends
