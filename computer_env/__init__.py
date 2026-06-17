"""Environment backends for GUI task execution."""

from .backends.base import (
    BackgroundCommandHandle,
    BaseComputerEnvironment,
    CommandExitException,
    CommandResult,
    CommandsClient,
    FilesClient,
    StreamClient,
)
from .config import (
    DEFAULT_DOCKER_CPUS,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_MEMORY,
    DEFAULT_DOCKER_PLATFORM,
    DEFAULT_DOCKER_SHM_SIZE,
    DEFAULT_DOCKER_READY_TIMEOUT,
    DEFAULT_ENV_BACKEND,
    DEFAULT_E2B_TEMPLATE,
)
from .factory import create_env, ensure_backend_support

__all__ = [
    "BaseComputerEnvironment",
    "CommandsClient",
    "BackgroundCommandHandle",
    "CommandExitException",
    "CommandResult",
    "DEFAULT_DOCKER_CPUS",
    "DEFAULT_DOCKER_IMAGE",
    "DEFAULT_DOCKER_MEMORY",
    "DEFAULT_DOCKER_PLATFORM",
    "DEFAULT_DOCKER_READY_TIMEOUT",
    "DEFAULT_DOCKER_SHM_SIZE",
    "DEFAULT_ENV_BACKEND",
    "DEFAULT_E2B_TEMPLATE",
    "FilesClient",
    "StreamClient",
    "create_env",
    "ensure_backend_support",
]
