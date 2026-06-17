#!/usr/bin/env python3
"""Obsidian CLI — Knowledge management and note-taking via Obsidian Local REST API.

This CLI provides full access to the Obsidian REST API for managing notes,
searching the vault, and executing Obsidian commands.

Usage:
    # One-shot commands
    cli-anything-obsidian --api-key YOUR_KEY vault list
    cli-anything-obsidian --api-key YOUR_KEY vault read "My Note.md"
    cli-anything-obsidian --api-key YOUR_KEY --json search query "tag:#project"

    # Interactive REPL
    cli-anything-obsidian --api-key YOUR_KEY
"""

import sys
import os
import json
import shlex
import click
from cli_anything.obsidian.utils.obsidian_backend import DEFAULT_BASE_URL
from cli_anything.obsidian.core import vault as vault_mod
from cli_anything.obsidian.core import search as search_mod
from cli_anything.obsidian.core import note as note_mod
from cli_anything.obsidian.core import command as cmd_mod
from cli_anything.obsidian.core import server as server_mod
from cli_anything.obsidian.core import local_artifacts as local_mod

# Global state
_json_output = False
_repl_mode = False
_host = DEFAULT_BASE_URL
_api_key = ""
_last_path: str = ""


def output(data, message: str = ""):
    if _json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if message:
            click.echo(message)
        if isinstance(data, dict):
            _print_dict(data)
        elif isinstance(data, list):
            _print_list(data)
        else:
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


def handle_error(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": "runtime_error"}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
        except (ValueError, IndexError) as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
        except Exception as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _require_api_key():
    """Check that API key is set, raise error if not."""
    if not _api_key:
        raise RuntimeError("API key required. Use --api-key or set OBSIDIAN_API_KEY env var.")


# ── Main CLI Group ──────────────────────────────────────────────
@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.option("--host", type=str, default=None,
              help=f"Obsidian REST API URL (default: {DEFAULT_BASE_URL})")
@click.option("--api-key", type=str, default=None,
              help="API key for authentication (or set OBSIDIAN_API_KEY env var)")
@click.pass_context
def cli(ctx, use_json, host, api_key):
    """Obsidian CLI — Knowledge management and note-taking.

    Run without a subcommand to enter interactive REPL mode.
    """
    global _json_output, _host, _api_key
    _json_output = use_json
    _host = host if host else DEFAULT_BASE_URL
    _api_key = api_key or os.environ.get("OBSIDIAN_API_KEY", "")

    if ctx.invoked_subcommand is None:
        _require_api_key()
        ctx.invoke(repl)


# ── Vault Commands ──────────────────────────────────────────────
@cli.group()
def vault():
    """Vault file operations."""
    pass


@vault.command("list")
@click.argument("path", default="/")
@handle_error
def vault_list(path):
    """List files and folders in the vault."""
    _require_api_key()
    result = vault_mod.list_files(_host, _api_key, path)
    files = result.get("files", [])
    if _json_output:
        output(result)
    else:
        if not files:
            click.echo("No files found.")
            return
        click.echo(f"{'FILE':<60}")
        click.echo("─" * 60)
        for f in files:
            click.echo(f"{f}")


@vault.command("read")
@click.argument("path")
@handle_error
def vault_read(path):
    """Read a note's content."""
    _require_api_key()
    global _last_path
    _last_path = path
    result = vault_mod.read_note(_host, _api_key, path)
    if _json_output:
        output(result)
    else:
        click.echo(result.get("content", ""))


@vault.command("create")
@click.argument("path")
@click.option("--content", "-c", default="", help="Note content (markdown)")
@click.option("--file", "-f", "input_file", type=click.Path(exists=True),
              help="Read content from file")
@handle_error
def vault_create(path, content, input_file):
    """Create a new note in the vault."""
    _require_api_key()
    if input_file:
        with open(input_file, "r", encoding="utf-8") as fh:
            content = fh.read()
    result = vault_mod.create_note(_host, _api_key, path, content)
    output(result, f"Created: {path}")


@vault.command("update")
@click.argument("path")
@click.option("--content", "-c", default="", help="New note content (markdown)")
@click.option("--file", "-f", "input_file", type=click.Path(exists=True),
              help="Read content from file")
@handle_error
def vault_update(path, content, input_file):
    """Update an existing note (overwrites content)."""
    _require_api_key()
    if input_file:
        with open(input_file, "r", encoding="utf-8") as fh:
            content = fh.read()
    result = vault_mod.update_note(_host, _api_key, path, content)
    output(result, f"Updated: {path}")


@vault.command("delete")
@click.argument("path")
@handle_error
def vault_delete(path):
    """Delete a note from the vault."""
    _require_api_key()
    result = vault_mod.delete_note(_host, _api_key, path)
    output(result, f"Deleted: {path}")


@vault.command("append")
@click.argument("path")
@click.option("--content", "-c", required=True, help="Content to append")
@click.option("--position", "-p", type=click.Choice(["end", "beginning"]),
              default="end", help="Insert position (default: end)")
@handle_error
def vault_append(path, content, position):
    """Append or prepend content to a note."""
    _require_api_key()
    result = vault_mod.append_note(_host, _api_key, path, content, position=position)
    output(result, f"{'Appended to' if position == 'end' else 'Prepended to'}: {path}")


# ── Local Artifact Commands ─────────────────────────────────────
@cli.group()
def local():
    """Local vault file and config commands."""
    pass


@local.command("init")
@click.argument("vault_path")
@handle_error
def local_init(vault_path):
    """Create a local vault and .obsidian directory."""
    output(local_mod.init_vault(vault_path), "Vault initialized.")


@local.command("write-note")
@click.argument("vault_path")
@click.argument("note_path")
@click.option("--content", "-c", default="", help="Markdown content.")
@click.option("--file", "-f", "input_file", type=click.Path(exists=True),
              help="Read Markdown content from file.")
@handle_error
def local_write_note(vault_path, note_path, content, input_file):
    """Create or replace a local note."""
    output(local_mod.write_note(vault_path, note_path, content, input_file), f"Note written: {note_path}")


@local.command("append-note")
@click.argument("vault_path")
@click.argument("note_path")
@click.option("--content", "-c", required=True, help="Markdown content to insert.")
@click.option("--position", "-p", type=click.Choice(["end", "beginning"]),
              default="end", help="Insert position.")
@handle_error
def local_append_note(vault_path, note_path, content, position):
    """Append or prepend content to a local note."""
    output(local_mod.append_note(vault_path, note_path, content, position), f"Note updated: {note_path}")


@local.command("mkdir")
@click.argument("vault_path")
@click.argument("folder")
@handle_error
def local_mkdir(vault_path, folder):
    """Create a folder under a local vault."""
    output(local_mod.make_folder(vault_path, folder), f"Folder ready: {folder}")


@local.command("write-file")
@click.argument("path")
@click.option("--content", "-c", default="", help="Text content.")
@click.option("--file", "-f", "input_file", type=click.Path(exists=True),
              help="Read content from file.")
@handle_error
def local_write_file(path, content, input_file):
    """Create or replace a local file."""
    output(local_mod.write_file(path, content, input_file), f"File written: {path}")


@local.command("config-write")
@click.argument("vault_path")
@click.argument("name")
@click.option("--json-text", default=None, help="JSON object or array to write.")
@click.option("--file", "-f", "input_file", type=click.Path(exists=True),
              help="Read JSON from file.")
@handle_error
def local_config_write(vault_path, name, json_text, input_file):
    """Write an Obsidian config JSON file."""
    output(local_mod.config_write(vault_path, name, json_text, input_file), f"Config written: {name}")


@local.command("config-set")
@click.argument("vault_path")
@click.argument("name")
@click.argument("key")
@click.argument("value")
@handle_error
def local_config_set(vault_path, name, key, value):
    """Set a key in an Obsidian config JSON file."""
    output(local_mod.config_set(vault_path, name, key, value), f"Config updated: {name}")


@local.command("plugin-enable")
@click.argument("vault_path")
@click.argument("plugin_id")
@click.option("--type", "plugin_type", type=click.Choice(["community", "core"]),
              default="community", help="Plugin type.")
@click.option("--disabled", is_flag=True, help="Disable instead of enable.")
@handle_error
def local_plugin_enable(vault_path, plugin_id, plugin_type, disabled):
    """Enable or disable a local plugin config entry."""
    output(local_mod.plugin_enable(vault_path, plugin_id, plugin_type, not disabled), "Plugin config updated.")


@local.command("plugin-setting")
@click.argument("vault_path")
@click.argument("plugin_id")
@click.argument("key")
@click.argument("value")
@handle_error
def local_plugin_setting(vault_path, plugin_id, key, value):
    """Set a community plugin setting."""
    output(local_mod.plugin_setting(vault_path, plugin_id, key, value), "Plugin setting updated.")


@local.command("hotkey-set")
@click.argument("vault_path")
@click.argument("command_id")
@click.option("--key", "key_name", required=True, help="Keyboard key.")
@click.option("--modifier", multiple=True, help="Hotkey modifier; repeat for multiple.")
@handle_error
def local_hotkey_set(vault_path, command_id, key_name, modifier):
    """Set a hotkey binding."""
    output(local_mod.hotkey_set(vault_path, command_id, key_name, modifier), "Hotkey updated.")


@local.command("bookmark-add")
@click.argument("vault_path")
@click.argument("path")
@click.option("--type", "item_type", default="file", help="Bookmark item type.")
@handle_error
def local_bookmark_add(vault_path, path, item_type):
    """Add a bookmark entry."""
    output(local_mod.bookmark_add(vault_path, path, item_type), "Bookmark added.")


@local.command("workspace-set")
@click.argument("vault_path")
@click.option("--active", default=None, help="Active file path.")
@click.option("--json-text", default=None, help="Workspace JSON object.")
@handle_error
def local_workspace_set(vault_path, active, json_text):
    """Write workspace state."""
    output(local_mod.workspace_set(vault_path, active, json_text), "Workspace updated.")


@local.command("global-config-set")
@click.argument("key")
@click.argument("value")
@click.option("--config-path", default=None, help="Override global obsidian.json path.")
@handle_error
def local_global_config_set(key, value, config_path):
    """Set a key in global obsidian.json."""
    output(local_mod.global_config_set(key, value, config_path), "Global config updated.")


# ── Search Commands ─────────────────────────────────────────────
@cli.group()
def search():
    """Search operations."""
    pass


@search.command("query")
@click.argument("query")
@handle_error
def search_query(query):
    """Search vault using Obsidian's search engine."""
    _require_api_key()
    result = search_mod.search_query(_host, _api_key, query)
    if _json_output:
        output(result)
    else:
        if isinstance(result, list):
            if not result:
                click.echo("No results found.")
                return
            for item in result:
                filename = item.get("filename", "unknown")
                score = item.get("score", "")
                click.echo(f"  {filename}" + (f"  (score: {score})" if score else ""))
        else:
            output(result)


@search.command("simple")
@click.argument("query")
@click.option("--context-length", "-l", type=int, default=100,
              help="Context characters around matches (default: 100)")
@handle_error
def search_simple(query, context_length):
    """Simple text search across the vault."""
    _require_api_key()
    result = search_mod.search_simple(_host, _api_key, query, context_length=context_length)
    if _json_output:
        output(result)
    else:
        if isinstance(result, list):
            if not result:
                click.echo("No results found.")
                return
            for item in result:
                filename = item.get("filename", "unknown")
                matches = item.get("matches", [])
                click.echo(f"  {filename} ({len(matches)} matches)")
                for match in matches[:3]:
                    context = match.get("context", match.get("match", ""))
                    if len(context) > 120:
                        context = context[:120] + "..."
                    click.echo(f"    ...{context}...")
        else:
            output(result)


# ── Note Commands ───────────────────────────────────────────────
@cli.group()
def note():
    """Active note operations."""
    pass


@note.command("active")
@handle_error
def note_active():
    """Get the currently active note in Obsidian."""
    _require_api_key()
    result = note_mod.get_active(_host, _api_key)
    if _json_output:
        output(result)
    else:
        click.echo(result.get("content", "(no active note)"))


@note.command("open")
@click.argument("path")
@handle_error
def note_open(path):
    """Open a note in Obsidian."""
    _require_api_key()
    global _last_path
    _last_path = path
    result = note_mod.open_note(_host, _api_key, path)
    output(result, f"Opened: {path}")


# ── Command Commands ────────────────────────────────────────────
@cli.group("command")
def command_group():
    """Obsidian command operations."""
    pass


@command_group.command("list")
@handle_error
def command_list():
    """List available Obsidian commands."""
    _require_api_key()
    result = cmd_mod.list_commands(_host, _api_key)
    if _json_output:
        output(result)
    else:
        commands = result.get("commands", result if isinstance(result, list) else [])
        if not commands:
            click.echo("No commands available.")
            return
        click.echo(f"{'ID':<40} {'NAME'}")
        click.echo("─" * 70)
        for cmd in commands:
            cmd_id = cmd.get("id", "")
            cmd_name = cmd.get("name", "")
            click.echo(f"{cmd_id:<40} {cmd_name}")


@command_group.command("execute")
@click.argument("command_id")
@handle_error
def command_execute(command_id):
    """Execute an Obsidian command by ID."""
    _require_api_key()
    result = cmd_mod.execute_command(_host, _api_key, command_id)
    output(result, f"Executed: {command_id}")


# ── Server Commands ─────────────────────────────────────────────
@cli.group()
def server():
    """Server status commands."""
    pass


@server.command("status")
@handle_error
def server_status():
    """Check if Obsidian REST API is running."""
    _require_api_key()
    result = server_mod.server_status(_host, _api_key)
    output(result, f"Obsidian REST API at {_host}: running")


# ── Session Commands ────────────────────────────────────────────
@cli.group()
def session():
    """Session state commands."""
    pass


@session.command("status")
@handle_error
def session_status():
    """Show current session state."""
    data = {
        "host": _host,
        "api_key_set": bool(_api_key),
        "last_path": _last_path or "(none)",
        "json_output": _json_output,
    }
    output(data, "Session Status")


# ── REPL ────────────────────────────────────────────────────────
@cli.command()
@handle_error
def repl():
    """Start interactive REPL session."""
    from cli_anything.obsidian.utils.repl_skin import ReplSkin

    global _repl_mode
    _repl_mode = True

    skin = ReplSkin("obsidian", version="1.0.0")
    skin.print_banner()

    pt_session = skin.create_prompt_session()

    _repl_commands = {
        "vault":   "list|read|create|update|delete|append",
        "local":   "init|write-note|append-note|mkdir|write-file|config-write|config-set|plugin-enable|plugin-setting|hotkey-set|bookmark-add|workspace-set|global-config-set",
        "search":  "query|simple",
        "note":    "active|open",
        "command": "list|execute",
        "server":  "status",
        "session": "status",
        "help":    "Show this help",
        "quit":    "Exit REPL",
    }

    while True:
        try:
            context = _last_path if _last_path else ""
            line = skin.get_input(pt_session, project_name=context, modified=False)
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                skin.print_goodbye()
                break
            if line.lower() == "help":
                skin.help(_repl_commands)
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


# ── Entry Point ─────────────────────────────────────────────────
def main():
    cli()


if __name__ == "__main__":
    main()
