from __future__ import annotations

from pathlib import Path

from evaluation.runtime.run_config import VERIFIERS_DIR

from .base import AppSpec
from .specs import APP_BUILDERS


def _verifier_paths(app_id: str) -> tuple[Path, str]:
    return VERIFIERS_DIR / app_id / f"{app_id}.py", f"/home/user/verifiers/{app_id}.py"


APP_SPECS = {
    app_id: builder(*_verifier_paths(app_id))
    for app_id, builder in APP_BUILDERS.items()
}


def get_app_spec(app_id: str) -> AppSpec:
    try:
        return APP_SPECS[app_id]
    except KeyError as exc:
        raise ValueError(f"Unknown app: {app_id}") from exc


def list_app_ids() -> list[str]:
    return sorted(APP_SPECS)
