from __future__ import annotations

from .backends.base import BaseComputerEnvironment
from .backends.docker.runtime import create_docker_env
from .backends.e2b.runtime import create_e2b_env
from .config import (
    DEFAULT_DOCKER_CPUS,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_MEMORY,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_DOCKER_READY_TIMEOUT,
    DEFAULT_DOCKER_SHM_SIZE,
    DEFAULT_E2B_TEMPLATE,
    EnvCreateOptions,
    normalize_backend,
)


def create_env(
    *,
    backend: str | None = None,
    timeout: int = 3600,
    resolution: tuple[int, int] = (1920, 1080),
    template: str | None = None,
    docker_image: str | None = None,
    docker_platform: str | None = None,
    docker_shm_size: str | None = None,
    docker_memory: str | None = None,
    docker_cpus: str | None = None,
    docker_ready_timeout: int | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
    no_proxy: str | None = None,
    app_name: str | None = None,
    docker_metadata: dict[str, str] | None = None,
    e2b_metadata: dict[str, str] | None = None,
) -> BaseComputerEnvironment:
    options = EnvCreateOptions(
        backend=normalize_backend(backend),
        timeout=timeout,
        resolution=resolution,
        template=template or DEFAULT_E2B_TEMPLATE,
        docker_image=docker_image or DEFAULT_DOCKER_IMAGE,
        docker_platform=docker_platform or DEFAULT_DOCKER_PLATFORM,
        docker_shm_size=docker_shm_size or DEFAULT_DOCKER_SHM_SIZE,
        docker_memory=docker_memory or DEFAULT_DOCKER_MEMORY,
        docker_cpus=docker_cpus or DEFAULT_DOCKER_CPUS,
        docker_ready_timeout=docker_ready_timeout or DEFAULT_DOCKER_READY_TIMEOUT,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
        no_proxy=no_proxy,
        app_name=app_name,
        docker_metadata=docker_metadata,
        e2b_metadata=e2b_metadata,
    )
    ensure_backend_support(options.backend, app_name)
    if options.backend == "e2b":
        return create_e2b_env(options)
    if options.backend == "docker":
        return create_docker_env(options)
    raise ValueError(f"Unknown environment backend: {options.backend}")


def ensure_backend_support(backend: str | None, app_name: str | None) -> None:
    normalized = normalize_backend(backend)
    if normalized not in {"e2b", "docker"}:
        raise ValueError(f"Unknown environment backend: {backend}")
    if not app_name:
        return
    from evaluation.apps.registry import get_app_spec

    app_spec = get_app_spec(app_name)
    if not app_spec.supports_backend(normalized):
        raise ValueError(f"App '{app_name}' does not support backend '{normalized}'")
