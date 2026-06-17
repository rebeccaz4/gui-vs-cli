# LibreOffice Calc Verifier

Programmatic state inspection for LibreOffice Calc spreadsheets in E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Prerequisites

Launch LibreOffice Calc with UNO socket listener enabled:

```bash
soffice --calc --accept="socket,host=localhost,port=2002;urp;" --norestore &
```

For file-based verification (ODF parsing), no running instance is needed — just a saved `.ods` file.

## Verification Channels

| Channel | When to use | Needs running LO? |
|---------|-------------|-------------------|
| **UNO API** | Live cell values, formatting, formulas, sheet structure | Yes |
| **ODF parsing** | Saved file content, offline verification | No |
| **File checks** | File existence, save state | No |

## Endpoint Reference

### UNO Live State

#### `sheets`
List all sheets in the current workbook.
```bash
python3 /home/user/verifiers/libreoffice_calc.py sheets
```
```json
{"sheets": [{"name": "Sheet1", "index": 0, "rows": 10, "cols": 5, "visible": true}], "active": "Sheet1", "count": 1}
```

#### `active-sheet`
Get the name and index of the active sheet.
```bash
python3 /home/user/verifiers/libreoffice_calc.py active-sheet
```
```json
{"name": "Sheet1", "index": 0}
```

#### `doc-info`
Get document metadata.
```bash
python3 /home/user/verifiers/libreoffice_calc.py doc-info
```
```json
{"path": "file:///home/user/test.ods", "title": "test.ods", "sheet_count": 3, "modified": true}
```

#### `cell-value <cell_ref> [sheet_name]`
Get the value, type, display string, and formula of a cell.
```bash
python3 /home/user/verifiers/libreoffice_calc.py cell-value A1
python3 /home/user/verifiers/libreoffice_calc.py cell-value B5 "Sales Data"
```
```json
{"cell": "A1", "value": 42, "type": "float", "display": "42", "formula": null, "sheet": "Sheet1"}
```

#### `range-values <range_ref> [sheet_name]`
Get values for a rectangular range.
```bash
python3 /home/user/verifiers/libreoffice_calc.py range-values A1:C3
```
```json
{"range": "A1:C3", "data": [[1, "Name", 100], [2, "Alice", 200], [3, "Bob", 300]], "rows": 3, "cols": 3, "sheet": "Sheet1"}
```

#### `sheet-data [sheet_name]`
Get all data from a sheet (up to 50 rows x 26 cols).
```bash
python3 /home/user/verifiers/libreoffice_calc.py sheet-data
python3 /home/user/verifiers/libreoffice_calc.py sheet-data "Sales Data"
```
```json
{"sheet": "Sheet1", "data": [...], "rows": 10, "cols": 3, "headers": ["A", "B", "C"]}
```

#### `cell-format <cell_ref> [sheet_name]`
Get formatting info for a cell (font, colors, alignment, number format).
```bash
python3 /home/user/verifiers/libreoffice_calc.py cell-format A1
```
```json
{"cell": "A1", "bold": true, "italic": false, "font_name": "Arial", "font_size": 12.0, "font_color": "#000000", "bg_color": "#FFFF00", "h_align": "center", "v_align": "center", "number_format": "General", "wrap_text": false}
```

#### `merged-cells [sheet_name]`
Get all merged cell ranges.
```bash
python3 /home/user/verifiers/libreoffice_calc.py merged-cells
```
```json
{"merged": ["A1:C1", "B3:B5"], "count": 2, "sheet": "Sheet1"}
```

### ODF File Parsing (Offline)

These commands parse `.ods` files directly — no running LibreOffice needed.

#### `parse-sheets [file_path]`
List sheets from an ODS file.
```bash
python3 /home/user/verifiers/libreoffice_calc.py parse-sheets /home/user/report.ods
```
```json
{"sheets": [{"name": "Sheet1", "rows": 10, "cols": 3}], "count": 1, "file": "/home/user/report.ods"}
```

#### `parse-cell <cell_ref> [file_path] [sheet_name]`
Read a cell value from an ODS file.
```bash
python3 /home/user/verifiers/libreoffice_calc.py parse-cell A1 /home/user/report.ods
```
```json
{"cell": "A1", "value": 42, "display": "42", "type": "float", "formula": null}
```

#### `parse-range <range_ref> [file_path] [sheet_name]`
Read a range from an ODS file.
```bash
python3 /home/user/verifiers/libreoffice_calc.py parse-range A1:B3 /home/user/report.ods
```
```json
{"range": "A1:B3", "data": [[1, "Name"], [2, "Alice"], [3, "Bob"]], "rows": 3, "cols": 2}
```

### Composite Checks (Reward Signals)

All `check-*` commands return a dict with a **primary boolean key** that maps directly to a reward signal.

#### `check-cell-value <cell_ref> <expected> [sheet_name]`
Check if a cell matches an expected value. Numeric-aware comparison.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-cell-value A1 42
python3 /home/user/verifiers/libreoffice_calc.py check-cell-value B2 "Hello" "Sheet2"
```
```json
{"match": true, "cell": "A1", "expected": "42", "actual": 42, "display": "42"}
```
**Reward key:** `match`

#### `check-sheet-exists <sheet_name>`
Check if a sheet with the given name exists.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-sheet-exists "Sales Data"
```
```json
{"exists": true, "sheet": "Sales Data", "index": 1}
```
**Reward key:** `exists`

#### `check-sheet-count <expected_count>`
Check the number of sheets.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-sheet-count 3
```
```json
{"match": true, "expected": 3, "actual": 3}
```
**Reward key:** `match`

#### `check-cell-formula <cell_ref> <expected_formula> [sheet_name]`
Check if a cell contains the expected formula (case-insensitive, leading `=` optional).
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-cell-formula C1 "=A1+B1"
```
```json
{"match": true, "cell": "C1", "expected": "=A1+B1", "actual": "=A1+B1"}
```
**Reward key:** `match`

#### `check-cell-formatted <cell_ref> [bold=true/false]`
Check if a cell has specific formatting. Via CLI, checks bold only; use Python API for full control.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-cell-formatted A1 true
```
```json
{"match": true, "cell": "A1", "checks": {"bold": {"expected": true, "actual": true, "ok": true}}}
```
**Reward key:** `match`

#### `check-column-sorted <col> [asc/desc] [start_row]`
Check if a column is sorted.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-column-sorted A
python3 /home/user/verifiers/libreoffice_calc.py check-column-sorted B desc 2
```
```json
{"sorted": true, "column": "A", "direction": "ascending", "rows_checked": 10}
```
**Reward key:** `sorted`

#### `check-file-exists <file_path>`
Check if a spreadsheet file exists.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-file-exists /home/user/report.ods
```
```json
{"exists": true, "path": "/home/user/report.ods", "size": 12345}
```
**Reward key:** `exists`

#### `check-file-saved [file_path]`
Check if the document has been saved (no unsaved modifications).
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-file-saved
```
```json
{"saved": true, "path": "file:///home/user/test.ods"}
```
**Reward key:** `saved`

#### `check-merged-cells <range_ref> [sheet_name]`
Check if a specific range is merged.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-merged-cells A1:C1
```
```json
{"merged": true, "range": "A1:C1"}
```
**Reward key:** `merged`

### Preferences & Settings (registrymodifications.xcu)

#### `calc-prefs`
Return a dict of known Calc-related user preferences parsed from `~/.config/libreoffice/4/user/registrymodifications.xcu`.
```bash
python3 /home/user/verifiers/libreoffice_calc.py calc-prefs
```
Keys: `default_sheet_count`, `default_save_filter_calc`, `measurement_unit_calc`, `raw`.

#### `check-calc-pref <key> <expected>`
Check a known Calc preference against an expected value.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-calc-pref default_sheet_count 5
python3 /home/user/verifiers/libreoffice_calc.py check-calc-pref default_save_filter_calc "MS Excel 2007"
python3 /home/user/verifiers/libreoffice_calc.py check-calc-pref measurement_unit_calc 2
```
**Reward key:** `match`

### Conditional Formatting / Named Ranges / Data Validation / AutoFilter / Freeze

#### `check-conditional-format <range> [sheet_name]`
Check whether any conditional-formatting rule covers cells intersecting `<range>` on the given sheet.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-conditional-format B2:E13 Sales
```
**Reward key:** `match`

#### `check-named-range <name> [expected_content]`
Check whether a named range is defined in the workbook. Optionally require that its content string contains `expected_content`.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-named-range CustomerList
python3 /home/user/verifiers/libreoffice_calc.py check-named-range TaxRate Settings
```
**Reward key:** `match`

#### `check-data-validation <cell> [sheet_name]`
Check whether a cell has any non-ANY data-validation rule applied.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-data-validation B2 Orders
```
**Reward key:** `match`

#### `check-autofilter [sheet_name]`
Check whether AutoFilter is enabled on the sheet.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-autofilter Employees
```
**Reward key:** `match`

#### `check-frozen-rows <expected_rows> [sheet_name]`
Check whether the first N rows are frozen on the sheet.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-frozen-rows 1 Employees
```
**Reward key:** `match`

#### `check-csv-rows <file_path> <expected_rows> [has_header=true]`
Check that a CSV file has the expected number of data rows.
```bash
python3 /home/user/verifiers/libreoffice_calc.py check-csv-rows /home/user/Documents/out.csv 5
```
**Reward key:** `match`

## Common Verification Patterns

### Check if user entered a value in a cell
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py check-cell-value A1 42")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if user created a formula
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_calc.py check-cell-formula C1 "=SUM(A1:B1)"')
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if user created a new sheet
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_calc.py check-sheet-exists "Summary"')
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if user formatted cells bold
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py check-cell-formatted A1 true")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if user sorted a column
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py check-column-sorted A")
data = json.loads(result.stdout)
reward = 1.0 if data["sorted"] else 0.0
```

### Read a saved ODS file without LibreOffice running
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py parse-cell A1 /home/user/output.ods")
data = json.loads(result.stdout)
value = data["value"]
```

### Verify entire range matches expected data
```python
# From Python API (check agent):
from verifiers.libreoffice_calc import LibreOfficeCalcVerifier
v = LibreOfficeCalcVerifier()
result = v.check_range_values("A1:C3", [[1, "Name", 100], [2, "Alice", 200], [3, "Bob", 300]])
reward = 1.0 if result["match"] else 0.0
```
