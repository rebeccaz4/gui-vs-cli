# Task Generation Pipeline

This document defines how to generate, evaluate, verify, synthesize environments for, and finalize GUI automation tasks. Claude Code performs each stage directly — there are no wrapper scripts to call.

## Directory Layout

```
task_generator/
├── CLAUDE.md              # This file — pipeline instructions
├── ENDPOINT_EXTENSION.md  # Workflow for adding new verifier endpoints
├── TASK_EXTENSION.md      # Workflow for expanding task coverage by app
├── LESSONS.md             # Accumulated lessons from past runs
└── tasks/                 # Output: one folder per generated task
    └── <task_id>/
        ├── task.json      # Final task spec (objective + verification commands)
        └── env/           # Input files the agent needs (CSV, ODS, images, etc.)
```

## Installed Apps in the Sandbox

The E2B `desktop-all-apps` template runs Ubuntu with XFCE and has these apps installed:

**Browsers:** Google Chrome, Firefox ESR, Brave, Opera
**Office/Productivity:** LibreOffice (Writer, Calc, Impress, Draw), gedit, galculator, Obsidian, Zotero
**Graphics/Design:** GIMP, Inkscape, Krita, darktable, draw.io Desktop
**3D/CAD:** FreeCAD, CloudCompare, RenderDoc
**Media:** VLC, OBS Studio, Kdenlive, Audacity, Shotcut
**Music:** MuseScore 3
**Game Development:** Godot 4
**Communication:** Zoom
**Development:** VS Code, Sublime Text, Eclipse IDE, GitHub Desktop
**System:** PCManFM (file manager), Thunderbird, xfce4 desktop, git, curl, wget, python3, ffmpeg

See `apps_to_include.json` for the full list. See `app_verifiability_report.md` for each app's verification channels, APIs, and file formats.

## Task JSON Schema

Every generated task must conform to this schema:

```json
{
  "id": "short_snake_case_id",
  "app": "gimp",
  "task": "Precise description of what the agent must do.",
  "env": {
    "files": [
      {"filename": "photo.png", "sandbox_path": "/home/user/Documents/photo.png"}
    ]
  },
  "verification": [
    {
      "command": "check-cell-value A1 42",
      "key": "match",
      "expected": true,
      "description": "A1 = 42"
    }
  ],
  "metadata": {
    "complexity": 4,
    "data_generatability": 5,
    "estimated_difficulty": 4
  }
}
```

Notes on the `verification` array:

- The `command` field must contain ONLY the verifier subcommand and args (e.g., `check-cell-value A1 42`). Do NOT include the `python3 /home/user/verifiers/<app>.py` prefix — `run_eval.py` prepends that automatically.
- `key` + `expected`: check `result[key] == expected` (for apps with `check-*` commands).
- `eval`: Python expression where `result` is the parsed JSON stdout.

---

## Pipeline Overview

```
Stage 1: Propose  →  Stage 2: Evaluate  →  Stage 3: Verify & Finalize  →  Stage 4: Synthesize Env
    (no verifier)       (complexity +          (match to verifier,          (generate input
                         data generatability)   adapt/extend/discard)        files)
```

Key principle: **do not consult verifiers during Stage 1 or Stage 2.** The verifier is ONLY read in Stage 3. Proposals should be creative and diverse, unconstrained by what the verifier currently supports. Verification matching happens only after a task has proven its worth on complexity and data generatability.

---

## Difficulty Scale

| Level | Steps | Example |
|-------|-------|---------|
| 1 | < 5 steps | "Type a value in A1" |
| 2 | 5-10 linear | "Can you make a new folder for me on the desktop? Let's call it 'Favorites.'" |
| 3 | 11-20, some reasoning | "I would like to copy all the numbers in the 'Old ID' column to the 'New 7 Digit Id' column, and pad them with zeros in front, to fill them up to seven digits." |
| 4 | 20-40 | "Here are two tables recording the per-month costs in 2019 and 2020. I want to create two column bar charts reflecting per-month total costs for each year from these data." |
| 5 | > 40 | "Using the inventory workbook, calculate stock turnover for each item, flag items with fewer than 10 units as Low Stock, flag items with more than 200 units as Overstock, create a reorder recommendation column, and build a manager summary sheet with tables and charts." |

Default range: **4-5** (reject tasks with difficulty <= 3).

## Task Categories

Don't just generate tasks around the app's primary function. A well-rounded task set must cover **all inspectable surfaces** of the app. Use the categories below as a checklist — for each app, generate tasks across every applicable category, not just category 1.

**1. Core content tasks** — The app's primary purpose: editing documents, browsing pages, editing images, writing code, playing media. These are the most obvious tasks and should be about half of it.

**2. Settings, preferences, and configuration** — Almost every app has user-configurable settings, and these make excellent RL tasks because they're precise and deterministically verifiable. Examples:
  - "Change the default font size to 14 in Sublime Text"
  - "Set Chrome's homepage to https://example.com"
  - "Enable word wrap in VS Code"
  - "Set VLC's default volume to 75%"
  - "Turn off auto-save in gedit"
  - "Change LibreOffice Calc's default number of sheets in new workbooks to 3"
  - "Set GIMP's default image format to PNG"
  - "Enable dark mode / change the theme in the app"
  - "Change the tab size from 4 spaces to 2 spaces"
  - "Disable telemetry / usage statistics reporting"
  - "Set the auto-save interval to 5 minutes"

**3. Keybindings and shortcuts** — Apps with customizable keybindings (VS Code, Sublime, terminal emulators):
  - "Add a keyboard shortcut Ctrl+Shift+T to open a new terminal in VS Code"
  - "Change the 'Go to Definition' keybinding to F12 in Sublime Text"
  - "Remove the default Ctrl+W keybinding in the editor"

**4. Extensions, plugins, and packages** — Installing, enabling, disabling, or configuring add-ons:
  - "Install the Python extension in VS Code"
  - "Install the Package Control package in Sublime Text"
  - "Enable a specific browser extension"
  - "Install the 'Material Theme' package and activate it"

**5. UI layout and window configuration** — Arranging the app's interface:
  - "Open the sidebar in VS Code and switch to the Explorer view"
  - "Split the editor into two side-by-side panes"
  - "Hide the toolbar in LibreOffice Writer"
  - "Set the sidebar width in PCManFM to show places panel"
  - "Switch to compact view in the file manager"
  - "Enable the minimap in the code editor"

**6. Bookmarks, favorites, and organization** — Managing saved locations and items:
  - "Bookmark the current page in Chrome under the 'Work' folder"
  - "Add /home/user/Projects to the file manager sidebar bookmarks"
  - "Pin a note in Obsidian"
  - "Create a bookmark bar folder called 'Research' and add three sites to it"

**7. File management and export/import** — Working with files across apps:
  - "Export the GIMP image as a JPEG with 85% quality"
  - "Save the LibreOffice spreadsheet as a CSV file"
  - "Create a symlink from ~/Desktop/shortcut to ~/Documents/report.odt"
  - "Change file permissions to 755 for a specific script"

**8. History and recent items** — Working with app history:
  - "Clear the browser history from the last hour"
  - "Open the most recently edited file in Sublime Text"
  - "Delete a specific site from Chrome's browsing history"

**9. Network, privacy, and security settings** — For apps with network features:
  - "Block third-party cookies in Firefox"
  - "Set Chrome to always use HTTPS"
  - "Configure a proxy server in the browser settings"
  - "Disable JavaScript in the browser"

**10. Project and workspace setup** — For IDEs and editors:
  - "Create a new VS Code workspace with two folders: ~/src and ~/tests"
  - "Add a build task to the VS Code workspace that runs 'python main.py'"
  - "Create a launch configuration for debugging Python in VS Code"
  - "Set the project-specific Python interpreter path"

**11. Multi-step cross-feature tasks** — Combine multiple categories into one task:
  - "Install the Markdown preview extension in VS Code, then open a .md file and split the editor to show preview alongside the source"
  - "Change Sublime Text's color scheme to Monokai, set font size to 13, and enable word wrap"
  - "Create a new spreadsheet, enter data in 3 columns, apply a formula, format the header row, and save as both .xlsx and .csv"

## App-Specific Task Ideas

When generating tasks, think about what's natural for each app category:

**Browsers (Chrome, Firefox, Brave, Opera):** Navigate, search, fill forms, manage tabs/bookmarks, download files, change privacy settings (cookies, tracking, do-not-track), configure homepage/startup pages, manage search engines, adjust appearance (font size, zoom, theme), change download location, manage extensions, configure proxy/network, clear history/cache.

**Office (LibreOffice Calc/Writer/Impress/Draw):** Enter data, create formulas, format cells/text, build charts, insert tables, create slides, mail merge, import/export. Also: change autocorrect settings, set default save format, configure spell-check language, adjust page margins/orientation, set print options, change default font, modify toolbar layout, enable/disable macro security.

**Graphics (GIMP, Inkscape, Krita, darktable):** Open images, resize/crop, apply filters, draw shapes, edit layers, export to different formats, adjust colors, create compositions. Also: change default canvas size, set grid/snap preferences, configure color management/ICC profiles, change export quality defaults, set tool options, adjust performance/memory settings.

**Audio (Audacity):** Record audio, import/export tracks, apply effects (amplify, normalize, noise reduction, fade in/out), split/join clips, mix multiple tracks, change sample rate/bit depth, configure recording preferences, set input/output devices, label regions, adjust spectral settings.

**Video Editing (Kdenlive, Shotcut):** Import clips, arrange on timeline, trim/split/cut, add transitions, apply effects/filters, add text overlays, adjust audio levels, export to various formats, configure project settings (resolution, frame rate), manage multiple tracks, set rendering profiles.

**Media Playback (VLC, OBS):** Open media files, adjust playback settings, create playlists, set up recording scenes, export. Also: change audio output device, set default volume, configure subtitle preferences (font, size, encoding), set playback speed, change video output module, configure OBS recording format/quality, set hotkeys.

**Music Notation (MuseScore 3):** Create scores, add notes/rests, set time signature/key signature, add instruments, write lyrics, add dynamics/articulations, transpose, export to PDF/MIDI/MusicXML, configure page layout, set playback tempo, add rehearsal marks.

**3D/CAD (FreeCAD, CloudCompare, RenderDoc):** FreeCAD: create/edit 3D models, set up sketches, apply constraints, boolean operations, export to STL/STEP, configure grid/snap, set units, manage workbenches. CloudCompare: import point clouds, compute normals, segment/filter, measure distances, set scalar fields, export. RenderDoc: capture/inspect GPU frames, analyze draw calls, inspect textures/shaders, configure capture settings.

**Game Development (Godot 4):** Create scenes/nodes, configure project settings (window size, input mappings, rendering), add scripts, set up physics, import assets, configure export presets, manage autoloads, set editor preferences, create resources.

**Reference Management (Zotero):** Create collections, add items, attach files, manage tags, configure sync settings, set citation styles, create bibliographies, organize with subcollections, set general/export preferences.

**Communication (Zoom):** Configure audio/video settings, set virtual background, change display name, configure recording preferences, set accessibility options, manage notification settings.

**Development (VS Code, Sublime, Eclipse):** Open projects, edit files, find/replace, run terminal commands, navigate code. Also: install/manage extensions, configure settings (tab size, word wrap, format-on-save, auto-close brackets, line numbers), customize keybindings, set up workspace/project settings, add build tasks, create launch/debug configurations, change theme/color scheme, configure linting rules.

**File Management (PCManFM):** Create folders, move/copy/rename files, change permissions, sort/filter views, open files with specific apps. Also: add/remove sidebar bookmarks, change default view mode (list/icon/compact), show/hide hidden files, change sort order, configure file associations.

**Other (Obsidian, draw.io, Thunderbird, galculator, gedit):** Create notes/diagrams/emails, organize, link, export. Also: Obsidian vault settings (editor mode, default note location, appearance), draw.io page settings and export options, Thunderbird account settings and mail composition defaults, gedit preferences (tab width, line numbers, highlight, word wrap, theme).

---

## Stage 1: Task Proposal

**Goal:** Generate diverse, difficult task proposals for the target app.

### CRITICAL: Do NOT read verifiers in this stage

**Do NOT read `verifiers/<app>/README.md`, `verifiers/<app>/<app>.py`, or any verifier file.** If you read the verifier first, you will unconsciously design tasks around what the verifier already supports, producing narrow, repetitive tasks (e.g., all layer tasks for Krita because the verifier only has layer endpoints). The whole point of this pipeline is to generate tasks based on what the app can do, not what the verifier can currently check. Verifier gaps are filled later in Stage 3 via endpoint extension.

### Procedure

1. **Read `task_generator/LESSONS.md`** for past design lessons to avoid repeating known mistakes.
2. **Review the Difficulty Scale, Task Categories, and App-Specific Task Ideas** sections above for the category checklist, difficulty scale, and app-specific ideas.
3. **Check `task_generator/tasks/`** for existing tasks for the same app. New tasks must be substantially different in both objective and the skills they test.
4. **Think about what a real user would do with this app.** What are the app's core features? What workflows would exercise different parts of the UI? What would be challenging but realistic? Design tasks from the perspective of app functionality, not verifiability.
5. **Generate task proposals** as a JSON array. Each proposal needs:
   - `id`: short snake_case identifier prefixed with app name (e.g., `gimp_resize_crop`)
   - `app`: target application name
   - `objective`: a clear goal statement describing the desired end-state, **not** step-by-step instructions
   - `input_requirements`: list of files needed (or empty list if none)
   - `success_criteria`: human-readable list of what must be true when done
   - `estimated_difficulty`: 1-5 rating

   Deliberately spread tasks across the difficulty scale (aim for a mix of levels 4 and 5) and across as many task categories as the app supports. Review the distribution before finalizing and rebalance if needed.

### Constraints

- Tasks must be completable by a GUI agent using mouse/keyboard in an E2B Ubuntu sandbox.
- Don't require internet access to unstable URLs. Use stable sites (httpbin.org, wikipedia.org) or local files.
- Be specific: name exact values, cell references, sheet names, filenames.
- Vary the tasks — don't generate 10 variations of the same action. If you notice all your tasks use the same app feature (e.g., all layer operations, all bookmark tasks), stop and rebalance across different features.
- Overshoot the requested count by ~30% since some will be rejected in later stages.
- **Do NOT think about how tasks will be verified.** That is Stage 3's job. A task that seems hard to verify might turn out to be trivially inspectable via a file or config — you don't know yet because you haven't read the verifier.

### Output

Save proposals to `task_generator/tasks/proposals_<app>.json`.

---

## Stage 2: Task Evaluation

**Goal:** Filter proposals on task quality, independent of verification. Still do NOT read verifiers — evaluation is about task quality only.

### Procedure

For each proposal, score on two axes:

#### 1. Task Complexity (accept: 4-5)

Does the task require meaningful multi-step interaction?

- **Reject if <= 3**: too simple, doesn't test agent capabilities.

See the Difficulty Scale section above.

#### 2. Data Generatability (accept: >= 4)

Can the input artifacts be synthesized by Claude Code?

| Score | Meaning |
|-------|---------|
| 1-2 | Needs real-world/proprietary data (API keys, auth, live feeds) |
| 3 | Needs complex domain data with tricky constraints |
| 4 | Simple structured data (CSV with names/numbers, config JSON, slides) |
| 5 | No input files needed, or trivially simple |

- **Reject if < 4**: we must be able to create all inputs ourselves.

### Output

For each proposal, record: scores, accepted/rejected, rejection reasons, suggestions for improvement.

Save to `task_generator/tasks/evaluated_<app>.json`:

```json
{
  "accepted": [ ...proposals with evaluation attached... ],
  "rejected": [ ...proposals with rejection reasons... ],
  "summary": {"total": 10, "accepted": 7, "rejected": 3}
}
```

### Retry Loop

If too few tasks pass, generate replacement proposals incorporating the rejection feedback. Retry up to 3 rounds. Include the rejection reasons so the same mistakes aren't repeated.

---

## Stage 3: Verification Matching & Finalization

**Goal:** For each accepted task, determine how to verify it, then produce the final `task.json`.

**NOW — and only now — read `verifiers/<app>/README.md`** to see what endpoints exist. This is the first time in the pipeline you look at the verifier.

### Procedure

For each accepted task, walk through this decision tree **in order**:

#### Step A: Direct match

Check if the task's success criteria can already be verified by existing verifier endpoints. If every criterion maps to an existing `check-*` command or can be expressed as an `eval` over existing endpoint output → **use those endpoints**. Proceed to finalization.

#### Step B: Extend the verifier

If no existing endpoint covers the task, but the outcome **is inspectable** through some channel (file on disk, config file, IPC/API, database, etc.) — follow the **[Endpoint Extension Workflow](ENDPOINT_EXTENSION.md)** to build, test, and add a new endpoint.

- If the endpoint is successfully implemented and tests pass → use it. Proceed to finalization.
- If the endpoint fails after retries → proceed to Step C.

#### Step C: Discard

If there is no viable verification channel for the task's main goal, discard it. Append an entry to `task_generator/tasks/unverifiable_<app>.md` with:
- Task ID and objective
- What verification was attempted
- Why it's not possible
- Date

### Finalization (for tasks that pass Steps A/B/C)

1. **Map each success criterion** to verification commands:
   - Prefer `check-*` commands with `key`/`expected`.
   - Use `eval` when no `check-*` fits (counting, computed comparisons).
   - Include a `description` for every check.

2. **Rewrite the task description** as a clear goal statement. The agent gets ONLY this text. State the desired end-state, not step-by-step GUI instructions. Include exact values (filenames, paths, dimensions, colors, cell references) so the goal is unambiguous, but let the agent figure out **how** to accomplish it.

3. **Add edge-case checks** the original criteria might have missed:
   - If task says "save the file" → verify the file exists at the expected path.
   - If task creates a named object (sheet, layer, channel) → verify the name exactly.
   - If task enters a formula → verify both the formula string AND the computed value.
   - If task exports a file → verify the output format and that the file is non-empty.

4. **Write the final `task.json`** to `task_generator/tasks/<task_id>/task.json` using the schema at the top of this document.

5. **Write the combined file** `task_generator/tasks/<app>_tasks.json` containing all final tasks as a JSON array.

---

## Stage 4: Environment Synthesis

**Goal:** Generate the input files each task needs.

### Procedure

For each finalized task with non-empty `input_requirements`:

1. Read the requirements (file types, descriptions, sandbox paths).
2. Generate the actual file content. Common file types:
   - **CSV**: Header row + 10-30 realistic rows. Standard comma-separated.
   - **XLSX (Excel)**: Preferred format for LibreOffice Calc tasks. Build using `openpyxl` (`pip install openpyxl`). Use `.xlsx` not `.ods` — it's more widely compatible and `openpyxl` is simpler than raw ZIP+XML.
   - **ODS**: Fallback if `.xlsx` is not suitable. Build using Python stdlib (zipfile + XML). Use the ODS builder pattern from `verifiers/libreoffice_calc/test_libreoffice_calc.py` as reference.
   - **Images (PNG/JPEG)**: Use Python's Pillow or stdlib to generate simple test images (solid colors, gradients, shapes).
   - **SVG**: Write XML directly (Inkscape tasks).
   - **Text/Markdown/JSON/Config**: Write content directly.
   - **Documents (ODT/ODP)**: Like ODS, these are ZIP+XML. Can be built with stdlib.
   - **Media files**: For VLC/Kdenlive tasks, note in the manifest that a sample file must be provided or downloaded in the sandbox at runtime.
3. Save files to `task_generator/tasks/<task_id>/env/`.
4. Save a manifest: `task_generator/tasks/<task_id>/env_manifest.json`:

```json
{
  "task_id": "the_id",
  "files": [
    {"filename": "data.csv", "sandbox_path": "/home/user/Documents/data.csv", "type": "csv"},
    {"filename": "photo.png", "sandbox_path": "/home/user/Pictures/photo.png", "type": "png"}
  ]
}
```

### Key Rules

- Content must be consistent with the task description (matching column names, expected values, filenames, etc.).
- If the task says "the sum of column B should be 550", make sure the numbers actually sum to 550.
- For spreadsheets, prefer `.xlsx` format built with `openpyxl`. For ODS/ODT/ODP files, use the ZIP+XML approach (no external deps needed).
- For images, prefer generating them programmatically (simple shapes, solid fills) over needing real photographs.

### Required Workflow: Research → Generate → Verify

Do **not** stop after writing a generator script. Every env file must be actually produced on disk and confirmed to open/parse correctly.

1. **Research first.** Before writing the generator, search the repo and the web for the correct file format, library API, and any existing examples. Check `verifiers/<app>/` for reference builders if there is any(e.g., the ODS builder in `verifiers/libreoffice_calc/test_libreoffice_calc.py`) and reuse patterns that are already known to work.
2. **Actually generate the file.** Run the generator script so the real artifact lands in `task_generator/tasks/<task_id>/env/`. A script that was written but never executed does not count.
3. **Verify the file works.** After generation, confirm the file is valid:
   - Check it exists and has required content.
   - Parse/open it with the same library or tool the task will use (e.g., reopen the `.xlsx` with `openpyxl`, parse the SVG, load the PNG with Pillow, unzip and inspect an ODS).
   - For content constraints encoded in the task (specific cell values, row counts, sums, image dimensions), assert them programmatically.
   - If verification fails, fix the generator and regenerate.
4. **Record what you learned.** If you had to debug and fix a broken generator, append a short lesson to `task_generator/LESSONS.md`. Skip this only when the generator worked on the first try.

---

## Running the Full Pipeline

When the user says something like "generate 10 tasks for gimp":

1. **Stage 1**: Generate 13+ proposals (overshoot by ~30%)
2. **Stage 2**: Evaluate on complexity + data generatability. If too few pass, retry with feedback (up to 3 rounds)
3. **Stage 3**: For each accepted task, match to verifier (direct match → extend → discard). Produce final `task.json` files.
4. **Stage 4**: Synthesize environment files for all finalized tasks

Report a summary at the end: how many proposed, evaluated-accepted, verified/adapted/extended/discarded, and the final task list.
