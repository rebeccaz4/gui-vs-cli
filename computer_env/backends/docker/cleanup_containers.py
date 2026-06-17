"""
List and clean up Docker containers managed by gui-synth-env.

Examples:
    python -m computer_env.backends.docker.cleanup_containers
    python -m computer_env.backends.docker.cleanup_containers --force
    python -m computer_env.backends.docker.cleanup_containers --state running --json
    python -m computer_env.backends.docker.cleanup_containers --metadata run_id=kimi-k2.5_20260425_223506 --force
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Iterable

from .runtime import APP_LABEL, BACKEND_LABEL, DOCKER_METADATA_LABEL_PREFIX, MANAGED_CONTAINER_LABEL

DEFAULT_STATES = ("created", "running", "paused", "restarting", "exited", "dead")
VALID_STATES = ("created", "running", "paused", "restarting", "exited", "dead", "removing")


class DockerCliError(RuntimeError):
    """Raised when the Docker CLI returns an unexpected error."""


@dataclass(frozen=True)
class ContainerRecord:
    container_id: str
    name: str
    image: str
    state: str
    status: str
    created_at: str | None
    labels: dict[str, str]

    @classmethod
    def from_inspect_payload(cls, payload: dict[str, Any]) -> "ContainerRecord":
        config = payload.get("Config")
        config = config if isinstance(config, dict) else {}
        state = payload.get("State")
        state = state if isinstance(state, dict) else {}
        labels = config.get("Labels")
        labels = labels if isinstance(labels, dict) else {}
        name = str(payload.get("Name") or "").lstrip("/")

        return cls(
            container_id=str(payload.get("Id") or ""),
            name=name,
            image=str(config.get("Image") or ""),
            state=str(state.get("Status") or ""),
            status=str(state.get("Status") or ""),
            created_at=str(payload.get("Created") or "") or None,
            labels={str(key): str(value) for key, value in labels.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "container_id": self.container_id,
            "name": self.name,
            "image": self.image,
            "state": self.state,
            "status": self.status,
            "created_at": self.created_at,
            "labels": self.labels,
        }


def _run_subprocess(argv: list[str], *, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Docker CLI was not found. Install Docker Desktop / Docker Engine and ensure "
            "`docker` is on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerCliError(f"Command timed out after {timeout}s: {' '.join(argv)}") from exc

    if check and result.returncode != 0:
        raise DockerCliError(result.stderr.strip() or result.stdout.strip() or "Docker command failed")

    return result


def _list_candidate_container_ids(
    *,
    states: Iterable[str],
    metadata: dict[str, str] | None = None,
    app: str | None = None,
) -> list[str]:
    argv = [
        "docker",
        "ps",
        "-aq",
        "--filter",
        f"label={MANAGED_CONTAINER_LABEL}=true",
        "--filter",
        f"label={BACKEND_LABEL}=docker",
    ]
    for state in dict.fromkeys(state.strip() for state in states if state.strip()):
        argv.extend(["--filter", f"status={state}"])
    for key, value in (metadata or {}).items():
        argv.extend(["--filter", f"label={DOCKER_METADATA_LABEL_PREFIX}{key}={value}"])
    if app:
        argv.extend(["--filter", f"label={APP_LABEL}={app}"])

    result = _run_subprocess(argv, check=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def list_containers(
    *,
    states: Iterable[str] = DEFAULT_STATES,
    metadata: dict[str, str] | None = None,
    app: str | None = None,
) -> list[ContainerRecord]:
    container_ids = _list_candidate_container_ids(states=states, metadata=metadata, app=app)
    if not container_ids:
        return []

    result = _run_subprocess(["docker", "inspect", *container_ids], check=True)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DockerCliError("Failed to parse `docker inspect` output") from exc

    if not isinstance(payload, list):
        raise DockerCliError("Unexpected `docker inspect` output")

    return [ContainerRecord.from_inspect_payload(item) for item in payload if isinstance(item, dict)]


def remove_container(container_id: str) -> bool:
    result = _run_subprocess(["docker", "rm", "-f", container_id], check=False)
    if result.returncode == 0:
        return True
    message = (result.stderr or result.stdout).strip().lower()
    if "no such container" in message:
        return False
    raise DockerCliError(result.stderr.strip() or result.stdout.strip() or "Docker command failed")


def cleanup_containers(
    *,
    states: Iterable[str] = DEFAULT_STATES,
    metadata: dict[str, str] | None = None,
    app: str | None = None,
) -> tuple[list[ContainerRecord], list[str], list[tuple[str, str]]]:
    containers = list_containers(states=states, metadata=metadata, app=app)
    deleted: list[str] = []
    failed: list[tuple[str, str]] = []

    for container in containers:
        try:
            existed = remove_container(container.container_id)
        except Exception as exc:
            failed.append((container.container_id, str(exc)))
            continue
        if existed:
            deleted.append(container.container_id)

    return containers, deleted, failed


def _format_table(containers: list[ContainerRecord]) -> str:
    headers = ("CONTAINER ID", "STATE", "NAME", "APP", "RUN ID", "IMAGE")
    rows = [
        (
            container.container_id[:12],
            container.state or "-",
            container.name or "-",
            container.labels.get(APP_LABEL, "-"),
            container.labels.get(f"{DOCKER_METADATA_LABEL_PREFIX}run_id", "-"),
            container.image or "-",
        )
        for container in containers
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
    parser = argparse.ArgumentParser(description="List or clean up gui-synth-env Docker containers")
    parser.add_argument(
        "--state",
        action="append",
        choices=VALID_STATES,
        help="Filter container states. Repeat to include multiple states. Defaults to common active and exited states.",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Filter by Docker metadata label. Repeat to include multiple exact-match metadata filters.",
    )
    parser.add_argument("--app", type=str, help="Filter by gui-synth-env app label")
    parser.add_argument("--json", action="store_true", help="Print matching containers as JSON.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually delete the matching containers. Without this flag the script only lists them.",
    )
    args = parser.parse_args()

    states = tuple(args.state or DEFAULT_STATES)
    metadata: dict[str, str] = {}
    for item in args.metadata:
        if "=" not in item:
            raise SystemExit(f"Invalid --metadata value: {item!r}. Expected KEY=VALUE.")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit(f"Invalid --metadata value: {item!r}. Metadata key cannot be empty.")
        metadata[key] = value

    try:
        containers = list_containers(states=states, metadata=metadata, app=args.app)
    except Exception as exc:
        print(f"Failed to list containers: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([container.to_dict() for container in containers], indent=2, ensure_ascii=False))
    elif containers:
        print(_format_table(containers))
    else:
        print("No matching Docker containers found.")

    filters = [f"states={','.join(states)}"]
    if metadata:
        filters.extend(f"{key}={value}" for key, value in metadata.items())
    if args.app:
        filters.append(f"app={args.app}")
    print(f"\nMatched {len(containers)} container(s) for filters: {', '.join(filters)}")

    if not args.force:
        print("Dry run only. Re-run with --force to delete them.")
        return 0

    if not containers:
        return 0

    deleted: list[str] = []
    failed: list[tuple[str, str]] = []

    for container in containers:
        try:
            existed = remove_container(container.container_id)
        except Exception as exc:
            failed.append((container.container_id, str(exc)))
            continue
        if existed:
            deleted.append(container.container_id)

    print(f"Deleted {len(deleted)} container(s).")

    if failed:
        print("Failed deletions:", file=sys.stderr)
        for container_id, error in failed:
            print(f"  {container_id}: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
