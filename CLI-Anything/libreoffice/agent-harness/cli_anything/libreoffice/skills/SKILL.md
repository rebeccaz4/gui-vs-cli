---
name: "cli-anything-libreoffice"
description: "Command-line interface for creating, editing, importing, patching, and exporting LibreOffice Writer, Calc, and Impress documents."
---

# cli-anything-libreoffice

A stateful command-line interface for LibreOffice documents. It can create project JSON, import existing spreadsheets, import Writer `.odt`/`.docx` files, import Impress `.odp`/`.pptx`/`.ppt` files, patch existing Calc `.xlsx` files, write LibreOffice preferences, and export Writer, Calc, and Impress files.

## Usage

```bash
cli-anything-libreoffice [--json] [--project PROJECT.json] <command-group> <command> [args/options]
```

Run without a subcommand to start the interactive REPL.

## Command Groups

### Document

Document management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new document |
| `open` | Open a project JSON file |
| `import-spreadsheet` | Import an existing `.xlsx` spreadsheet into project state |
| `save` | Save the current project |
| `info` | Show document information |
| `profiles` | List page profiles |
| `json` | Print raw project JSON |

### Writer

Writer document commands.

| Command | Description |
|---------|-------------|
| `add-paragraph` | Add a paragraph |
| `add-heading` | Add a heading |
| `add-list` | Add a list |
| `add-table` | Add a table |
| `set-table-cell` | Set a Writer table cell value |
| `add-image` | Add an image reference |
| `add-bookmark` | Add a bookmark marker |
| `set-header` | Set Writer header text |
| `set-footer` | Set Writer footer text |
| `import-document` | Import an existing `.odt` or `.docx` into project state |
| `add-page-break` | Add a page break |
| `remove` | Remove content by index |
| `list` | List content items |
| `set-text` | Update content text |

### Calc

Spreadsheet commands.

| Command | Description |
|---------|-------------|
| `add-sheet` | Add a sheet |
| `remove-sheet` | Remove a sheet |
| `rename-sheet` | Rename a sheet |
| `set-cell` | Set a cell value or formula |
| `get-cell` | Get a cell value |
| `list-sheets` | List sheets |
| `format-cell` | Format a cell |
| `merge-cells` | Merge a cell range |
| `named-range` | Create or update a named range |
| `data-validation` | Add a data validation rule |
| `conditional-format` | Add a conditional formatting rule |
| `autofilter` | Enable AutoFilter on a range |
| `freeze-rows` | Freeze the first N rows |
| `active-sheet` | Set the active sheet |

Calc commands that accept `--file` patch an existing `.xlsx` directly.

### Impress

Presentation commands.

| Command | Description |
|---------|-------------|
| `add-slide` | Add a slide |
| `remove-slide` | Remove a slide |
| `set-content` | Update slide title or content |
| `list-slides` | List slides |
| `add-element` | Add an element to a slide |
| `import-presentation` | Import an existing `.odp`, `.pptx`, or `.ppt` into project state |
| `import-odp` | Import an existing `.odp` into project state |
| `set-notes` | Set speaker notes for a slide |
| `set-transition` | Set slide transition metadata |
| `set-footer` | Set a footer declaration and enable it |
| `set-header` | Set a header declaration and enable it |
| `enable-slide-number` | Enable slide number on a slide |
| `add-animation` | Add a simple animation marker |

### Style

Style commands.

| Command | Description |
|---------|-------------|
| `create` | Create a style |
| `modify` | Modify a style |
| `list` | List styles |
| `apply` | Apply a style to Writer content |
| `remove` | Remove a style |

### Export

Export commands.

| Command | Description |
|---------|-------------|
| `presets` | List export presets |
| `preset-info` | Show preset details |
| `render` | Export the document |

Writer export presets include `odt`, `html`, `text`, `docx`, `doc`, `rtf`, and `pdf`.

### Config

LibreOffice configuration commands.

| Command | Description |
|---------|-------------|
| `set-calc-pref` | Set a Calc preference |
| `set-registry` | Set an arbitrary LibreOffice registry value |

### Session

Session commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `history` | Show undo history |

## Examples

```bash
cli-anything-libreoffice --project report.json writer add-table --name Results --rows 2 --cols 2
cli-anything-libreoffice writer import-document existing.docx --output imported.json
cli-anything-libreoffice --project budget.json calc set-cell A1 Total --type string
cli-anything-libreoffice calc set-cell B2 100 --type float --sheet-name Data --file /home/user/Documents/report.xlsx
cli-anything-libreoffice --project deck.json impress add-slide --title Overview --content "Project Overview" --layout 1
cli-anything-libreoffice impress import-presentation existing.pptx --output imported.json
```

## Version

1.0.0
