# Eclipse IDE Verifier

Programmatic state inspection for Eclipse IDE in an E2B desktop sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Verification Channels

| Channel | What it covers | How |
|---------|---------------|-----|
| `.project` XML | Project name, natures, builders, linked resources | `xml.etree.ElementTree` |
| `.classpath` XML | Source dirs, libraries, containers, output dir | `xml.etree.ElementTree` |
| `.settings/` prefs | Compiler level, formatter, encoding, etc. | Java properties parsing |
| Workspace `.metadata/` | Workspace-level preferences and plugin state | Directory listing |
| File system | Source files, build output in `bin/` | `os.walk` / `Path.exists` |

**Primary approach:** Parse XML project/workspace files. Check build artifacts on disk.

## Usage from Check Agent

```python
import json
from e2b_desktop import Sandbox

sandbox = Sandbox.create(template="desktop-all-apps")

# --- List projects in a workspace ---
result = sandbox.commands.run(
    "python3 /home/user/verifiers/eclipse.py projects /home/user/workspace"
)
projects = json.loads(result.stdout)

# --- Check if a Java project exists ---
result = sandbox.commands.run(
    "python3 /home/user/verifiers/eclipse.py check-project-exists "
    "/home/user/workspace MyProject"
)
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0

# --- Check project nature ---
result = sandbox.commands.run(
    "python3 /home/user/verifiers/eclipse.py check-project-nature "
    "/home/user/workspace/MyProject org.eclipse.jdt.core.javanature"
)
data = json.loads(result.stdout)

# --- Check classpath entry ---
result = sandbox.commands.run(
    "python3 /home/user/verifiers/eclipse.py check-classpath-entry "
    "/home/user/workspace/MyProject src src"
)
data = json.loads(result.stdout)
assert data["exists"]

# --- Check a project setting ---
result = sandbox.commands.run(
    "python3 /home/user/verifiers/eclipse.py check-setting "
    "/home/user/workspace/MyProject org.eclipse.jdt.core.prefs "
    "org.eclipse.jdt.core.compiler.source 17"
)
data = json.loads(result.stdout)
assert data["matches"]
```

## Commands

### Query (read state)

| Command | Args | Description |
|---------|------|-------------|
| `projects` | `<workspace_path>` | List all projects in workspace |
| `project-info` | `<project_path>` | Parse .project (name, natures, builders, linked resources) |
| `classpath` | `<project_path>` | Parse .classpath (source dirs, libs, output) |
| `project-settings` | `<project_path>` | List .settings/ files and their contents |
| `source-files` | `<project_path>` | List Java/C/Python source files |
| `build-output` | `<project_path>` | List compiled artifacts in bin/build dirs |
| `workspace-info` | `<workspace_path>` | Workspace metadata |

### Check (boolean verification)

| Command | Args | Primary key |
|---------|------|------------|
| `check-file-exists` | `<path>` | `exists` |
| `check-project-exists` | `<workspace_path> <project_name>` | `exists` |
| `check-project-nature` | `<project_path> <nature>` | `has_nature` |
| `check-classpath-entry` | `<project_path> <kind> <path>` | `exists` |
| `check-source-file-exists` | `<project_path> <relative_path>` | `exists` |
| `check-build-output-exists` | `<project_path> <relative_path>` | `exists` |
| `check-project-count` | `<workspace_path> <count>` | `matches` |
| `check-setting` | `<project_path> <settings_file> <key> <value>` | `matches` |
| `check-workspace-pref` | `<workspace> <prefs_file> <key> <value>` | `matches` |
| `check-workspace-pref-contains` | `<workspace> <prefs_file> <key> <substring>` | `contains` |
| `get-launch-config` | `<workspace> <name>` | attributes dict |
| `check-launch-config` | `<workspace> <name> <type>` | `type_matches` |
| `check-launch-attribute` | `<workspace> <name> <key> <value>` | `matches` |
| `check-launch-attribute-contains` | `<workspace> <name> <key> <substring>` | `contains` |
| `get-breakpoints` | `<workspace>` | list of breakpoints |
| `check-line-breakpoint` | `<workspace> <type> <line>` | `exists` |
| `check-exception-breakpoint` | `<workspace> <class>` | `exists` |
| `get-working-sets` | `<workspace>` | list of working sets |
| `check-working-set` | `<workspace> <name> <edit_page_id>` | `page_matches` |
| `check-working-set-member` | `<workspace> <name> <member_substring>` | `contains` |
| `check-git-repo` | `<project_path>` | `head_exists` |
| `check-git-commit-message` | `<project_path> <substring>` | `contains` |
| `check-git-file-tracked` | `<project_path> <relative_path>` | `tracked` |
| `check-file-contains` | `<path> <substring>` | `contains` |
| `check-xml-attribute` | `<path> <xpath> <attr> <value>` | `matches` |

All `check-*` commands return a dict with a primary boolean key that maps directly to a reward signal.

## Eclipse Project Structure

```
workspace/
  .metadata/                    # Workspace settings
    .plugins/
      org.eclipse.core.runtime/
        .settings/              # Workspace prefs
  MyProject/
    .project                    # Project definition XML
    .classpath                  # Build path XML (Java projects)
    .settings/                  # Per-project settings
      org.eclipse.jdt.core.prefs
    src/                        # Source directory
      com/example/Main.java
    bin/                        # Build output
      com/example/Main.class
    lib/                        # External libraries
```

## Common Nature IDs

| Nature | Language |
|--------|----------|
| `org.eclipse.jdt.core.javanature` | Java |
| `org.eclipse.cdt.core.cnature` | C |
| `org.eclipse.cdt.core.ccnature` | C++ |
| `org.eclipse.pde.PluginNature` | Eclipse Plugin |
| `org.eclipse.pydev.pythonNature` | Python (PyDev) |
| `org.eclipse.wst.jsdt.core.jsNature` | JavaScript |

## Headless Builds

Eclipse supports headless builds for CI/verification:

```bash
/opt/eclipse/eclipse -nosplash \
    -application org.eclipse.cdt.managedbuilder.core.headlessbuild \
    -data /home/user/workspace \
    -build all
```

## Running Tests

```bash
python verifiers/eclipse/test_eclipse.py
```

Tests create a synthetic workspace in the sandbox with Java and empty projects, then verify all query and check endpoints against known state.
