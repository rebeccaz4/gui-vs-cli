"""Tool registry — loads the bundled safari-mcp tool schema.

The registry is generated offline from safari-mcp's source code by
``scripts/extract_tools.py`` and bundled as ``resources/tools.json``. This
guarantees feature parity with safari-mcp without requiring the CLI to
spawn the MCP server just to learn its tool surface.

Usage:
    from cli_anything.safari.utils.tool_registry import load_registry

    registry = load_registry()
    for tool in registry.tools:
        print(tool.name, tool.description)

    click_tool = registry.get("safari_click")
    for param in click_tool.params:
        print(param.cli_name, param.type, param.required)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ToolParam:
    """A single parameter on an MCP tool, normalized for CLI generation."""

    name: str                # MCP name (camelCase as the server expects)
    cli_name: str            # kebab-case for CLI flag (e.g. "url-pattern")
    type: str                # JSON schema type: string|number|integer|boolean|array|object
    description: str         # from .describe("...") in Zod
    required: bool
    default: Optional[str] = None
    choices: Optional[list[str]] = None

    @classmethod
    def from_json_schema(cls, name: str, schema: dict, required: bool) -> "ToolParam":
        cli_name = _camel_to_kebab(name)
        ptype = schema.get("type", "string")
        if isinstance(ptype, list):
            non_null = [t for t in ptype if t != "null"]
            ptype = non_null[0] if non_null else "string"
        return cls(
            name=name,
            cli_name=cli_name,
            type=ptype,
            description=schema.get("description", ""),
            required=required,
            default=schema.get("default"),
            choices=schema.get("enum"),
        )


@dataclass(frozen=True)
class ToolSchema:
    """A single MCP tool with its full schema."""

    name: str                # e.g. "safari_navigate"
    short_name: str          # without the "safari_" prefix, kebab-case: "navigate"
    description: str
    params: tuple[ToolParam, ...]
    raw_schema: dict

    @classmethod
    def from_dict(cls, data: dict) -> "ToolSchema":
        name = data["name"]
        schema = data.get("inputSchema", {})
        props = schema.get("properties", {}) or {}
        required_set = set(schema.get("required", []) or [])
        params = tuple(
            ToolParam.from_json_schema(pname, pdef, pname in required_set)
            for pname, pdef in props.items()
        )
        short = name
        if short.startswith("safari_"):
            short = short[len("safari_"):]
        short = short.replace("_", "-")
        return cls(
            name=name,
            short_name=short,
            description=data.get("description", ""),
            params=params,
            raw_schema=schema,
        )

    def get_param(self, name: str) -> Optional[ToolParam]:
        """Look up a param by MCP name or CLI name."""
        for p in self.params:
            if p.name == name or p.cli_name == name:
                return p
        return None


@dataclass
class ToolRegistry:
    """The full set of MCP tools from a particular safari-mcp version."""

    source_version: str
    tools: list[ToolSchema] = field(default_factory=list)
    _by_name: dict[str, ToolSchema] = field(default_factory=dict, repr=False)
    _by_short_name: dict[str, ToolSchema] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._by_name = {t.name: t for t in self.tools}
        self._by_short_name = {t.short_name: t for t in self.tools}

    def get(self, name: str) -> Optional[ToolSchema]:
        """Look up a tool by full MCP name (e.g. 'safari_navigate')."""
        return self._by_name.get(name)

    def get_short(self, short_name: str) -> Optional[ToolSchema]:
        """Look up a tool by short name (e.g. 'navigate')."""
        return self._by_short_name.get(short_name)

    def __iter__(self):
        return iter(self.tools)

    def __len__(self):
        return len(self.tools)


def _camel_to_kebab(name: str) -> str:
    """Convert camelCase / snake_case to kebab-case.

    Examples:
        urlPattern     -> url-pattern
        sourceSelector -> source-selector
        max_length     -> max-length
        x              -> x
        URLPattern     -> url-pattern
    """
    import re
    # Handle ALLCAPS runs followed by lowercase (e.g. "URLPattern" -> "URL-Pattern")
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    # Handle camelCase transitions (e.g. "fooBar" -> "foo-Bar")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    # Convert underscores to hyphens and lowercase
    return s.replace("_", "-").lower()


def _resources_path() -> Path:
    return Path(__file__).resolve().parent.parent / "resources" / "tools.json"


@lru_cache(maxsize=1)
def load_registry(path: Optional[Path] = None) -> ToolRegistry:
    """Load the bundled tool registry (cached for the process lifetime).

    Args:
        path: Optional override path to a tools.json file (for tests).

    Returns:
        A populated ToolRegistry.

    Raises:
        FileNotFoundError: If the registry JSON is missing.
        json.JSONDecodeError: If the registry JSON is malformed.
    """
    if path is None:
        path = _resources_path()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tools = [ToolSchema.from_dict(t) for t in data.get("tools", [])]
    return ToolRegistry(
        source_version=data.get("source_version", "unknown"),
        tools=tools,
    )


def clear_cache() -> None:
    """Clear the registry cache — primarily for tests."""
    load_registry.cache_clear()


def coerce_arg_value(param: ToolParam, raw: Any) -> Any:
    """Coerce a raw CLI value into the MCP-expected type.

    Click already handles primitive conversion; this layer handles the
    remaining cases (object/array come in as JSON strings).
    """
    if raw is None:
        return None
    if param.type == "object" or param.type == "array":
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    return raw
