from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules
from typing import Callable

AppBuilder = Callable[..., object]


def _load_app_builders() -> dict[str, AppBuilder]:
    builders: dict[str, AppBuilder] = {}
    for module_info in sorted(iter_modules(__path__), key=lambda item: item.name):
        if module_info.ispkg or module_info.name.startswith("_"):
            continue
        module = import_module(f"{__name__}.{module_info.name}")
        builder_name = f"build_{module_info.name}_spec"
        builder = getattr(module, builder_name, None)
        if builder is None or not callable(builder):
            raise ImportError(
                f"App spec module '{module_info.name}' must define callable '{builder_name}'"
            )
        builders[module_info.name] = builder
    return builders


APP_BUILDERS = _load_app_builders()

__all__ = ["APP_BUILDERS"]
