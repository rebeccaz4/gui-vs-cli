"""
List and clean up E2B sandboxes for the current account.

Examples:
    python -m computer_env.backends.e2b.cleanup_sandboxes
    python -m computer_env.backends.e2b.cleanup_sandboxes --force
    python -m computer_env.backends.e2b.cleanup_sandboxes --state running --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    dotenv = None

if dotenv is not None:
    dotenv.load_dotenv()


def _iter_dotenv_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
        for current in (base, *base.parents):
            candidate = current / ".env"
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)

    return candidates


def _load_dotenv_fallback() -> None:
    for candidate in _iter_dotenv_candidates():
        if not candidate.exists():
            continue

        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            if not key or key in os.environ:
                continue
            if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
                value = value[1:-1]
            os.environ[key] = value
        return


if "E2B_API_KEY" not in os.environ:
    _load_dotenv_fallback()

DEFAULT_PAGE_SIZE = 100
DEFAULT_STATES = ("running", "paused")


class E2BApiError(RuntimeError):
    """Raised when the E2B API returns an unexpected error."""


@dataclass(frozen=True)
class SandboxRecord:
    sandbox_id: str
    state: str
    template_id: str
    alias: str | None
    started_at: str | None
    end_at: str | None
    metadata: dict[str, str]

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "SandboxRecord":
        raw_metadata = payload.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        return cls(
            sandbox_id=str(payload["sandboxID"]),
            state=str(payload["state"]),
            template_id=str(payload["templateID"]),
            alias=str(payload["alias"]) if payload.get("alias") is not None else None,
            started_at=str(payload["startedAt"]) if payload.get("startedAt") else None,
            end_at=str(payload["endAt"]) if payload.get("endAt") else None,
            metadata={str(key): str(value) for key, value in metadata.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "state": self.state,
            "template_id": self.template_id,
            "alias": self.alias,
            "started_at": self.started_at,
            "end_at": self.end_at,
            "metadata": self.metadata,
        }


def _resolve_api_url() -> str:
    explicit_api_url = os.getenv("E2B_API_URL")
    if explicit_api_url:
        return explicit_api_url.rstrip("/")

    domain = os.getenv("E2B_DOMAIN") or "e2b.app"
    debug_mode = os.getenv("E2B_DEBUG", "false").strip().lower() == "true"
    if debug_mode:
        return "http://localhost:3000"
    return f"https://api.{domain}"


def _require_api_key() -> str:
    api_key = os.getenv("E2B_API_KEY")
    if api_key:
        return api_key
    raise RuntimeError(
        "E2B_API_KEY is not set. Export it or place it in a .env file before running this script."
    )


def _request_json(
    *,
    method: str,
    path: str,
    api_key: str,
    query: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[Any, Any]:
    api_url = _resolve_api_url()
    url = f"{api_url}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "gui-synth-env/e2b-cleanup",
            "X-API-KEY": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body) if raw_body else None
            return payload, response.headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = body.strip()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict) and parsed.get("message"):
            message = str(parsed["message"])
        raise E2BApiError(f"{exc.code}: {message or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise E2BApiError(f"Request failed: {exc.reason}") from exc


def list_sandboxes(
    *,
    states: Iterable[str] = DEFAULT_STATES,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[SandboxRecord]:
    api_key = _require_api_key()
    requested_states = tuple(dict.fromkeys(state.strip() for state in states if state.strip()))
    sandboxes: list[SandboxRecord] = []
    next_token: str | None = None

    while True:
        query = {"limit": str(page_size)}
        if requested_states:
            query["state"] = ",".join(requested_states)
        if next_token:
            query["nextToken"] = next_token

        payload, headers = _request_json(
            method="GET",
            path="/v2/sandboxes",
            api_key=api_key,
            query=query,
        )

        items = payload if isinstance(payload, list) else []
        sandboxes.extend(SandboxRecord.from_api_payload(item) for item in items)

        next_token = headers.get("x-next-token")
        if not next_token:
            break

    return sandboxes


def kill_sandbox(sandbox_id: str) -> bool:
    api_key = _require_api_key()
    try:
        _request_json(
            method="DELETE",
            path=f"/sandboxes/{sandbox_id}",
            api_key=api_key,
        )
    except E2BApiError as exc:
        if str(exc).startswith("404:"):
            return False
        raise
    return True


def cleanup_sandboxes(
    *,
    states: Iterable[str] = DEFAULT_STATES,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[SandboxRecord], list[str], list[tuple[str, str]]]:
    sandboxes = list_sandboxes(states=states, page_size=page_size)
    deleted: list[str] = []
    failed: list[tuple[str, str]] = []

    for sandbox in sandboxes:
        try:
            existed = kill_sandbox(sandbox.sandbox_id)
        except Exception as exc:  # pragma: no cover - network/API failures
            failed.append((sandbox.sandbox_id, str(exc)))
            continue
        if existed:
            deleted.append(sandbox.sandbox_id)

    return sandboxes, deleted, failed


def _format_table(sandboxes: list[SandboxRecord]) -> str:
    headers = ("SANDBOX ID", "STATE", "TEMPLATE", "ALIAS", "END AT")
    rows = [
        (
            sandbox.sandbox_id,
            sandbox.state,
            sandbox.template_id,
            sandbox.alias or "-",
            sandbox.end_at or "-",
        )
        for sandbox in sandboxes
    ]

    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    lines = [
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="List or clean up E2B sandboxes")
    parser.add_argument(
        "--state",
        action="append",
        choices=("running", "paused"),
        help="Filter sandbox states. Repeat to include multiple states. Defaults to both running and paused.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"List page size for the E2B API (default: {DEFAULT_PAGE_SIZE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print matching sandboxes as JSON.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually delete the matching sandboxes. Without this flag the script only lists them.",
    )
    args = parser.parse_args()

    states = tuple(args.state or DEFAULT_STATES)

    try:
        sandboxes = list_sandboxes(states=states, page_size=args.page_size)
    except Exception as exc:
        print(f"Failed to list sandboxes: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([sandbox.to_dict() for sandbox in sandboxes], indent=2, ensure_ascii=False))
    elif sandboxes:
        print(_format_table(sandboxes))
    else:
        print("No matching E2B sandboxes found.")

    print(f"\nMatched {len(sandboxes)} sandbox(es) for states: {', '.join(states)}")

    if not args.force:
        print("Dry run only. Re-run with --force to delete them.")
        return 0

    if not sandboxes:
        return 0

    deleted: list[str] = []
    failed: list[tuple[str, str]] = []

    for sandbox in sandboxes:
        try:
            existed = kill_sandbox(sandbox.sandbox_id)
        except Exception as exc:
            failed.append((sandbox.sandbox_id, str(exc)))
            continue
        if existed:
            deleted.append(sandbox.sandbox_id)

    print(f"Deleted {len(deleted)} sandbox(es).")

    if failed:
        print("Failed deletions:", file=sys.stderr)
        for sandbox_id, error in failed:
            print(f"  {sandbox_id}: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
