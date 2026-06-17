from __future__ import annotations

import atexit
import os
import shlex
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from computer_env.backends.base import (
    BackgroundCommandHandle,
    BaseComputerEnvironment,
    CommandExitException,
    CommandResult,
)
from computer_env.config import EnvCreateOptions

DOCKER_NOVNC_PORT = 6080
DOCKER_VNC_PORT = 5900
DOCKER_DBUS_ADDRESS = "unix:path=/tmp/runtime-user/bus"
MANAGED_CONTAINER_LABEL = "gui-synth-env.managed"
BACKEND_LABEL = "gui-synth-env.backend"
APP_LABEL = "gui-synth-env.app"
SESSION_LABEL = "gui-synth-env.session"
DOCKER_METADATA_LABEL_PREFIX = "gui-synth-env.meta."
PROCESS_SESSION_ID = f"{os.getpid()}-{uuid.uuid4().hex}"
DOCKER_TMPFS_MOUNTS = (
    "/tmp:rw,exec,nosuid,size=2g",
)
DOCKER_SCREENSHOT_ATTEMPTS = 3
DOCKER_SCREENSHOT_RETRY_DELAY_SECONDS = 1.0
_ACTIVE_CONTAINER_IDS: set[str] = set()
_ACTIVE_CONTAINER_IDS_LOCK = threading.Lock()


def _register_active_container(container_id: str) -> None:
    with _ACTIVE_CONTAINER_IDS_LOCK:
        _ACTIVE_CONTAINER_IDS.add(container_id)


def _unregister_active_container(container_id: str) -> None:
    with _ACTIVE_CONTAINER_IDS_LOCK:
        _ACTIVE_CONTAINER_IDS.discard(container_id)


def _container_exists(container_id: str) -> bool:
    result = _run_subprocess(
        ["docker", "ps", "-aq", "--filter", f"id={container_id}"],
        timeout=10,
    )
    return bool(result.stdout.strip())


def _remove_container_if_present(container_id: str) -> bool:
    try:
        _run_subprocess(["docker", "rm", "-f", container_id], timeout=20)
    except Exception:
        if _container_exists(container_id):
            return False
    _unregister_active_container(container_id)
    return True


def cleanup_active_docker_containers() -> list[str]:
    with _ACTIVE_CONTAINER_IDS_LOCK:
        container_ids = set(_ACTIVE_CONTAINER_IDS)

    try:
        result = _run_subprocess(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label={SESSION_LABEL}={PROCESS_SESSION_ID}",
            ],
            timeout=20,
        )
    except Exception:
        result = None
    else:
        container_ids.update(line.strip() for line in result.stdout.splitlines() if line.strip())

    cleaned: list[str] = []
    for container_id in sorted(container_ids):
        if _remove_container_if_present(container_id):
            cleaned.append(container_id)
    return cleaned


def cleanup_docker_containers_by_metadata(metadata: dict[str, str] | None) -> list[str]:
    if not metadata:
        return []

    argv = [
        "docker",
        "ps",
        "-aq",
        "--filter",
        f"label={MANAGED_CONTAINER_LABEL}=true",
        "--filter",
        f"label={BACKEND_LABEL}=docker",
    ]
    for key, value in metadata.items():
        argv.extend(["--filter", f"label={DOCKER_METADATA_LABEL_PREFIX}{key}={value}"])

    result = _run_subprocess(argv, timeout=20)
    container_ids = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())

    cleaned: list[str] = []
    for container_id in container_ids:
        if _remove_container_if_present(container_id):
            cleaned.append(container_id)
    return cleaned


atexit.register(cleanup_active_docker_containers)


def _run_subprocess(argv: list[str], timeout: int | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    # Match E2B semantics: timeout=0 means "no timeout", not "immediately fail".
    effective_timeout = None if timeout == 0 else timeout
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Docker CLI was not found. Install Docker Desktop / Docker Engine and ensure "
            "`docker` is on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Command timed out after {timeout}s: {' '.join(argv)}") from exc

    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Docker command failed")
    return result


def _run_subprocess_bytes(
    argv: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    effective_timeout = None if timeout == 0 else timeout
    try:
        result = subprocess.run(
            argv,
            input=input_bytes,
            capture_output=True,
            timeout=effective_timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Docker CLI was not found. Install Docker Desktop / Docker Engine and ensure "
            "`docker` is on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Command timed out after {timeout}s: {' '.join(argv)}") from exc

    if check and result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        stdout = result.stdout.decode(errors="replace").strip()
        raise RuntimeError(stderr or stdout or "Docker command failed")
    return result


def _parse_port_mapping(raw: str) -> int:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Docker did not expose a noVNC port")

    preferred = next((line for line in lines if line.startswith("127.0.0.1:")), lines[0])
    host_port = preferred.rsplit(":", 1)[-1]
    return int(host_port)


def _build_container_labels(options: EnvCreateOptions) -> dict[str, str]:
    labels = {
        MANAGED_CONTAINER_LABEL: "true",
        BACKEND_LABEL: "docker",
        APP_LABEL: options.app_name or "none",
        SESSION_LABEL: PROCESS_SESSION_ID,
    }
    for key, value in (options.docker_metadata or {}).items():
        labels[f"{DOCKER_METADATA_LABEL_PREFIX}{key}"] = value
    return labels


def _build_docker_run_argv(
    *,
    options: EnvCreateOptions,
    container_name: str,
) -> list[str]:
    width, height = options.resolution
    argv = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
        "--platform",
        options.docker_platform,
        "--shm-size",
        options.docker_shm_size,
        # GLib/GIO desktop launching paths use close_range() on this Ubuntu base.
        # Docker's default seccomp profile blocks that syscall with EPERM, which
        # breaks xfce4-session child startup and clicking .desktop launchers from
        # the desktop/menu ("Failed to close file descriptor for child process").
        "--security-opt",
        "seccomp=unconfined",
        "--entrypoint",
        "/usr/local/bin/gui-synth-entrypoint.sh",
        "-p",
        f"127.0.0.1::{DOCKER_NOVNC_PORT}",
        "-p",
        "127.0.0.1::5900",
    ]
    for mount in DOCKER_TMPFS_MOUNTS:
        argv.extend(["--tmpfs", mount])
    for key, value in _build_container_labels(options).items():
        argv.extend(["--label", f"{key}={value}"])
    if options.docker_memory:
        argv.extend(["--memory", options.docker_memory])
    if options.docker_cpus:
        argv.extend(["--cpus", options.docker_cpus])
    argv.extend(
        [
            "-e",
            f"SCREEN_WIDTH={width}",
            "-e",
            f"SCREEN_HEIGHT={height}",
            # Removed ENV_TIMEOUT_SECONDS to avoid conflicts with docker exec timeout
# The docker exec timeout is sufficient for enforcing time limits
            "-e",
            "HTTP_PROXY=http://host.docker.internal:7897",
            "-e",
            "HTTPS_PROXY=http://host.docker.internal:7897",
            "-e",
            "NO_PROXY=localhost,127.0.0.1",
            options.docker_image,
        ]
    )
    return argv


def _tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


def _collect_container_debug(container_ref: str) -> str:
    sections = []
    for name, argv in (
        ("inspect", ["docker", "inspect", container_ref]),
        ("logs", ["docker", "logs", container_ref]),
    ):
        try:
            result = _run_subprocess(argv, timeout=10)
        except Exception as exc:  # pragma: no cover - best effort diagnostics
            sections.append(f"[{name}] unavailable: {exc}")
            continue
        payload = ((result.stdout or "") + (result.stderr or "")).strip()
        if payload:
            sections.append(f"[{name}]\n{_tail(payload)}")
        else:
            sections.append(f"[{name}] empty")
    return "\n\n".join(sections)


class DockerCommandsClient:
    def __init__(self, env: "DockerEnvironment") -> None:
        self._env = env

    def run(self, command: str, timeout: int | None = None, background: bool = False):
        exec_argv = ["docker", "exec"]
        if background:
            exec_argv.append("-d")
        exec_argv.extend(
            [
                self._env.container_id,
                "bash",
                "-lc",
                self._env._with_desktop_env(command),
            ]
        )
        result = _run_subprocess(exec_argv, timeout=timeout)
        if result.returncode != 0:
            raise CommandExitException(
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        if background:
            return BackgroundCommandHandle(command=command, backend="docker")

        return CommandResult(
            command=command,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.returncode,
        )


class DockerFilesClient:
    def __init__(self, env: "DockerEnvironment") -> None:
        self._env = env

    def write(self, path: str, data) -> None:
        payload = data.encode() if isinstance(data, str) else data
        parent = str(Path(path).parent)
        self._env._exec_as_root(f"mkdir -p {shlex.quote(parent)}", timeout=10)
        write_result = _run_subprocess_bytes(
            [
                "docker",
                "exec",
                "-i",
                "--user",
                "root",
                self._env.container_id,
                "bash",
                "-lc",
                f"cat > {shlex.quote(path)}",
            ],
            input_bytes=payload,
            timeout=30,
        )
        if write_result.returncode != 0:
            raise RuntimeError(
                write_result.stderr.decode(errors="replace").strip()
                or write_result.stdout.decode(errors="replace").strip()
                or "Failed to write file via docker exec"
            )
        self._env._exec_as_root(
            f"chown user:user {shlex.quote(path)} 2>/dev/null || true",
            timeout=10,
        )

    def read(self, path: str, format: str = "text"):
        result = _run_subprocess_bytes(
            [
                "docker",
                "exec",
                self._env.container_id,
                "bash",
                "-lc",
                self._env._with_desktop_env(f"cat {shlex.quote(path)}"),
            ],
            timeout=30,
        )
        if result.returncode != 0:
            raise FileNotFoundError(path)
        data = result.stdout
        if format in {"bytes", "binary"}:
            return data
        return data.decode()

    def remove(self, path: str) -> None:
        self._env._exec_as_root(f"rm -f {shlex.quote(path)}", timeout=10)


class DockerStreamClient:
    def __init__(self, env: "DockerEnvironment") -> None:
        self._env = env

    def start(self, **kwargs):
        self._env.wait_ready()

    def get_url(self, resize: str | None = None, view_only: bool = False, auth_key: str | None = None):
        params = {"autoconnect": "true"}
        if resize:
            params["resize"] = resize
        if view_only:
            params["view_only"] = "true"
        if auth_key:
            params["password"] = auth_key
        query = urlencode(params)
        return f"http://127.0.0.1:{self._env.stream_port}/vnc.html?{query}"

    def stop(self):
        return None


class DockerEnvironment(BaseComputerEnvironment):
    backend_name = "docker"

    def __init__(
        self,
        *,
        container_id: str,
        container_name: str,
        stream_port: int,
        timeout: int,
        resolution: tuple[int, int],
        ready_timeout: int,
    ) -> None:
        self.container_id = container_id
        self.container_name = container_name
        self.stream_port = stream_port
        self.timeout = timeout
        self.resolution = resolution
        self.ready_timeout = ready_timeout
        self.commands = DockerCommandsClient(self)
        self.files = DockerFilesClient(self)
        self.stream = DockerStreamClient(self)
        self._killed = False

    @classmethod
    def create(cls, options: EnvCreateOptions) -> "DockerEnvironment":
        image_inspect = _run_subprocess(["docker", "image", "inspect", options.docker_image], timeout=30)
        if image_inspect.returncode != 0:
            inspect_error = (image_inspect.stderr or image_inspect.stdout).strip()
            raise RuntimeError(
                f"Unable to inspect Docker image '{options.docker_image}'. "
                f"Docker returned: {inspect_error or f'exit code {image_inspect.returncode}'}. "
                "If the image is missing, build it with: "
                f"bash computer_env/provision/docker/build_image.sh {options.docker_image}"
            )
        image_arch_result = _run_subprocess(
            ["docker", "image", "inspect", options.docker_image, "--format", "{{.Architecture}}"],
            timeout=30,
        )
        image_arch = image_arch_result.stdout.strip()
        expected_arch = options.docker_platform.split("/")[-1]
        if image_arch and expected_arch and image_arch != expected_arch:
            raise RuntimeError(
                f"Docker image '{options.docker_image}' has architecture '{image_arch}', "
                f"but the backend is configured for '{options.docker_platform}'. "
                "Rebuild it with: "
                f"bash computer_env/provision/docker/build_image.sh {options.docker_image}"
            )

        container_name = f"gui-synth-env-{uuid.uuid4().hex[:12]}"
        run_argv = _build_docker_run_argv(
            options=options,
            container_name=container_name,
        )
        run_result = _run_subprocess(run_argv, timeout=60)
        if run_result.returncode != 0:
            raise RuntimeError(run_result.stderr.strip() or run_result.stdout.strip())

        container_id = run_result.stdout.strip()
        _register_active_container(container_id)
        try:
            port_result = _run_subprocess(
                ["docker", "port", container_id, f"{DOCKER_NOVNC_PORT}/tcp"],
                timeout=15,
            )
            if port_result.returncode != 0:
                debug_info = _collect_container_debug(container_id)
                raise RuntimeError(
                    "Docker desktop container did not expose the noVNC port.\n"
                    f"{port_result.stderr.strip() or port_result.stdout.strip()}\n\n"
                    f"{debug_info}"
                )
            stream_port = _parse_port_mapping(port_result.stdout)
            env = cls(
                container_id=container_id,
                container_name=container_name,
                stream_port=stream_port,
                timeout=options.timeout,
                resolution=options.resolution,
                ready_timeout=options.docker_ready_timeout,
            )
            env.wait_ready()
            return env
        except BaseException:
            try:
                _run_subprocess(["docker", "rm", "-f", container_id], timeout=20)
            except Exception:
                pass
            finally:
                _unregister_active_container(container_id)
            raise

    def _exec_as_root(self, command: str, timeout: int | None = None) -> CommandResult:
        exec_argv = [
            "docker",
            "exec",
            "--user",
            "root",
            self.container_id,
            "bash",
            "-lc",
            self._with_desktop_env(command),
        ]
        result = _run_subprocess(exec_argv, timeout=timeout)
        if result.returncode != 0:
            raise CommandExitException(
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return CommandResult(command=command, stdout=result.stdout or "", stderr=result.stderr or "")

    def wait_ready(self) -> None:
        deadline = time.time() + self.ready_timeout
        last_error = "desktop not ready"
        while time.time() < deadline:
            ps_result = _run_subprocess(["docker", "ps", "-q", "-f", f"id={self.container_id}"], timeout=10)
            if not ps_result.stdout.strip():
                debug_info = _collect_container_debug(self.container_id)
                raise RuntimeError(
                    f"Docker desktop container exited before becoming ready.\n"
                    f"{debug_info}"
                )

            try:
                check = _run_subprocess(
                    [
                        "docker",
                        "exec",
                        self.container_id,
                        "bash",
                        "-lc",
                        self._with_desktop_env(
                            "DISPLAY=:0 xset q >/dev/null 2>&1 && "
                            "pgrep -f x11vnc >/dev/null 2>&1 && "
                            "pgrep -f websockify >/dev/null 2>&1",
                        ),
                    ],
                    timeout=10,
                )
            except TimeoutError:
                last_error = "ready check docker exec timed out"
                time.sleep(1)
                continue
            if check.returncode == 0:
                try:
                    with socket.create_connection(("127.0.0.1", self.stream_port), timeout=1):
                        return
                except OSError as exc:
                    last_error = str(exc)
            else:
                last_error = (check.stderr or check.stdout or last_error).strip()

            time.sleep(1)

        debug_info = _collect_container_debug(self.container_id)
        raise RuntimeError(
            "Docker desktop environment did not become ready.\n"
            f"reason: {last_error}\n\n{debug_info}"
        )

    def screenshot(self):
        last_error = None

        for attempt in range(1, DOCKER_SCREENSHOT_ATTEMPTS + 1):
            screenshot_path = f"/tmp/gui_synth_env_screenshot_{uuid.uuid4().hex}.png"
            try:
                self.commands.run(
                    f"DISPLAY=:0 scrot --pointer {shlex.quote(screenshot_path)}",
                    timeout=20,
                )
                data = self.files.read(screenshot_path, format="bytes")
                self.commands.run(f"rm -f {shlex.quote(screenshot_path)}", timeout=10)
                return data
            except Exception as exc:
                last_error = exc
                try:
                    self.commands.run(f"rm -f {shlex.quote(screenshot_path)}", timeout=10)
                except Exception:
                    pass
                if attempt < DOCKER_SCREENSHOT_ATTEMPTS:
                    time.sleep(DOCKER_SCREENSHOT_RETRY_DELAY_SECONDS)

        raise RuntimeError(
            "Docker screenshot failed after "
            f"{DOCKER_SCREENSHOT_ATTEMPTS} attempts: {last_error}"
        )

    def kill(self) -> None:
        if self._killed:
            return
        self._killed = True
        try:
            _run_subprocess(["docker", "rm", "-f", self.container_id], timeout=20)
        finally:
            _unregister_active_container(self.container_id)

    @staticmethod
    def _with_desktop_env(command: str) -> str:
        return (
            f"export DBUS_SESSION_BUS_ADDRESS=${{DBUS_SESSION_BUS_ADDRESS:-{shlex.quote(DOCKER_DBUS_ADDRESS)}}}; "
            f"{command}"
        )


def create_docker_env(options: EnvCreateOptions) -> DockerEnvironment:
    return DockerEnvironment.create(options)
