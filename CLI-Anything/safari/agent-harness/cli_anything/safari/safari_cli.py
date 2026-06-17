#!/usr/bin/env python3
"""Safari CLI — Command-line interface for Safari browser automation via safari-mcp.

Wraps the `safari-mcp` Node.js MCP server in a Python Click CLI so that any
agent framework (not just MCP clients) can drive Safari on macOS.

**Feature parity with the original MCP is guaranteed** by bundling the tool
schema (generated offline from safari-mcp's source) and building every Click
command dynamically from it. Every tool and every argument safari-mcp exposes
is reachable here with the same name and type.

Usage:
    # One-shot commands (every tool exposed as 'tool <short-name>')
    cli-anything-safari tool navigate --url https://example.com
    cli-anything-safari tool snapshot
    cli-anything-safari tool click --ref 0_5
    cli-anything-safari tool scroll --direction down --amount 500
    cli-anything-safari --json tool read-page

    # Introspection
    cli-anything-safari tools list
    cli-anything-safari tools describe safari_click

    # Interactive REPL
    cli-anything-safari

    # Raw escape hatch for anything the schema-driven path can't express
    cli-anything-safari raw safari_evaluate --json-args '{"script":"document.title"}'
"""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any, Optional

import click

from cli_anything.safari.core.session import Session
from cli_anything.safari.utils import safari_backend as backend
from cli_anything.safari.utils import security as security_mod
from cli_anything.safari.utils.tool_registry import (
    ToolParam,
    ToolSchema,
    coerce_arg_value,
    load_registry,
)

_session: Optional[Session] = None
_json_output = False
_repl_mode = False
_availability_cached: Optional[tuple[bool, str]] = None

# Tools whose `url` argument is a navigation target and must be validated
# through the security layer. Populated by ``_register_all_tools()`` at
# import time from the bundled registry, so new URL-taking tools added
# upstream are picked up automatically.
#
# Frozenset after registration so accidental mutation downstream raises.
_URL_VALIDATED_TOOLS: frozenset[str] = frozenset()


def _compute_url_validated_tools(registry) -> frozenset[str]:
    """Find every tool with a `url` param that takes a navigation target.

    Heuristic: a param whose MCP name is literally ``"url"`` (not
    ``urlPattern`` or similar) and type ``string`` is a navigation
    target. ``mock_route``'s ``urlPattern`` is a regex/substring
    pattern, not a target, and is correctly excluded.
    """
    result: set[str] = set()
    for tool in registry:
        for p in tool.params:
            if p.name == "url" and p.type == "string":
                result.add(tool.name)
                break
    return frozenset(result)


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def output(data, message: str = ""):
    if _json_output:
        click.echo(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    else:
        if message:
            click.echo(message)
        if isinstance(data, dict):
            _print_dict(data)
        elif isinstance(data, list):
            _print_list(data)
        elif data is not None:
            click.echo(str(data))


def _print_dict(d: dict, indent: int = 0):
    prefix = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            click.echo(f"{prefix}{k}:")
            _print_dict(v, indent + 1)
        elif isinstance(v, list):
            click.echo(f"{prefix}{k}:")
            _print_list(v, indent + 1)
        else:
            click.echo(f"{prefix}{k}: {v}")


def _print_list(items: list, indent: int = 0):
    prefix = "  " * indent
    for i, item in enumerate(items):
        if isinstance(item, dict):
            click.echo(f"{prefix}[{i}]")
            _print_dict(item, indent + 1)
        else:
            click.echo(f"{prefix}- {item}")


def _handle_error(e: Exception):
    """Uniform error reporting that respects --json and REPL mode."""
    err_type = type(e).__name__
    if _json_output:
        click.echo(json.dumps({"error": str(e), "type": err_type}))
    else:
        click.echo(f"Error: {e}", err=True)
    if not _repl_mode:
        sys.exit(1)


def handle_error(func):
    """Decorator that funnels exceptions through ``_handle_error``.

    Applied to ``tools``, ``raw``, and ``session`` commands so that any
    uncaught ``RuntimeError``, ``ValueError``, ``OSError``, or
    ``ClickException`` (the base class covering ``UsageError``,
    ``BadParameter``, ``BadOptionUsage``, ``MissingParameter``,
    ``FileError``, ``BadArgumentUsage``) is reported through the
    uniform error path (respects ``--json`` and REPL mode).

    The dynamically-built ``tool`` commands catch their own exceptions
    inline because they need per-parameter JSON-decode handling that a
    generic decorator cannot express.
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (RuntimeError, ValueError, IndexError,
                OSError, json.JSONDecodeError,
                click.exceptions.ClickException) as e:
            _handle_error(e)
    return wrapper


def _validate_url_or_exit(url: str) -> None:
    """Validate a URL and abort the current command if it's unsafe.

    In non-REPL mode this calls ``_handle_error`` which ``sys.exit(1)``s.
    In REPL mode it raises ``click.exceptions.UsageError`` so the REPL
    loop can report the error once and continue. The caller should
    propagate the raise — nothing downstream should run if the URL is
    bad.
    """
    ok, err = security_mod.validate_url(url)
    if ok:
        return
    if _repl_mode:
        raise click.exceptions.UsageError(err)
    _handle_error(click.exceptions.UsageError(err))
    return


# Subcommands that operate on bundled metadata and never touch safari-mcp.
_INTROSPECTION_SUBCOMMANDS = {"tools"}


# ── Main CLI group ─────────────────────────────────────────────────
@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx, use_json):
    """Safari CLI — Browser automation on macOS via safari-mcp.

    Run without a subcommand to enter interactive REPL mode.
    """
    global _json_output, _session, _availability_cached
    _json_output = use_json

    # Click's --help support short-circuits before the group body runs,
    # so we only need to skip the availability probe for commands that
    # work off the bundled registry (tools list|describe|count).
    skip_probe = ctx.invoked_subcommand in _INTROSPECTION_SUBCOMMANDS

    if not skip_probe:
        if _availability_cached is None:
            _availability_cached = backend.is_available()
        available, msg = _availability_cached
        if not available:
            if _json_output:
                click.echo(json.dumps({"error": msg, "type": "dependency_error"}))
            else:
                click.echo(f"Error: {msg}", err=True)
                click.echo(
                    "\nDocs: https://github.com/achiya-automation/safari-mcp"
                )
            sys.exit(1)

    _session = get_session()

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ── Dynamic tool group — registers one Click command per MCP tool ─
@cli.group("tool")
def tool_group():
    """Call any of safari-mcp's 84 tools.

    Every MCP tool is exposed here with its full schema. Use
    ``cli-anything-safari tools list`` to see them, and
    ``cli-anything-safari tools describe <name>`` for full details.
    """


def _click_type_for_param(param: ToolParam):
    """Map a JSON Schema type to a Click ParamType."""
    base = {
        "string":  click.STRING,
        "integer": click.INT,
        "number":  click.FLOAT,
        "boolean": click.BOOL,
    }.get(param.type, click.STRING)
    if param.choices and param.type in ("string", "integer"):
        return click.Choice(param.choices, case_sensitive=False)
    return base


def _build_tool_command(tool: ToolSchema):
    """Build a Click command for a single MCP tool from its schema."""

    def run(**kwargs):
        # Convert kebab-case kwargs back to camelCase MCP names and coerce types.
        # Object/array params arrive as JSON strings and are decoded here;
        # a decode error is reported to the user via _handle_error rather
        # than bubbling up as an ugly traceback.
        args: dict[str, Any] = {}
        for param in tool.params:
            value = kwargs.get(_click_param_name(param.cli_name))
            if value is None:
                # Click's `required=True` covers most types, but boolean
                # flag pairs (--foo/--no-foo) cannot be marked required
                # at the Click level. We enforce here.
                if param.required and param.type == "boolean":
                    _handle_error(
                        click.exceptions.UsageError(
                            f"Missing required boolean flag: "
                            f"--{param.cli_name} or --no-{param.cli_name}"
                        )
                    )
                    return
                continue
            try:
                args[param.name] = coerce_arg_value(param, value)
            except json.JSONDecodeError as e:
                _handle_error(
                    click.exceptions.UsageError(
                        f"Invalid JSON for --{param.cli_name}: {e}"
                    )
                )
                return

        # URL safety for navigation tools. _validate_url_or_exit either
        # exits (non-REPL) or raises UsageError (REPL). Either way we
        # abort here before calling the MCP backend.
        if tool.name in _URL_VALIDATED_TOOLS and args.get("url"):
            _validate_url_or_exit(args["url"])

        try:
            result = backend.call(tool.name, **args)
        except Exception as e:
            _handle_error(e)
            return

        # Track URL for REPL context (only after a successful call).
        if tool.name in _URL_VALIDATED_TOOLS and args.get("url"):
            get_session().set_url(args["url"])

        output(result)

    # Apply Click options, in reverse so decorator order matches param order.
    decorated = run
    for param in reversed(tool.params):
        help_text = param.description or ""
        if param.default is not None:
            help_text = f"{help_text} (default: {param.default})".strip()
        if param.type == "boolean":
            # Required booleans need an explicit default (Click can't enforce
            # `required=True` on a boolean flag pair). For optional booleans
            # we use `default=None` so the arg is omitted from the MCP call
            # when the user doesn't pass --foo or --no-foo.
            bool_default = None
            if param.required:
                # No safe default for a required boolean — force the user
                # to pass --foo or --no-foo. Click doesn't have a "required
                # boolean flag" concept, so we approximate by leaving
                # default=None and validating in the runner below.
                bool_default = None
            decorated = click.option(
                f"--{param.cli_name}/--no-{param.cli_name}",
                default=bool_default,
                help=help_text,
            )(decorated)
        elif param.type in ("object", "array"):
            decorated = click.option(
                f"--{param.cli_name}",
                type=click.STRING,
                required=param.required,
                help=(
                    help_text + f" [JSON {param.type}]"
                    if help_text
                    else f"[JSON {param.type}]"
                ).strip(),
            )(decorated)
        else:
            decorated = click.option(
                f"--{param.cli_name}",
                type=_click_type_for_param(param),
                required=param.required,
                help=help_text,
            )(decorated)

    decorated.__doc__ = tool.description or f"Call {tool.name}."
    cmd = click.command(
        name=tool.short_name,
        help=tool.description or f"Call {tool.name}.",
    )(decorated)
    return cmd


def _click_param_name(cli_name: str) -> str:
    """Click normalizes option names to underscores for the handler kwarg."""
    return cli_name.replace("-", "_")


def _register_all_tools():
    """Load the bundled registry and register every tool as a subcommand.

    Populates ``_URL_VALIDATED_TOOLS`` BEFORE registering any commands so
    no command can be invoked while the validation set is empty.
    """
    global _URL_VALIDATED_TOOLS
    try:
        registry = load_registry()
    except FileNotFoundError:
        click.echo(
            "Warning: bundled tool registry (resources/tools.json) is missing. "
            "Run: python scripts/extract_tools.py <safari-mcp>/index.js "
            "cli_anything/safari/resources/tools.json",
            err=True,
        )
        return

    # Compute the validation set first so any registered command sees it.
    _URL_VALIDATED_TOOLS = _compute_url_validated_tools(registry)
    for tool in registry:
        cmd = _build_tool_command(tool)
        tool_group.add_command(cmd)


_register_all_tools()


# ── tools group — introspection over the bundled registry ────────
@cli.group("tools")
def tools_group():
    """Inspect the bundled safari-mcp tool registry."""


@tools_group.command("list")
@click.option("--filter", "pattern", default="", help="Substring to filter tool names")
@handle_error
def tools_list(pattern):
    """List every safari-mcp tool available to the CLI."""
    registry = load_registry()
    if _json_output:
        data = [
            {
                "name": t.name,
                "short_name": t.short_name,
                "description": t.description,
                "param_count": len(t.params),
            }
            for t in registry
            if pattern.lower() in t.name.lower()
        ]
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    count = 0
    for t in registry:
        if pattern.lower() not in t.name.lower():
            continue
        count += 1
        desc = (t.description or "").split("\n", 1)[0]
        if len(desc) > 80:
            desc = desc[:77] + "..."
        click.echo(f"  {t.short_name:<30} {desc}")
    click.echo()
    click.echo(
        f"{count} tool(s) shown (registry version: {registry.source_version})"
    )


@tools_group.command("describe")
@click.argument("tool_name")
@handle_error
def tools_describe(tool_name):
    """Show the full schema for a single tool."""
    registry = load_registry()
    tool = registry.get(tool_name) or registry.get_short(tool_name)
    if not tool:
        _handle_error(
            click.exceptions.UsageError(
                f"Unknown tool: {tool_name}. "
                f"Use 'tools list' to see available tools."
            )
        )
        return

    if _json_output:
        click.echo(
            json.dumps(
                {
                    "name": tool.name,
                    "short_name": tool.short_name,
                    "description": tool.description,
                    "params": [
                        {
                            "name": p.name,
                            "cli_name": p.cli_name,
                            "type": p.type,
                            "description": p.description,
                            "required": p.required,
                            "default": p.default,
                            "choices": p.choices,
                        }
                        for p in tool.params
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    click.echo(f"Name:        {tool.name}")
    click.echo(f"CLI command: tool {tool.short_name}")
    click.echo(f"Description: {tool.description}")
    if not tool.params:
        click.echo("Parameters:  (none)")
        return
    click.echo("Parameters:")
    for p in tool.params:
        req = "required" if p.required else "optional"
        extra = f" [choices: {p.choices}]" if p.choices else ""
        default = f" [default: {p.default}]" if p.default is not None else ""
        click.echo(f"  --{p.cli_name} ({p.type}, {req}){extra}{default}")
        if p.description:
            click.echo(f"      {p.description}")


@tools_group.command("count")
@handle_error
def tools_count():
    """Print the number of tools in the bundled registry (for scripts)."""
    registry = load_registry()
    if _json_output:
        click.echo(json.dumps({"tool_count": len(registry)}))
    else:
        click.echo(str(len(registry)))


# ── raw command — escape hatch for arbitrary tool calls ──────────
@cli.command()
@click.argument("tool_name")
@click.option(
    "--json-args", default="{}",
    help="JSON string of arguments to pass to the MCP tool",
)
@handle_error
def raw(tool_name, json_args):
    """Call any safari-mcp tool directly by name.

    This bypasses the schema-driven 'tool' group — useful when you have
    a pre-built JSON args blob or when testing new tools.

    Example:
        cli-anything-safari raw safari_evaluate \\
            --json-args '{"script":"document.title"}'
    """
    try:
        args = json.loads(json_args)
    except json.JSONDecodeError as e:
        _handle_error(
            click.exceptions.UsageError(f"Invalid JSON for --json-args: {e}")
        )
        return

    if not isinstance(args, dict):
        _handle_error(
            click.exceptions.UsageError(
                "--json-args must decode to a JSON object, "
                f"got {type(args).__name__}"
            )
        )
        return

    # Even via raw, still run URL validation for navigation tools
    if tool_name in _URL_VALIDATED_TOOLS and args.get("url"):
        _validate_url_or_exit(args["url"])

    try:
        result = backend.call(tool_name, **args)
    except Exception as e:
        _handle_error(e)
        return
    output(result)


# ── session command ───────────────────────────────────────────────
@cli.group()
def session():
    """Session state (last URL, current tab)."""


@session.command("status")
@handle_error
def session_status():
    """Show current session state."""
    output(get_session().status())


# ── REPL ──────────────────────────────────────────────────────────
@cli.command()
def repl():
    """Start interactive REPL session."""
    from cli_anything.safari.utils.repl_skin import ReplSkin

    global _repl_mode
    _repl_mode = True

    skin = ReplSkin("safari", version="1.0.0")
    skin.print_banner()

    pt_session = skin.create_prompt_session()

    repl_commands = {
        "tool <name>":  "Call any safari-mcp tool (use 'tools list' for names)",
        "tools list":   "List all available tools",
        "tools describe <name>": "Show full schema for a tool",
        "raw <name>":   "Call a tool via JSON args",
        "session status": "Show current session state",
        "help":         "Show this help",
        "quit":         "Exit REPL",
    }

    while True:
        try:
            sess = get_session()
            context = ""
            if sess.last_url:
                url_display = (
                    sess.last_url[:40] + "..."
                    if len(sess.last_url) > 40
                    else sess.last_url
                )
                context = url_display
                if sess.current_tab_index is not None:
                    context = f"tab{sess.current_tab_index} {url_display}"

            line = skin.get_input(pt_session, context=context)
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                skin.print_goodbye()
                break
            if line.lower() == "help":
                skin.help(repl_commands)
                continue

            try:
                args = shlex.split(line)
            except ValueError:
                args = line.split()

            try:
                cli.main(args, standalone_mode=False)
            except SystemExit:
                pass
            except click.exceptions.UsageError as e:
                skin.warning(f"Usage error: {e}")
            except Exception as e:
                skin.error(f"{e}")

        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break

    _repl_mode = False


# ── Entry point ───────────────────────────────────────────────────
def main():
    cli()


if __name__ == "__main__":
    main()
