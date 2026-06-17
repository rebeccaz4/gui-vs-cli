#!/usr/bin/env python3
"""LibreOffice CLI -- A stateful command-line interface for document editing.

This CLI provides document creation and editing capabilities for Writer,
Calc, and Impress documents, with export to real ODF files (ZIP archives).

Usage:
    # One-shot commands
    python3 -m cli.libreoffice_cli document new --type writer --name "Report"
    python3 -m cli.libreoffice_cli writer add-paragraph --text "Hello world"
    python3 -m cli.libreoffice_cli export render output.odt --preset odt

    # Interactive REPL
    python3 -m cli.libreoffice_cli repl
"""

import sys
import os
import json
import shlex
import click
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_anything.libreoffice.core.session import Session
from cli_anything.libreoffice.core import document as doc_mod
from cli_anything.libreoffice.core import writer as writer_mod
from cli_anything.libreoffice.core import calc as calc_mod
from cli_anything.libreoffice.core import impress as impress_mod
from cli_anything.libreoffice.core import styles as styles_mod
from cli_anything.libreoffice.core import export as export_mod
from cli_anything.libreoffice.core import config as config_mod
from cli_anything.libreoffice.core import xlsx_patch as xlsx_patch_mod

# Global session state
_session: Optional[Session] = None
_json_output = False
_repl_mode = False


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


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
        except FileNotFoundError as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": "file_not_found"}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
        except (ValueError, IndexError, RuntimeError) as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
        except FileExistsError as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": "file_exists"}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ── Main CLI Group ──────────────────────────────────────────────
@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.option("--project", "project_path", type=str, default=None,
              help="Path to .lo-cli.json project file")
@click.option("--dry-run", "dry_run", is_flag=True, default=False,
              help="Run command without saving changes to disk")
@click.pass_context
def cli(ctx, use_json, project_path, dry_run):
    """LibreOffice CLI -- Stateful document editing from the command line.

    Run without a subcommand to enter interactive REPL mode.
    """
    global _json_output
    _json_output = use_json

    if project_path:
        sess = get_session()
        if not sess.has_project():
            proj = doc_mod.open_document(project_path)
            sess.set_project(proj, project_path)

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl, project_path=None)


@cli.result_callback()
def auto_save_on_exit(result, use_json, project_path, dry_run, **kwargs):
    """Auto-save project after one-shot commands if state was modified."""
    if _repl_mode:
        return
    if dry_run:
        return
    sess = get_session()
    if sess.has_project() and sess._modified and sess.project_path:
        try:
            sess.save_session()
        except Exception as e:
            click.echo(f"Warning: Auto-save failed: {e}", err=True)


# ── Document Commands ────────────────────────────────────────────
@cli.group()
def document():
    """Document management commands."""
    pass


@document.command("new")
@click.option("--type", "doc_type",
              type=click.Choice(["writer", "calc", "impress"]),
              default="writer", help="Document type")
@click.option("--name", "-n", default="untitled", help="Document name")
@click.option("--profile", "-p", type=str, default=None, help="Page profile")
@click.option("--output", "-o", "output_path", type=str, default=None, help="Save path")
@handle_error
def document_new(doc_type, name, profile, output_path):
    """Create a new document."""
    proj = doc_mod.create_document(doc_type=doc_type, name=name, profile=profile)
    sess = get_session()
    sess.set_project(proj, output_path)
    if output_path:
        doc_mod.save_document(proj, output_path)
    info = doc_mod.get_document_info(proj)
    output(info, f"Created {doc_type} document: {name}")


@document.command("open")
@click.argument("path")
@handle_error
def document_open(path):
    """Open an existing project file."""
    proj = doc_mod.open_document(path)
    sess = get_session()
    sess.set_project(proj, path)
    info = doc_mod.get_document_info(proj)
    output(info, f"Opened: {path}")


@document.command("import-spreadsheet")
@click.argument("input_path")
@click.option("--output", "-o", "output_path", type=str, default=None, help="Save imported project JSON")
@handle_error
def document_import_spreadsheet(input_path, output_path):
    """Import an existing spreadsheet into project state."""
    ext = os.path.splitext(input_path)[1].lower()
    if ext != ".xlsx":
        raise ValueError("Only .xlsx import is currently supported.")
    proj = xlsx_patch_mod.import_xlsx(input_path)
    sess = get_session()
    sess.set_project(proj, output_path)
    if output_path:
        doc_mod.save_document(proj, output_path)
    info = doc_mod.get_document_info(proj)
    output(info, f"Imported spreadsheet: {input_path}")


@document.command("save")
@click.argument("path", required=False)
@handle_error
def document_save(path):
    """Save the current document."""
    sess = get_session()
    saved = sess.save_session(path)
    output({"saved": saved}, f"Saved to: {saved}")


@document.command("info")
@handle_error
def document_info():
    """Show document information."""
    sess = get_session()
    info = doc_mod.get_document_info(sess.get_project())
    output(info)


@document.command("profiles")
@handle_error
def document_profiles():
    """List available page profiles."""
    profiles = doc_mod.list_profiles()
    output(profiles, "Available profiles:")


@document.command("json")
@handle_error
def document_json():
    """Print raw project JSON."""
    sess = get_session()
    click.echo(json.dumps(sess.get_project(), indent=2, default=str))


# ── Writer Commands ──────────────────────────────────────────────
@cli.group()
def writer():
    """Writer (word processor) commands."""
    pass


@writer.command("add-paragraph")
@click.option("--text", "-t", default="", help="Paragraph text")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@click.option("--font-size", type=str, default=None, help="Font size (e.g. 12pt)")
@click.option("--bold", is_flag=True, help="Bold text")
@click.option("--italic", is_flag=True, help="Italic text")
@click.option("--alignment", type=click.Choice(["left", "center", "right", "justify"]),
              default=None)
@handle_error
def writer_add_paragraph(text, position, font_size, bold, italic, alignment):
    """Add a paragraph to the document."""
    sess = get_session()
    sess.snapshot("Add paragraph")
    style = {}
    if font_size:
        style["font_size"] = font_size
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    if alignment:
        style["alignment"] = alignment
    item = writer_mod.add_paragraph(
        sess.get_project(), text=text, style=style or None, position=position,
    )
    output(item, "Added paragraph")


@writer.command("add-heading")
@click.option("--text", "-t", default="", help="Heading text")
@click.option("--level", "-l", type=int, default=1, help="Heading level (1-6)")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def writer_add_heading(text, level, position):
    """Add a heading to the document."""
    sess = get_session()
    sess.snapshot("Add heading")
    item = writer_mod.add_heading(
        sess.get_project(), text=text, level=level, position=position,
    )
    output(item, f"Added heading (level {level})")


@writer.command("add-list")
@click.option("--items", "-i", multiple=True, help="List items")
@click.option("--style", "list_style",
              type=click.Choice(["bullet", "number"]),
              default="bullet", help="List style")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def writer_add_list(items, list_style, position):
    """Add a list to the document."""
    sess = get_session()
    sess.snapshot("Add list")
    item = writer_mod.add_list(
        sess.get_project(), items=list(items), list_style=list_style,
        position=position,
    )
    output(item, f"Added {list_style} list")


@writer.command("add-table")
@click.option("--rows", "-r", type=int, default=2, help="Number of rows")
@click.option("--cols", "-c", type=int, default=2, help="Number of columns")
@click.option("--name", default=None, help="Table name")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def writer_add_table(rows, cols, name, position):
    """Add a table to the document."""
    sess = get_session()
    sess.snapshot("Add table")
    item = writer_mod.add_table(
        sess.get_project(), rows=rows, cols=cols, name=name, position=position,
    )
    output(item, f"Added {rows}x{cols} table")


@writer.command("set-table-cell")
@click.argument("table_index", type=int)
@click.argument("row", type=int)
@click.argument("col", type=int)
@click.argument("value")
@handle_error
def writer_set_table_cell(table_index, row, col, value):
    """Set a Writer table cell value."""
    sess = get_session()
    sess.snapshot(f"Set table {table_index} cell {row},{col}")
    result = writer_mod.set_table_cell(sess.get_project(), table_index, row, col, value)
    output(result, "Set table cell")


@writer.command("add-image")
@click.argument("path")
@click.option("--name", default="Image", help="Image name")
@click.option("--width", default="5cm", help="Image width")
@click.option("--height", default="5cm", help="Image height")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def writer_add_image(path, name, width, height, position):
    """Add an image reference to the document."""
    sess = get_session()
    sess.snapshot("Add image")
    result = writer_mod.add_image(
        sess.get_project(), path=path, name=name, width=width, height=height,
        position=position,
    )
    output(result, "Added image")


@writer.command("add-bookmark")
@click.argument("name")
@click.option("--text", default="", help="Visible text wrapped by the bookmark")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def writer_add_bookmark(name, text, position):
    """Add a bookmark marker."""
    sess = get_session()
    sess.snapshot(f"Add bookmark {name}")
    result = writer_mod.add_bookmark(sess.get_project(), name=name, text=text, position=position)
    output(result, "Added bookmark")


@writer.command("set-header")
@click.argument("text")
@handle_error
def writer_set_header(text):
    """Set Standard page style header text."""
    sess = get_session()
    sess.snapshot("Set writer header")
    result = writer_mod.set_header(sess.get_project(), text)
    output(result, "Set header")


@writer.command("set-footer")
@click.argument("text")
@handle_error
def writer_set_footer(text):
    """Set Standard page style footer text."""
    sess = get_session()
    sess.snapshot("Set writer footer")
    result = writer_mod.set_footer(sess.get_project(), text)
    output(result, "Set footer")


@writer.command("import-document")
@click.argument("path")
@click.option("--name", "-n", default=None, help="Imported project name")
@click.option("--output", "-o", type=str, default=None, help="Save imported project JSON")
@handle_error
def writer_import_document(path, name, output):
    """Import an existing .odt or .docx into Writer project JSON."""
    proj = writer_mod.import_document(path, name=name)
    sess = get_session()
    sess.set_project(proj, output)
    if output:
        doc_mod.save_document(proj, output)
    globals()["output"](doc_mod.get_document_info(proj), f"Imported: {path}")


@writer.command("add-page-break")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def writer_add_page_break(position):
    """Add a page break."""
    sess = get_session()
    sess.snapshot("Add page break")
    item = writer_mod.add_page_break(sess.get_project(), position=position)
    output(item, "Added page break")


@writer.command("remove")
@click.argument("index", type=int)
@handle_error
def writer_remove(index):
    """Remove a content item by index."""
    sess = get_session()
    sess.snapshot(f"Remove content {index}")
    removed = writer_mod.remove_content(sess.get_project(), index)
    output(removed, f"Removed content at index {index}")


@writer.command("list")
@handle_error
def writer_list():
    """List all content items."""
    sess = get_session()
    items = writer_mod.list_content(sess.get_project())
    output(items, "Content items:")


@writer.command("set-text")
@click.argument("index", type=int)
@click.argument("text")
@handle_error
def writer_set_text(index, text):
    """Set the text of a content item."""
    sess = get_session()
    sess.snapshot(f"Set text at {index}")
    item = writer_mod.set_content_text(sess.get_project(), index, text)
    output(item, f"Updated text at index {index}")


# ── Calc Commands ────────────────────────────────────────────────
@cli.group()
def calc():
    """Calc (spreadsheet) commands."""
    pass


@calc.command("add-sheet")
@click.option("--name", "-n", default="Sheet", help="Sheet name")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@handle_error
def calc_add_sheet(name, position):
    """Add a new sheet."""
    sess = get_session()
    sess.snapshot(f"Add sheet: {name}")
    sheet = calc_mod.add_sheet(sess.get_project(), name=name, position=position)
    output(sheet, f"Added sheet: {name}")


@calc.command("remove-sheet")
@click.argument("index", type=int)
@handle_error
def calc_remove_sheet(index):
    """Remove a sheet by index."""
    sess = get_session()
    sess.snapshot(f"Remove sheet {index}")
    removed = calc_mod.remove_sheet(sess.get_project(), index)
    output(removed, f"Removed sheet at index {index}")


@calc.command("rename-sheet")
@click.argument("index", type=int)
@click.argument("name")
@handle_error
def calc_rename_sheet(index, name):
    """Rename a sheet."""
    sess = get_session()
    sess.snapshot(f"Rename sheet {index}")
    sheet = calc_mod.rename_sheet(sess.get_project(), index, name)
    output(sheet, f"Renamed sheet {index} to: {name}")


@calc.command("set-cell")
@click.argument("ref")
@click.argument("value")
@click.option("--type", "cell_type", default="string", help="Cell type: string, float")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--formula", type=str, default=None, help="Cell formula")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_set_cell(ref, value, cell_type, sheet, sheet_name, formula, file_path):
    """Set a cell value."""
    if file_path:
        result = xlsx_patch_mod.set_cell(
            file_path, ref, value, sheet_name=sheet_name,
            sheet_index=sheet, formula=formula, cell_type=cell_type,
        )
        output(result, f"Patched {ref} in: {file_path}")
        return
    sess = get_session()
    sess.snapshot(f"Set cell {ref}")
    result = calc_mod.set_cell(
        sess.get_project(), ref=ref, value=value, cell_type=cell_type,
        sheet=sheet, formula=formula,
    )
    output(result, f"Set {ref} = {value}")


@calc.command("get-cell")
@click.argument("ref")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@handle_error
def calc_get_cell(ref, sheet):
    """Get a cell value."""
    sess = get_session()
    result = calc_mod.get_cell(sess.get_project(), ref=ref, sheet=sheet)
    output(result)


@calc.command("list-sheets")
@handle_error
def calc_list_sheets():
    """List all sheets."""
    sess = get_session()
    sheets = calc_mod.list_sheets(sess.get_project())
    output(sheets, "Sheets:")


@calc.command("format-cell")
@click.argument("ref")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--bold", is_flag=True, help="Apply bold formatting")
@click.option("--italic", is_flag=True, help="Apply italic formatting in project state")
@click.option("--font-color", type=str, default=None, help="Font color")
@click.option("--bg-color", type=str, default=None, help="Background color")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_format_cell(ref, sheet, sheet_name, bold, italic, font_color, bg_color, file_path):
    """Format a cell."""
    if file_path:
        result = xlsx_patch_mod.format_cell(
            file_path, ref, sheet_name=sheet_name, sheet_index=sheet, bold=bold,
        )
        output(result, f"Formatted {ref} in: {file_path}")
        return
    sess = get_session()
    sess.snapshot(f"Format cell {ref}")
    result = calc_mod.format_cell(
        sess.get_project(), ref=ref, sheet=sheet, bold=bold,
        italic=italic, font_color=font_color, bg_color=bg_color,
    )
    output(result, f"Formatted {ref}")


@calc.command("merge-cells")
@click.argument("range_ref")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_merge_cells(range_ref, sheet, sheet_name, file_path):
    """Merge a cell range."""
    if file_path:
        result = xlsx_patch_mod.merge_cells(
            file_path, range_ref, sheet_name=sheet_name, sheet_index=sheet,
        )
        output(result, f"Merged {range_ref} in: {file_path}")
        return
    sess = get_session()
    sess.snapshot(f"Merge cells {range_ref}")
    result = calc_mod.merge_cells(sess.get_project(), range_ref=range_ref, sheet=sheet)
    output(result, f"Merged {range_ref}")


@calc.command("named-range")
@click.argument("name")
@click.argument("target")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_named_range(name, target, file_path):
    """Create or update a named range."""
    if file_path:
        result = xlsx_patch_mod.add_named_range(file_path, name, target)
        output(result, f"Named range {name}: {target}")
        return
    sess = get_session()
    sess.snapshot(f"Named range {name}")
    result = calc_mod.add_named_range(sess.get_project(), name=name, target=target)
    output(result, f"Named range {name}: {target}")


@calc.command("data-validation")
@click.argument("range_ref")
@click.argument("formula")
@click.option("--type", "validation_type", default="list", help="Validation type")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_data_validation(range_ref, formula, validation_type, sheet, sheet_name, file_path):
    """Add a data-validation rule."""
    if file_path:
        result = xlsx_patch_mod.add_data_validation(
            file_path, range_ref, formula, sheet_name=sheet_name,
            sheet_index=sheet, validation_type=validation_type,
        )
        output(result, f"Added validation on {range_ref}")
        return
    sess = get_session()
    sess.snapshot(f"Data validation {range_ref}")
    result = calc_mod.add_data_validation(
        sess.get_project(), range_ref=range_ref, formula=formula,
        sheet=sheet, validation_type=validation_type,
    )
    output(result, f"Added validation on {range_ref}")


@calc.command("conditional-format")
@click.argument("range_ref")
@click.option("--formula", default="TRUE()", help="Conditional expression")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_conditional_format(range_ref, formula, sheet, sheet_name, file_path):
    """Add a conditional-formatting rule."""
    if file_path:
        result = xlsx_patch_mod.add_conditional_format(
            file_path, range_ref, sheet_name=sheet_name,
            sheet_index=sheet, formula=formula,
        )
        output(result, f"Added conditional format on {range_ref}")
        return
    sess = get_session()
    sess.snapshot(f"Conditional format {range_ref}")
    result = calc_mod.add_conditional_format(
        sess.get_project(), range_ref=range_ref, sheet=sheet, formula=formula,
    )
    output(result, f"Added conditional format on {range_ref}")


@calc.command("autofilter")
@click.argument("range_ref")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_autofilter(range_ref, sheet, sheet_name, file_path):
    """Enable AutoFilter on a range."""
    if file_path:
        result = xlsx_patch_mod.add_autofilter(
            file_path, range_ref, sheet_name=sheet_name, sheet_index=sheet,
        )
        output(result, f"Added AutoFilter on {range_ref}")
        return
    sess = get_session()
    sess.snapshot(f"AutoFilter {range_ref}")
    result = calc_mod.add_autofilter(sess.get_project(), range_ref=range_ref, sheet=sheet)
    output(result, f"Added AutoFilter on {range_ref}")


@calc.command("freeze-rows")
@click.argument("rows", type=int)
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_freeze_rows(rows, sheet, sheet_name, file_path):
    """Freeze the first N rows."""
    if file_path:
        result = xlsx_patch_mod.freeze_rows(
            file_path, rows, sheet_name=sheet_name, sheet_index=sheet,
        )
        output(result, f"Froze {rows} rows")
        return
    sess = get_session()
    sess.snapshot(f"Freeze rows {rows}")
    result = calc_mod.freeze_rows(sess.get_project(), rows=rows, sheet=sheet)
    output(result, f"Froze {rows} rows")


@calc.command("active-sheet")
@click.option("--sheet", "-s", type=int, default=0, help="Sheet index")
@click.option("--sheet-name", type=str, default=None, help="Sheet name for --file patching")
@click.option("--file", "file_path", type=str, default=None, help="Patch an existing .xlsx file directly")
@handle_error
def calc_active_sheet(sheet, sheet_name, file_path):
    """Set the active sheet."""
    if file_path:
        result = xlsx_patch_mod.set_active_sheet(
            file_path, sheet_name=sheet_name, sheet_index=sheet,
        )
        output(result, "Set active sheet")
        return
    sess = get_session()
    sess.snapshot(f"Active sheet {sheet}")
    result = calc_mod.set_active_sheet(sess.get_project(), sheet=sheet)
    output(result, "Set active sheet")


# ── Impress Commands ─────────────────────────────────────────────
@cli.group()
def impress():
    """Impress (presentation) commands."""
    pass


@impress.command("add-slide")
@click.option("--title", "-t", default="", help="Slide title")
@click.option("--content", "-c", default="", help="Slide content")
@click.option("--position", "-p", type=int, default=None, help="Insert position")
@click.option("--layout", type=int, default=None, help="Slide layout identifier")
@handle_error
def impress_add_slide(title, content, position, layout):
    """Add a slide to the presentation."""
    sess = get_session()
    sess.snapshot("Add slide")
    slide = impress_mod.add_slide(
        sess.get_project(), title=title, content=content, position=position,
        layout=layout,
    )
    output(slide, f"Added slide: {title}")


@impress.command("remove-slide")
@click.argument("index", type=int)
@handle_error
def impress_remove_slide(index):
    """Remove a slide by index."""
    sess = get_session()
    sess.snapshot(f"Remove slide {index}")
    removed = impress_mod.remove_slide(sess.get_project(), index)
    output(removed, f"Removed slide {index}")


@impress.command("set-content")
@click.argument("index", type=int)
@click.option("--title", "-t", type=str, default=None, help="New title")
@click.option("--content", "-c", type=str, default=None, help="New content")
@handle_error
def impress_set_content(index, title, content):
    """Update a slide's title and/or content."""
    sess = get_session()
    sess.snapshot(f"Update slide {index}")
    slide = impress_mod.set_slide_content(
        sess.get_project(), index, title=title, content=content,
    )
    output(slide, f"Updated slide {index}")


@impress.command("list-slides")
@handle_error
def impress_list_slides():
    """List all slides."""
    sess = get_session()
    slides = impress_mod.list_slides(sess.get_project())
    output(slides, "Slides:")


@impress.command("add-element")
@click.argument("slide_index", type=int)
@click.option("--type", "element_type", default="text_box", help="Element type")
@click.option("--text", "-t", default="", help="Element text")
@click.option("--x", default="2cm", help="X position")
@click.option("--y", default="2cm", help="Y position")
@click.option("--width", "-w", default="10cm", help="Width")
@click.option("--height", "-h", default="5cm", help="Height")
@click.option("--name", default=None, help="Element name")
@click.option("--href", default=None, help="Hyperlink URL")
@click.option("--action", default=None, help="Click action, such as show-page")
@click.option("--target", default=None, help="Action target slide name")
@handle_error
def impress_add_element(slide_index, element_type, text, x, y, width, height, name, href, action, target):
    """Add an element to a slide."""
    sess = get_session()
    sess.snapshot(f"Add element to slide {slide_index}")
    elem = impress_mod.add_slide_element(
        sess.get_project(), slide_index,
        element_type=element_type, text=text,
        x=x, y=y, width=width, height=height,
        name=name, href=href, action=action, target=target,
    )
    output(elem, f"Added {element_type} to slide {slide_index}")


@impress.command("import-odp")
@click.argument("path")
@click.option("--name", "-n", default=None, help="Imported project name")
@click.option("--output", "-o", type=str, default=None, help="Save imported project JSON")
@handle_error
def impress_import_odp(path, name, output):
    """Import an existing .odp into project JSON."""
    proj = impress_mod.import_odp(path, name=name)
    sess = get_session()
    sess.set_project(proj, output)
    if output:
        doc_mod.save_document(proj, output)
    globals()["output"](doc_mod.get_document_info(proj), f"Imported: {path}")


@impress.command("import-presentation")
@click.argument("path")
@click.option("--name", "-n", default=None, help="Imported project name")
@click.option("--output", "-o", type=str, default=None, help="Save imported project JSON")
@handle_error
def impress_import_presentation(path, name, output):
    """Import an existing .odp, .pptx, or .ppt into project JSON."""
    proj = impress_mod.import_presentation(path, name=name)
    sess = get_session()
    sess.set_project(proj, output)
    if output:
        doc_mod.save_document(proj, output)
    globals()["output"](doc_mod.get_document_info(proj), f"Imported: {path}")


@impress.command("set-notes")
@click.argument("slide_index", type=int)
@click.argument("notes")
@handle_error
def impress_set_notes(slide_index, notes):
    """Set speaker notes for a slide."""
    sess = get_session()
    sess.snapshot(f"Set notes on slide {slide_index}")
    slide = impress_mod.set_notes(sess.get_project(), slide_index, notes)
    output(slide, f"Set notes on slide {slide_index}")


@impress.command("set-transition")
@click.argument("slide_index", type=int)
@click.option("--type", "transition_type", default="fade", help="Transition type")
@click.option("--subtype", default="default", help="Transition subtype")
@click.option("--duration", type=float, default=2.0, help="Duration in seconds")
@handle_error
def impress_set_transition(slide_index, transition_type, subtype, duration):
    """Set slide transition metadata."""
    sess = get_session()
    sess.snapshot(f"Set transition on slide {slide_index}")
    result = impress_mod.set_transition(
        sess.get_project(), slide_index,
        transition_type=transition_type, subtype=subtype, duration=duration,
    )
    output(result, f"Set transition on slide {slide_index}")


@impress.command("set-footer")
@click.argument("text")
@click.option("--slide", "slide_index", type=int, default=None, help="Slide index; omit for all slides")
@click.option("--name", default="footer1", help="Footer declaration name")
@handle_error
def impress_set_footer(text, slide_index, name):
    """Set a footer declaration and enable it."""
    sess = get_session()
    sess.snapshot("Set footer")
    result = impress_mod.set_footer(sess.get_project(), text, slide_index=slide_index, name=name)
    output(result, "Set footer")


@impress.command("set-header")
@click.argument("text")
@click.option("--slide", "slide_index", type=int, default=None, help="Slide index; omit for all slides")
@click.option("--name", default="header1", help="Header declaration name")
@handle_error
def impress_set_header(text, slide_index, name):
    """Set a header declaration and enable it."""
    sess = get_session()
    sess.snapshot("Set header")
    result = impress_mod.set_header(sess.get_project(), text, slide_index=slide_index, name=name)
    output(result, "Set header")


@impress.command("enable-slide-number")
@click.argument("slide_index", type=int)
@handle_error
def impress_enable_slide_number(slide_index):
    """Enable slide number on a slide."""
    sess = get_session()
    sess.snapshot(f"Enable slide number on slide {slide_index}")
    result = impress_mod.enable_slide_number(sess.get_project(), slide_index)
    output(result, f"Enabled slide number on slide {slide_index}")


@impress.command("add-animation")
@click.argument("slide_index", type=int)
@click.option("--type", "animation_type", default="par", help="ODF animation element type")
@click.option("--target", default=None, help="Animation target element")
@handle_error
def impress_add_animation(slide_index, animation_type, target):
    """Add a simple animation marker to a slide."""
    sess = get_session()
    sess.snapshot(f"Add animation to slide {slide_index}")
    result = impress_mod.add_animation(
        sess.get_project(), slide_index, animation_type=animation_type, target=target,
    )
    output(result, f"Added animation to slide {slide_index}")


# ── Style Commands ───────────────────────────────────────────────
@cli.group("style")
def style_group():
    """Style management commands."""
    pass


@style_group.command("create")
@click.argument("name")
@click.option("--family", type=click.Choice(["paragraph", "text"]),
              default="paragraph", help="Style family")
@click.option("--parent", type=str, default=None, help="Parent style name")
@click.option("--prop", "-p", multiple=True, help="Property: key=value")
@handle_error
def style_create(name, family, parent, prop):
    """Create a new style."""
    props = _parse_props(prop)
    sess = get_session()
    sess.snapshot(f"Create style: {name}")
    result = styles_mod.create_style(
        sess.get_project(), name=name, family=family,
        parent=parent, properties=props,
    )
    output(result, f"Created style: {name}")


@style_group.command("modify")
@click.argument("name")
@click.option("--prop", "-p", multiple=True, help="Property: key=value")
@handle_error
def style_modify(name, prop):
    """Modify an existing style."""
    props = _parse_props(prop)
    sess = get_session()
    sess.snapshot(f"Modify style: {name}")
    result = styles_mod.modify_style(
        sess.get_project(), name=name, properties=props,
    )
    output(result, f"Modified style: {name}")


@style_group.command("list")
@handle_error
def style_list():
    """List all styles."""
    sess = get_session()
    styles = styles_mod.list_styles(sess.get_project())
    output(styles, "Styles:")


@style_group.command("apply")
@click.argument("style_name")
@click.argument("content_index", type=int)
@handle_error
def style_apply(style_name, content_index):
    """Apply a style to a content item (Writer only)."""
    sess = get_session()
    sess.snapshot(f"Apply style {style_name} to {content_index}")
    result = styles_mod.apply_style(
        sess.get_project(), style_name, content_index,
    )
    output(result, f"Applied style '{style_name}' to content {content_index}")


@style_group.command("remove")
@click.argument("name")
@handle_error
def style_remove(name):
    """Remove a style."""
    sess = get_session()
    sess.snapshot(f"Remove style: {name}")
    result = styles_mod.remove_style(sess.get_project(), name)
    output(result, f"Removed style: {name}")


# ── Export Commands ──────────────────────────────────────────────
@cli.group("export")
def export_group():
    """Export/render commands."""
    pass


@export_group.command("presets")
@handle_error
def export_presets():
    """List export presets."""
    presets = export_mod.list_presets()
    output(presets, "Export presets:")


@export_group.command("preset-info")
@click.argument("name")
@handle_error
def export_preset_info(name):
    """Show preset details."""
    info = export_mod.get_preset_info(name)
    output(info)


@export_group.command("render")
@click.argument("output_path")
@click.option("--preset", "-p", default="odt", help="Export preset")
@click.option("--overwrite", is_flag=True, help="Overwrite existing file")
@handle_error
def export_render(output_path, preset, overwrite):
    """Export the document to a file."""
    sess = get_session()
    result = export_mod.export(
        sess.get_project(), output_path,
        preset=preset, overwrite=overwrite,
    )
    output(result, f"Exported to: {output_path}")


# ── Config Commands ──────────────────────────────────────────────
@cli.group("config")
def config_group():
    """LibreOffice configuration commands."""
    pass


@config_group.command("set-calc-pref")
@click.argument("key")
@click.argument("value")
@click.option("--path", "config_path", type=str, default=None, help="registrymodifications.xcu path")
@handle_error
def config_set_calc_pref(key, value, config_path):
    """Set a Calc preference."""
    result = config_mod.set_preference(key, value, path=config_path)
    output(result, f"Set {key} = {value}")


@config_group.command("set-registry")
@click.argument("item_path")
@click.argument("prop_name")
@click.argument("value")
@click.option("--path", "config_path", type=str, default=None, help="registrymodifications.xcu path")
@handle_error
def config_set_registry(item_path, prop_name, value, config_path):
    """Set an arbitrary LibreOffice registry value."""
    result = config_mod.set_registry_value(item_path, prop_name, value, path=config_path)
    output(result, f"Set {item_path}/{prop_name} = {value}")


# ── Session Commands ─────────────────────────────────────────────
@cli.group()
def session():
    """Session management commands."""
    pass


@session.command("status")
@handle_error
def session_status():
    """Show session status."""
    sess = get_session()
    output(sess.status())


@session.command("undo")
@handle_error
def session_undo():
    """Undo the last operation."""
    sess = get_session()
    desc = sess.undo()
    output({"undone": desc}, f"Undone: {desc}")


@session.command("redo")
@handle_error
def session_redo():
    """Redo the last undone operation."""
    sess = get_session()
    desc = sess.redo()
    output({"redone": desc}, f"Redone: {desc}")


@session.command("history")
@handle_error
def session_history():
    """Show undo history."""
    sess = get_session()
    history = sess.list_history()
    output(history, "Undo history:")


# ── REPL ─────────────────────────────────────────────────────────
@cli.command()
@click.option("--project", "project_path", type=str, default=None)
@handle_error
def repl(project_path):
    """Start interactive REPL session."""
    from cli_anything.libreoffice.utils.repl_skin import ReplSkin

    global _repl_mode
    _repl_mode = True

    skin = ReplSkin("libreoffice", version="1.0.0")

    if project_path:
        sess = get_session()
        proj = doc_mod.open_document(project_path)
        sess.set_project(proj, project_path)

    skin.print_banner()

    pt_session = skin.create_prompt_session()

    def _get_project_name():
        try:
            s = get_session()
            proj = s.get_project()
            if proj and isinstance(proj, dict):
                return proj.get("name", "")
        except Exception:
            pass
        return ""

    def _is_modified():
        try:
            s = get_session()
            return s.is_modified() if hasattr(s, "is_modified") else False
        except Exception:
            return False

    while True:
        try:
            line = skin.get_input(
                pt_session,
                project_name=_get_project_name(),
                modified=_is_modified(),
            ).strip()
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                skin.print_goodbye()
                break
            if line.lower() == "help":
                _repl_help(skin)
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
                skin.error(f"Usage error: {e}")
            except Exception as e:
                skin.error(str(e))

        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break

    _repl_mode = False


def _repl_help(skin=None):
    commands = {
        "document new|open|save|info|profiles|json": "Document management",
        "writer add-paragraph|add-heading|add-list|add-table|set-table-cell|add-image|add-bookmark|set-header|set-footer|import-document|add-page-break|remove|list|set-text": "Writer editing",
        "calc add-sheet|remove-sheet|rename-sheet|set-cell|get-cell|list-sheets": "Spreadsheet editing",
        "impress add-slide|remove-slide|set-content|list-slides|add-element|import-presentation|import-odp|set-notes|set-transition|set-footer|set-header|enable-slide-number|add-animation": "Presentation editing",
        "style create|modify|list|apply|remove": "Style management",
        "export presets|preset-info|render": "Export/render documents",
        "config set-calc-pref|set-registry": "LibreOffice configuration",
        "session status|undo|redo|history": "Session management",
        "help": "Show this help",
        "quit": "Exit REPL",
    }
    if skin is not None:
        skin.help(commands)
    else:
        click.echo("\nCommands:")
        for cmd, desc in commands.items():
            click.echo(f"  {cmd:60s}  {desc}")
        click.echo()


def _parse_props(prop_list):
    """Parse property key=value pairs from CLI."""
    props = {}
    for p in prop_list:
        if "=" not in p:
            raise ValueError(f"Invalid property format: '{p}'. Use key=value.")
        k, v = p.split("=", 1)
        # Try to parse bool/number
        if v.lower() == "true":
            v = True
        elif v.lower() == "false":
            v = False
        else:
            try:
                v = float(v) if "." in v else int(v)
            except ValueError:
                pass
        props[k] = v
    return props


# ── Entry Point ──────────────────────────────────────────────────
def main():
    cli()


if __name__ == "__main__":
    main()
