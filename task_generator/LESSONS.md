# Task Design Lessons

Reusable insights collected from user feedback during task adjustment. Claude Code should read this file during task generation (Stage 1) and task evaluation (Stage 2) to avoid repeating past mistakes.

Lessons are organized by app. The **General** section applies to all apps.

---

## General

- Avoid using special characters (parentheses, brackets, ampersands, etc.) in verification command arguments. The eval runner passes commands through bash, so characters like `(` and `)` in e.g. `Python_(programming_language)` cause shell syntax errors. Use simpler substrings for checks when possible (e.g., `check-tab-open Python_programming` instead of `check-tab-open Python_(programming_language)`).

## Browsers (Brave, Chrome, Opera, Firefox)

- For browser tasks with multiple tabs, do not use check-page-contains to verify navigation — it only inspects the active tab and will give false negatives when a different tab is focused. Use check-tab-open to confirm a page was visited; successful navigation is sufficient verification for that step.

- Browser verifiers discover the profile directory (for bookmarks, history, etc.) by checking well-known paths under `~/.config/`. However, the eval runner launches browsers with `--user-data-dir=/tmp/<browser>-test-profile`, so the profile ends up in `/tmp/`, not `~/.config/`. The verifiers now include a `/tmp` glob fallback, but be aware of this when debugging "Profile not found" or "profile directory not found" errors.

- For browser form-filling tasks, do not use `check-page-contains` to verify entered values — `innerText` does not include text typed into `<input>` or `<textarea>` fields. Instead, use `eval` with JS that reads the input value directly (e.g., `document.querySelector('input[name=field]')?.value`), falling back to `document.body.innerText` to also cover the case where the form was already submitted and the response page is showing.

- `check-bookmark` and `check-cookie` may not work reliably due to sandbox profile path issues. For bookmark tasks, verify via `check-url-visited` or `check-tab-open` instead. For cookie tasks, verify via `check-page-contains` on pages that display cookie values (e.g., httpbin.org/cookies). For form field verification, prefer the dedicated `input <css_selector>` verifier command over raw `eval` with `getElementById` — it is purpose-built and does not assume specific element IDs.

## Brave

- For `check-page-contains`, use only single-word arguments. Multi-word arguments (e.g., `check-page-contains John Doe`) get split by the shell — the second word is misinterpreted as a tab index parameter, causing the check to crash with a ValueError. Use a unique single-word substring instead (e.g., `check-page-contains Doe`).

- For Brave bookmark and history checks, `check-bookmark` reads the JSON Bookmarks file and `check-url-visited` queries the SQLite History database — both require the profile directory to be discoverable. If these checks return null/error, the most likely cause is the profile path not being found (see Browsers section above).

## Chrome

- Chrome's verifier already searches `/tmp/chrome-*/Default` as a fallback for sandbox profiles. No known profile discovery issues.

## Blender

- All blender verification checks (except `check-file-exists`) require the `.blend` file to exist. If the agent fails to save the file, every subsequent check returns `{"error": "File not found: ..."}` and the checked key will be null. This is expected behavior, not a verifier bug — the first check should always be `check-file-exists` to confirm the file was saved.

- The sandbox runs Blender 3.x where the EEVEE render engine identifier is `BLENDER_EEVEE`. Do not use `BLENDER_EEVEE_NEXT` (Blender 4.x identifier) in `check-render-engine` commands.

- No need to check if the current file are saved, we auto save the file for checking.

## LibreOffice Calc

- When extending the verifier for preferences tasks, parse `~/.config/libreoffice/4/user/registrymodifications.xcu` (an XML file with `{http://openoffice.org/2001/registry}item` entries and `prop name=`/`value` children). Known keys: `Defaults/Sheet/SheetCount` for default new-workbook sheet count, `Save/Document/Calc` for default save filter, and `Layout/Other/MeasureUnit` under `.../Calc/` for Calc measurement unit (enum: 0=cm, 2=inch). The file is only written after LibreOffice exits cleanly, so preference-setting tasks must include a "close LibreOffice" step.

- For conditional-formatting verification via UNO, use `sheet.ConditionalFormats` which returns an `XConditionalFormats`; iterate `.ConditionalFormats` and check each CF's `Range.RangeAddresses` for intersection with the target range. Do not rely on `.Range.RangeAddress` (singular) alone — multi-range CFs expose `RangeAddresses` only.

- For AutoFilter detection via UNO, check both `doc.DatabaseRanges` and `doc.UnnamedDatabaseRanges` — user-created AutoFilters on a sheet without a named range live in the unnamed collection, accessible via `udbr.getByTable(sheet_index)`.

- For freeze-pane verification, read `controller.SplitRow` / `controller.SplitColumn` after `controller.setActiveSheet(sheet)`. `IsWindowSplit` returns true for both split and frozen modes — rely on SplitRow > 0 for rows-frozen checks.

## LibreOffice Writer

- Avoid `$` characters in verification command arguments — bash interprets `$1`, `$2`, etc. as positional parameters. For table cells or text containing dollar amounts, use `table-data` with `eval` instead of `check-table-cell`, and `paragraph-format` with `eval` instead of `check-text-contains`.
- When a task requires making text bold, verify the formatting with `check-paragraph-formatted` or `paragraph-format` with eval — do not rely solely on `check-text-contains`, which only checks text content and says nothing about formatting.
- UNO-based table commands (`check-table-exists`, `check-table-cell`, `tables`, `table-data`) frequently return null due to UNO connection issues with table objects. Use `parse-tables <file_path>` instead, which parses the saved ODT file directly without needing a running LibreOffice instance. Ensure `check-file-saved` runs before any `parse-tables` checks.
<!-- - For `parse-tables` eval expressions, always bounds-check array indices before accessing (e.g., `len(t.get('data', [])) > row_idx and len(t['data'][row_idx]) > col_idx`) — bare indexing with fallback defaults like `.get('data', [[]])` still causes IndexError on empty inner lists.
- In Writer table cell verification descriptions, don't quote numeric values (use `60`, not `'60'`). Use `parse-tables` with `eval` for all table content checks to avoid both UNO reliability issues and bash `$`-expansion problems with dollar amounts. -->

## Obsidian

- Do not wrap note content in `---` delimiters in task descriptions — Obsidian treats `---` at the start of a file as YAML frontmatter boundaries, and `#tags` inside frontmatter are parsed as YAML comments, not Obsidian tags. This causes `check-note-has-tag` to fail. Use plain Markdown body text for note content that includes inline tags or wiki links.

- The `plugin-settings` endpoint only reads `.obsidian/plugins/<id>/data.json` (community plugins). It does NOT read core plugin config files like `.obsidian/daily-notes.json`, so do not create tasks that check `format`/`folder` for core plugins via this endpoint. Fall back to `check-plugin-enabled` plus note-based verification for core-plugin tasks.

- The obsidian frontmatter parser is a hand-rolled parser, NOT real YAML. It tries `int(val)` then `float(val)` then stores as string. Dates like `2025-03-15` and paths like `/users` end up as plain strings (good). But the parser does NOT support nested structures, so avoid frontmatter tasks that require nested maps.

- For vault tasks requiring pre-existing notes, seed them via `env.files` with real `.md` files at `<VaultPath>/<note>.md` and include a placeholder `.obsidian/app.json` file so the vault directory exists before the agent opens the app. `create_vault.py` scripts in env/ are NOT automatically executed by `run_eval.py`.

## darktable

- Use `check-db-has-operation <filename> <operation>` instead of `check-xmp-has-operation` to verify darkroom edits. XMP sidecars may not be flushed to disk during a session, and darktable namespace URI mismatches cause silent parse failures. The `history` table in `library.db` is always current.
- Use `check-image-tagged-by-filename <filename> <tag_name>` and `check-image-rating-by-filename <filename> <rating>` instead of the `<image_id>`-based variants. Image IDs are not guaranteed to start at 1 across sandbox runs; filename-based lookups are portable.
- Do not use `check-tag-exists` as a standalone verification step — prefer `check-image-tagged-by-filename` which verifies both that the tag exists and is applied to the image. `check-tag-exists` can return false even when the tag is present due to internal darktable tag storage quirks, and a passing `check-image-tagged-by-filename` already implies the tag exists in the library.

- For browser form-filling tasks, do not use check-page-contains to verify entered values — innerText does not include text typed into <input> or <textarea> fields. Use eval with JS that reads the input value directly, falling back to innerText for the submitted response page.

## Thunderbird

- To generate a synthetic OpenPGP secret key for env/ artifacts, use `gpg --batch --passphrase '' --quick-generate-key 'Name <email>' rsa2048 default 0` (GnuPG 2.1+) instead of the older `--gen-key` batch-file approach, which rejects empty passphrases on modern gpg. Export with `gpg --armor --export-secret-keys <email>`.

- When extending the Thunderbird verifier with file-parsing endpoints (msgFilterRules.dat, virtualFolders.dat, feeds.json, Subscriptions.dat), all of them can be implemented with pure-stdlib file reads plus regex. The `msgFilterRules.dat` format stores filters as flat `name="..."`-style key/value blocks, one filter starts at each `name=` line. `virtualFolders.dat` uses `uri=...` block separators followed by key=value lines including `searchStr`. `feeds.json` is a plain JSON list of subscription dicts.

- Thunderbird's `check-calendar-event-exists` queries `calendar-data/local.sqlite`, but the calendar database may not exist or may not be flushed to disk reliably during a GUI session in the sandbox. Avoid calendar event verification in tasks unless the verifier is updated with a more robust check (e.g., scanning ICS files or forcing a DB flush). Prefer contact and message checks which use `abook.sqlite` and mbox files reliably.

- Thunderbird tasks require a pre-built profile tarball in `task_generator/tasks/<task_id>/env/thunderbird-profile.tar.gz` so the agent starts with a logged-in mailbox and clean state without any runtime downloads. Add that tarball to `env.files` with a sandbox path such as `/tmp/thunderbird-profile.tar.gz`; the eval runner uploads it, extracts it into `/home/user/`, then launches Thunderbird. The default OSWorld profile provides a fake offline mailbox (wrong IMAP/SMTP ports so nothing connects to a real server). To give a task a different initial mailbox state, replace the tarball inside that task's `env/` directory.

- Thunderbird verifier commands are passed through bash and split on whitespace via `sys.argv`. Multi-word arguments (names, subjects, body text, company names, job titles) MUST be wrapped in single quotes in the command string — e.g., `check-contact-field 'Elena Rodriguez' company 'GlobalTech Solutions'`. Without quotes, each word becomes a separate positional arg, causing args to shift and checks to silently test the wrong values.

## PCManFM

- `check-file-exists` may return null for files with compound extensions (e.g., `data.csv.bak`). When verifying that temp/backup files were deleted, prefer `check-file-count` on the parent directory as an alternative — it implicitly confirms deletions by verifying the expected item count.

- `check-file-exists` may return null for files with compound extensions (e.g., `data.csv.bak`). Use `check-file-count` on the parent directory as an alternative to verify deletions.

- `check-symlink` does exact string comparison on the target path. Trailing slashes cause mismatches (e.g., agent creates symlink to `/foo/bar/` but check expects `/foo/bar`). The verifier now normalizes trailing slashes, but task descriptions should also avoid trailing slashes on directory paths to reduce ambiguity.

- `check-bookmark-exists` did exact string comparison on bookmark paths without normalizing trailing slashes. GTK bookmarks for directories include a trailing slash in the URI (e.g., `file:///home/user/foo/`), so checks against `/home/user/foo` would fail. The verifier now normalizes trailing slashes for both path and URI comparisons.

- For symlink and bookmark verification, use `check-symlink` and `check-bookmark-exists` with `key`/`expected` format (not `eval`). Both `file-info` with eval expressions and the `check-*` commands with eval can fail silently in the eval runner even when the symlink/bookmark exists. Using `key`/`expected` bypasses the eval runner entirely and is the most reliable approach.

- Thunderbird calendar verification (check-calendar-event-exists) is unreliable — the calendar-data/local.sqlite DB may not exist or be flushed during a GUI session. Prefer contact and message checks which use abook.sqlite and mbox files reliably.

- For symlink and bookmark verification in PCManFM, use check-symlink and check-bookmark-exists with key/expected format — file-info and bookmarks with eval expressions also fail silently in the eval runner.

- `check-file-count` returns `match` (boolean), not `count`. Use `"key": "match", "expected": true` — using `"key": "count"` will always return null.

- `check-file-count` returns `match` (boolean), not `count`. Use `"key": "match", "expected": true` — using `"key": "count"` will always return null.

- `check-permissions` returns `match` (boolean), not `permissions`. Use `"key": "match", "expected": true` — using `"key": "permissions"` will always return null. Similarly, `check-symlink` returns `target_matches` (boolean), not `target`. Use `"key": "target_matches", "expected": true`.

## LibreOffice Impress

- For Impress preference tasks that read `registrymodifications.xcu`, the important `oor:path` values are: `/org.openoffice.Office.Common/Save/Document` (holds `AutoSave`, `AutoSaveTimeIntervall`, `CreateBackup`), `/org.openoffice.Office.Common/Save/Document/Impress` (holds `ooSetupFactoryDefaultFilter`, e.g. `Impress MS PowerPoint 2007 XML`), and `/org.openoffice.Office.Impress/Layout/Other/MeasureUnit` with prop `Metric` (enum: 0=cm, 8=inch). The file only flushes when LibreOffice exits cleanly — task must instruct the agent to close all LibreOffice windows.

- Minimal ODP files for Impress env synthesis can be built with stdlib (`zipfile` + raw XML strings). The archive must contain: `mimetype` (stored uncompressed, first entry, value `application/vnd.oasis.opendocument.presentation`), `META-INF/manifest.xml`, `content.xml`, `styles.xml`, `meta.xml`, `settings.xml`. `styles.xml` must include a `<style:page-layout>` with `fo:page-width`/`fo:page-height` — otherwise the new `parse-slide-size` / `check-slide-size` endpoints cannot read the slide dimensions.

- Do not use `check-file-saved` for tasks that save in non-native formats (e.g., .pptx). LibreOffice's `isModified()` flag may not be cleared after saving in PowerPoint format, causing false negatives. Use `check-file-exists <path>` instead to verify the file was saved to disk.

- Do not use `check-file-saved` (UNO isModified) for tasks that save in non-native formats like .pptx — LibreOffice may not clear the modified flag after format conversion. Use `check-file-exists` instead.

- Avoid verifying pre-existing slide content that wasn't part of the task edits — style/formatting differences between PPTX and ODP (or UNO text extraction quirks) can cause exact-match checks to fail on original content the agent didn't touch. Only verify content the agent was asked to add or change.

- Avoid verifying pre-existing slide content that wasn't part of the task edits — style/formatting differences between PPTX and ODP can cause exact-match checks to fail on original content the agent didn't touch. Only verify content the agent was asked to add or change.

## LibreOffice Draw

- UNO `page.getCount()` may include extra internal shapes (master page placeholders, presentation objects) beyond what is visually visible. Use `>=` comparisons via `pages` + `eval` for shape count checks instead of exact `check-shape-count` matches. Rely on `check-page-contains` for precise content verification.

- UNO-based table commands (check-table-exists, check-table-cell, tables, table-data) frequently return null due to UNO connection issues with table objects. Use parse-tables <file_path> instead, which parses the saved ODT file directly without needing a running LibreOffice instance. Ensure check-file-saved runs before any parse-tables checks.

- For Draw page-size / margins / background-fill verification, parse the saved `.odg` offline: `styles.xml` holds `style:page-layout` with `fo:page-width`/`page-height`/`margin-*`, and `style:master-page` links a master-page to its layout plus an optional `draw:style-name` whose `drawing-page-properties` carries `draw:fill` and `draw:fill-color`. Per-page `draw:style-name` on the `draw:page` element overrides the master's draw-style. Use `check-page-property <index> <key> <expected>` with keys `width_cm`, `height_cm`, `margin_*_cm`, `background_fill_color`, `name`, `master_page`. Numeric comparisons tolerate +/- 0.1 cm for format-rounding differences.

- For Draw preferences stored in `~/.config/libreoffice/4/user/registrymodifications.xcu`, useful prop paths include: `Office.Draw/Layout/Other/MeasureUnit::Metric` (enum: 0=1/100 mm, 1=mm, 2=cm, 8=inch, etc.), `Office.Draw/Snap/Grid/Options::VisibleGrid`/`SnapToGrid`, `Office.Draw/Snap/Grid/Resolution/{XAxis,YAxis}::Metric`, `Office.Draw/Snap/Grid/Subdivision/{XAxis,YAxis}::Count`, `Office.Common/Save/Document::Draw` (default save filter for Draw), `Office.Common/Save/Document::{AutoSave,AutoSaveTimeIntervall,CreateBackup}`. The file is only written on clean LO shutdown, so prefs tasks MUST include a "close LibreOffice" step.

- For PDF export verification of LibreOffice Draw tasks, a stdlib-only parser (regex + zlib for `/ObjStm`-compressed objects) is enough to extract `/Pages /Count` and `/Outlines` titles. Use `check-pdf-page-count <path> <n>` and `check-pdf-bookmark <path> <title_substring>`. Tasks that require bookmarks must explicitly tell the agent to enable "Export bookmarks" in the PDF export options dialog — it is not always default-on.

- For hyperlink-on-shape verification, do not rely on `check-page-contains` alone (it finds the visible link text but says nothing about whether an `xlink:href` is attached). Parse the saved ODG and look for elements with `xlink:href` attributes (both `draw:a` wrappers and `text:a` runs). Endpoint: `check-shape-hyperlink <page_index> <href_substring> [text_substring] [file_path]`.

- Shapes inserted via Draw's toolbar Ellipse/Rectangle/etc. buttons are `com.sun.star.drawing.CustomShape`, not native `EllipseShape`/`RectangleShape`; their geometric kind lives in `CustomShapeGeometry['Type']` (`'ellipse'`, `'rectangle'`, `'round-rectangle'`, …). `check-shape-exists <page> RectangleShape`/`EllipseShape` now matches both native types and the corresponding CustomShape geometry — so tasks can still phrase shape checks using the familiar native names.

## Inkscape / Kdenlive / Krita (creative apps)

- Do not rely on `create_env.py` or shell scripts to generate input files (videos, .kra archives) inside the sandbox at runtime — ffmpeg may not be available, scripts can silently fail, and the eval runner swallows errors. Instead, generate all input files locally (using PyAV, pure-Python ZIP builders, etc.), store them in the task's `env/` directory, and list them in `env.files` so the eval runner uploads them directly. This applies to video clips, kdenlive files for Kdenlive, `.kra` files for Krita, and SVG files for Inkscape.

## Inkscape

- Inkscape persists hex color values as lowercase (e.g. `#ff0000`) in the saved SVG, regardless of the case the agent entered in the XML editor. The verifier's `check-style-property` and `check-element-attribute` endpoints now compare `#`-prefixed values case-insensitively, so task authors can write colors in any case (`#FF0000` or `#ff0000`) and the check will pass either way. Do not rely on exact case when comparing fill/stroke values.

## Krita (.kra file format)

- **Krita .kra files must use Krita's exact native internal format.** A .kra is a ZIP archive, but Krita is very strict about the internal structure. Storing layer data as PNG files (e.g. `Background/data.png`) will cause Krita to show "unknown error" and refuse to open the file. The correct structure (verified against Krita 5.0.2) is:

  ```
  mimetype                              # MUST be first entry, ZIP_STORED (uncompressed)
  maindoc.xml                           # Document structure with xmlns namespace
  documentinfo.xml                      # Metadata
  preview.png                           # Small thumbnail (~256px longest side)
  {img_name}/layers/{filename}          # Layer tile data (text, NOT PNG)
  {img_name}/layers/{filename}.defaultpixel  # Raw pixel bytes (4 bytes BGRA for RGBA, 2 bytes for GRAYA)
  {img_name}/layers/{filename}.icc      # sRGB ICC profile per layer (9080 bytes)
  {img_name}/annotations/icc            # Document-level ICC profile
  mergedimage.png                       # Full-res flattened preview PNG
  {img_name}/animation/index.xml        # Animation metadata
  ```

- **Layer tile data files** are plain ASCII text, not binary image data:
  ```
  VERSION 2
  TILEWIDTH 64
  TILEHEIGHT 64
  PIXELSIZE 4
  DATA 0
  ```
  `PIXELSIZE` is 4 for RGBA, 2 for GRAYA. `DATA 0` means zero tiles (empty layer).

- **maindoc.xml must include** the `xmlns="http://www.calligra.org/DTD/krita"` namespace on the `<DOC>` element, and each `<layer>` must have `filename`, `uuid`, `collapsed`, `intimeline`, `channelflags`, `channellockflags`, `colorlabel`, `onionskin`, `locked`, and `selected` attributes. Layer filenames start at `layer2` (layer0/layer1 appear reserved). Example:
  ```xml
  <DOC xmlns="http://www.calligra.org/DTD/krita" kritaVersion="5.0.2" editor="Krita" syntaxVersion="2.0">
   <IMAGE x-res="300" y-res="300" width="800" name="painting" colorspacename="RGBA"
          mime="application/x-kra" height="600" description="" profile="sRGB-elle-V2-srgbtrc.icc">
    <layers>
     <layer colorspacename="RGBA" filename="layer2" nodetype="paintlayer" collapsed="0"
            channellockflags="" name="Background" compositeop="normal"
            uuid="{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}" selected="true" intimeline="1"
            opacity="255" channelflags="" y="0" x="0" colorlabel="0" onionskin="0"
            locked="1" visible="1"/>
    </layers>
    <ProjectionBackgroundColor ColorData="AAAAAA=="/>
    <GlobalAssistantsColor SimpleColorData="176,176,176,255"/>
    <animation>...</animation>
   </IMAGE>
  </DOC>
  ```

- **The sRGB ICC profile** (`sRGB-elle-V2-srgbtrc.icc`, 9080 bytes) must be embedded for each layer and as a document annotation. Extract it from a real Krita-generated file or the repo's `real_template.kra`.

- **To generate valid .kra files**, see the `create_test_kra()` function in `verifiers/krita/test_krita.py` which produces files that Krita opens without errors.

- Every task must have at least one file in `env.files` so the launch logic (`run_eval.py`) can open the app with that file. If `env.files` is empty, the app launches with no document and the agent must find and open the file manually — which usually fails. The first entry in `env.files` is used as the file to open.

- Do not use "Save As" to a different path. These apps' Save As dialogs are unreliable for GUI agents. Instead, upload the file directly to the path where verification will check, open the app with that file, and have the agent modify it in-place. The eval runner sends Ctrl+S after the agent finishes, which saves to the original path.

- Kdenlive verifier: Modern Kdenlive (21+) uses `<chain>` XML elements instead of `<producer>` for clips. The verifier's `_get_producers()` must search both tags.

## draw.io

- Every draw.io task must include a default empty `.drawio` file in `env.files`, uploaded to the sandbox path where verification checks the file. The task description should say "Open the file /home/user/Documents/foo.drawio in draw.io Desktop" and "Save the diagram" (not "Save as /path/...") so the agent overwrites the existing file.

- A minimal empty `.drawio` file is valid XML:
  ```xml
  <mxfile host="app.diagrams.net" modified="2024-01-15T10:00:00.000Z" agent="Mozilla/5.0" version="22.1.0" type="device">
    <diagram id="page1" name="Page-1">
      <mxGraphModel dx="1422" dy="762" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">
        <root>
          <mxCell id="0" />
          <mxCell id="1" parent="0" />
        </root>
      </mxGraphModel>
    </diagram>
  </mxfile>
  ```

## VLC

- VLC's `check-playlist-count` may return unreliable results — the HTTP API playlist structure can include nested nodes that inflate or misreport the count. Prefer `check-playing` and `check-media-loaded` for playlist playback tasks instead of exact playlist count checks.
