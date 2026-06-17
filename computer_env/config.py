from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_ENV_BACKEND = os.getenv("ENV_BACKEND", "docker")
DEFAULT_E2B_TEMPLATE = os.getenv("E2B_ENV_TEMPLATE", "desktop-all-apps")
DEFAULT_DOCKER_IMAGE = os.getenv("DOCKER_ENV_IMAGE", "paraverse-agent-runtime:latest")
import platform
_DEFAULT_ARCH = "linux/arm64" if platform.processor() == "arm" or platform.machine() == "arm64" else "linux/amd64"
DEFAULT_DOCKER_PLATFORM = os.getenv("DOCKER_ENV_PLATFORM", "linux/amd64")
DEFAULT_DOCKER_SHM_SIZE = os.getenv("DOCKER_ENV_SHM_SIZE", "2g")
DEFAULT_DOCKER_MEMORY = os.getenv("DOCKER_ENV_MEMORY") or None
DEFAULT_DOCKER_CPUS = os.getenv("DOCKER_ENV_CPUS") or None
DEFAULT_DOCKER_READY_TIMEOUT = int(os.getenv("DOCKER_ENV_READY_TIMEOUT", "90"))


@dataclass(frozen=True)
class EnvCreateOptions:
    backend: str = DEFAULT_ENV_BACKEND
    timeout: int = 3600
    resolution: tuple[int, int] = (1920, 1080)
    template: str = DEFAULT_E2B_TEMPLATE
    docker_image: str = DEFAULT_DOCKER_IMAGE
    docker_platform: str = DEFAULT_DOCKER_PLATFORM
    docker_shm_size: str = DEFAULT_DOCKER_SHM_SIZE
    docker_memory: str | None = DEFAULT_DOCKER_MEMORY
    docker_cpus: str | None = DEFAULT_DOCKER_CPUS
    docker_ready_timeout: int = DEFAULT_DOCKER_READY_TIMEOUT
    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str | None = None
    app_name: str | None = None
    docker_metadata: dict[str, str] | None = None
    e2b_metadata: dict[str, str] | None = None


def normalize_backend(backend: str | None) -> str:
    return (backend or DEFAULT_ENV_BACKEND).strip().lower()
