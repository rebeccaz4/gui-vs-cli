"""
Eclipse Verifier -- programmatic state inspection for Eclipse IDE in E2B sandbox.

Verification channels (in order of preference):
  1. XML project files -- .project, .classpath define project structure and build paths
  2. Settings files -- .settings/ per-project XML/prefs for compiler, formatter, etc.
  3. Workspace metadata -- <workspace>/.metadata/ for workspace-level config
  4. File-based checks -- source files, build output in bin/ directories

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/eclipse.py projects /home/user/workspace")
    sandbox.commands.run("python3 /home/user/verifiers/eclipse.py project-info /home/user/workspace/MyProject")
    sandbox.commands.run("python3 /home/user/verifiers/eclipse.py check-project-nature /home/user/workspace/MyProject org.eclipse.jdt.core.javanature")

Usage from Python (inside sandbox or via E2B):
    from verifiers.eclipse import EclipseVerifier
    v = EclipseVerifier()
    projects = v.get_projects("/home/user/workspace")
    info = v.get_project_info("/home/user/workspace/MyProject")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Eclipse at /opt/eclipse/eclipse (for headless builds)
  - xml.etree.ElementTree (standard library)
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ECLIPSE_BIN = "/opt/eclipse/eclipse"

# Common Eclipse project natures
KNOWN_NATURES = {
    "org.eclipse.jdt.core.javanature": "Java",
    "org.eclipse.cdt.core.cnature": "C",
    "org.eclipse.cdt.core.ccnature": "C++",
    "org.eclipse.pde.PluginNature": "Plugin",
    "org.eclipse.pydev.pythonNature": "Python",
    "org.eclipse.wst.jsdt.core.jsNature": "JavaScript",
}

# Source file extensions by language
SOURCE_EXTENSIONS = {
    ".java", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp",
    ".py", ".js", ".ts", ".xml", ".properties",
}


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _parse_xml(path: str) -> ET.Element | None:
    """Parse an XML file and return root element, or None on failure."""
    try:
        tree = ET.parse(path)
        return tree.getroot()
    except (ET.ParseError, FileNotFoundError, PermissionError):
        return None


def _xml_to_dict(element: ET.Element) -> dict:
    """Convert an XML element to a simple dict representation."""
    result = {"tag": element.tag}
    if element.attrib:
        result["attrib"] = dict(element.attrib)
    if element.text and element.text.strip():
        result["text"] = element.text.strip()
    children = []
    for child in element:
        children.append(_xml_to_dict(child))
    if children:
        result["children"] = children
    return result


# ---------------------------------------------------------------------------
# EclipseVerifier class
# ---------------------------------------------------------------------------

class EclipseVerifier:
    """Stateless verifier -- each method call is independent."""

    # === Query: Project structure ===

    def get_projects(self, workspace_path: str) -> list[dict]:
        """List all projects in an Eclipse workspace.

        Scans for directories containing a .project file.

        Example return:
        [
            {"name": "MyProject", "path": "/home/user/workspace/MyProject",
             "has_classpath": true, "has_settings": true}
        ]
        """
        ws = Path(workspace_path)
        if not ws.is_dir():
            return [{"error": f"Workspace directory not found: {workspace_path}"}]

        projects = []
        for item in sorted(ws.iterdir()):
            if not item.is_dir():
                continue
            project_file = item / ".project"
            if not project_file.exists():
                continue

            name = item.name
            # Try to get name from .project XML
            root = _parse_xml(str(project_file))
            if root is not None:
                name_elem = root.find("name")
                if name_elem is not None and name_elem.text:
                    name = name_elem.text

            projects.append({
                "name": name,
                "path": str(item),
                "has_classpath": (item / ".classpath").exists(),
                "has_settings": (item / ".settings").is_dir(),
            })

        return projects

    def get_project_info(self, project_path: str) -> dict:
        """Parse .project file for a project.

        Returns project name, natures, builders, linked resources, and comments.

        Example return:
        {
            "name": "MyProject",
            "comment": "",
            "natures": ["org.eclipse.jdt.core.javanature"],
            "builders": ["org.eclipse.jdt.core.javabuilder"],
            "linked_resources": []
        }
        """
        proj_file = Path(project_path) / ".project"
        if not proj_file.exists():
            return {"error": f".project not found at {proj_file}"}

        root = _parse_xml(str(proj_file))
        if root is None:
            return {"error": f"Failed to parse {proj_file}"}

        name_elem = root.find("name")
        comment_elem = root.find("comment")

        # Natures
        natures = []
        natures_elem = root.find("natures")
        if natures_elem is not None:
            for nature in natures_elem.findall("nature"):
                if nature.text:
                    natures.append(nature.text)

        # Builders
        builders = []
        build_spec = root.find("buildSpec")
        if build_spec is not None:
            for cmd in build_spec.findall("buildCommand"):
                name_el = cmd.find("name")
                if name_el is not None and name_el.text:
                    builders.append(name_el.text)

        # Linked resources
        linked = []
        linked_elem = root.find("linkedResources")
        if linked_elem is not None:
            for link in linked_elem.findall("link"):
                link_info = {}
                for child in link:
                    if child.text:
                        link_info[child.tag] = child.text
                linked.append(link_info)

        return {
            "name": name_elem.text if name_elem is not None and name_elem.text else "",
            "comment": comment_elem.text if comment_elem is not None and comment_elem.text else "",
            "natures": natures,
            "nature_labels": [KNOWN_NATURES.get(n, n) for n in natures],
            "builders": builders,
            "linked_resources": linked,
        }

    def get_classpath(self, project_path: str) -> dict:
        """Parse .classpath file for a project.

        Returns classpath entries grouped by kind (src, lib, con, output).

        Example return:
        {
            "entries": [
                {"kind": "src", "path": "src"},
                {"kind": "con", "path": "org.eclipse.jdt.launching.JRE_CONTAINER"},
                {"kind": "output", "path": "bin"}
            ],
            "source_dirs": ["src"],
            "output_dir": "bin",
            "libraries": [],
            "containers": ["org.eclipse.jdt.launching.JRE_CONTAINER"]
        }
        """
        cp_file = Path(project_path) / ".classpath"
        if not cp_file.exists():
            return {"error": f".classpath not found at {cp_file}"}

        root = _parse_xml(str(cp_file))
        if root is None:
            return {"error": f"Failed to parse {cp_file}"}

        entries = []
        source_dirs = []
        libraries = []
        containers = []
        output_dir = None

        for entry in root.findall("classpathentry"):
            kind = entry.get("kind", "")
            path = entry.get("path", "")
            entry_info = {"kind": kind, "path": path}

            # Optional attributes
            for attr in ("sourcepath", "excluding", "including", "combineaccessrules"):
                val = entry.get(attr)
                if val:
                    entry_info[attr] = val

            # Access rules and attributes children
            access_rules = []
            for ar in entry.findall(".//accessrule"):
                access_rules.append({"kind": ar.get("kind", ""), "pattern": ar.get("pattern", "")})
            if access_rules:
                entry_info["access_rules"] = access_rules

            attrs = []
            for a in entry.findall(".//attribute"):
                attrs.append({"name": a.get("name", ""), "value": a.get("value", "")})
            if attrs:
                entry_info["attributes"] = attrs

            entries.append(entry_info)

            if kind == "src":
                source_dirs.append(path)
            elif kind == "lib":
                libraries.append(path)
            elif kind == "con":
                containers.append(path)
            elif kind == "output":
                output_dir = path

        return {
            "entries": entries,
            "source_dirs": source_dirs,
            "output_dir": output_dir,
            "libraries": libraries,
            "containers": containers,
        }

    def get_project_settings(self, project_path: str) -> dict:
        """List .settings/ files and parse their contents.

        Eclipse stores per-project settings as Java .prefs files or XML.

        Example return:
        {
            "settings_dir": "/home/user/workspace/MyProject/.settings",
            "files": {
                "org.eclipse.jdt.core.prefs": {"key": "value", ...},
                "org.eclipse.core.resources.prefs": {"key": "value", ...}
            }
        }
        """
        settings_dir = Path(project_path) / ".settings"
        if not settings_dir.is_dir():
            return {"error": f".settings directory not found at {settings_dir}"}

        files = {}
        for f in sorted(settings_dir.iterdir()):
            if not f.is_file():
                continue
            try:
                content = f.read_text(errors="replace")
            except (PermissionError, OSError):
                files[f.name] = {"error": "Cannot read file"}
                continue

            if f.suffix == ".prefs":
                # Java properties format: key=value lines
                props = {}
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, _, v = line.partition("=")
                        props[k.strip()] = v.strip()
                files[f.name] = props
            elif f.suffix == ".xml":
                root = _parse_xml(str(f))
                if root is not None:
                    files[f.name] = _xml_to_dict(root)
                else:
                    files[f.name] = {"raw": content[:2000]}
            else:
                files[f.name] = {"raw": content[:2000]}

        return {
            "settings_dir": str(settings_dir),
            "files": files,
        }

    def get_source_files(self, project_path: str) -> dict:
        """List source files in a project (Java, C, Python, etc.).

        Walks the project directory, excluding hidden dirs, bin/, build/.

        Example return:
        {
            "count": 5,
            "files": [
                {"path": "src/com/example/Main.java", "size": 1234},
                ...
            ]
        }
        """
        proj = Path(project_path)
        if not proj.is_dir():
            return {"error": f"Project directory not found: {project_path}"}

        skip_dirs = {".settings", ".git", "bin", "build", "target", ".metadata", "__pycache__"}
        files = []

        for root_dir, dirs, filenames in os.walk(proj):
            # Skip hidden and build directories
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            rel_root = Path(root_dir).relative_to(proj)

            for fname in sorted(filenames):
                ext = Path(fname).suffix.lower()
                if ext in SOURCE_EXTENSIONS:
                    rel_path = str(rel_root / fname) if str(rel_root) != "." else fname
                    full_path = Path(root_dir) / fname
                    try:
                        size = full_path.stat().st_size
                    except OSError:
                        size = -1
                    files.append({"path": rel_path, "size": size})

        return {"count": len(files), "files": files}

    def get_build_output(self, project_path: str) -> dict:
        """List compiled artifacts in bin/ and build/ directories.

        Example return:
        {
            "output_dirs_found": ["bin"],
            "count": 3,
            "files": [
                {"path": "bin/com/example/Main.class", "size": 567},
                ...
            ]
        }
        """
        proj = Path(project_path)
        if not proj.is_dir():
            return {"error": f"Project directory not found: {project_path}"}

        output_dirs = []
        files = []

        for dirname in ("bin", "build", "target", "out"):
            out_dir = proj / dirname
            if not out_dir.is_dir():
                continue
            output_dirs.append(dirname)

            for root_dir, _, filenames in os.walk(out_dir):
                rel_root = Path(root_dir).relative_to(proj)
                for fname in sorted(filenames):
                    rel_path = str(rel_root / fname)
                    full_path = Path(root_dir) / fname
                    try:
                        size = full_path.stat().st_size
                    except OSError:
                        size = -1
                    files.append({"path": rel_path, "size": size})

        return {
            "output_dirs_found": output_dirs,
            "count": len(files),
            "files": files,
        }

    def get_workspace_info(self, workspace_path: str) -> dict:
        """Get workspace metadata from .metadata/ directory.

        Returns info about the workspace: preferences, recent projects, etc.

        Example return:
        {
            "workspace_path": "/home/user/workspace",
            "has_metadata": true,
            "project_count": 3,
            "projects": ["MyProject", ...],
            "metadata_files": [".metadata/.plugins/...", ...]
        }
        """
        ws = Path(workspace_path)
        if not ws.is_dir():
            return {"error": f"Workspace directory not found: {workspace_path}"}

        metadata_dir = ws / ".metadata"
        has_metadata = metadata_dir.is_dir()

        # Count projects
        projects = self.get_projects(workspace_path)
        if projects and isinstance(projects[0], dict) and "error" in projects[0]:
            project_names = []
        else:
            project_names = [p["name"] for p in projects]

        result = {
            "workspace_path": str(ws),
            "has_metadata": has_metadata,
            "project_count": len(project_names),
            "projects": project_names,
        }

        if has_metadata:
            # List top-level metadata contents
            try:
                meta_items = []
                for item in sorted(metadata_dir.iterdir()):
                    meta_items.append(item.name)
                result["metadata_contents"] = meta_items
            except (PermissionError, OSError):
                result["metadata_contents"] = []

            # Check for workspace prefs
            prefs_dir = metadata_dir / ".plugins" / "org.eclipse.core.runtime" / ".settings"
            if prefs_dir.is_dir():
                try:
                    result["workspace_prefs_files"] = [f.name for f in sorted(prefs_dir.iterdir())]
                except (PermissionError, OSError):
                    pass

        return result

    # === Check: Boolean verification ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists at the given path.

        Example:
            v.check_file_exists("/home/user/workspace/MyProject/src/Main.java")
            => {"exists": true, "size": 1234, "is_file": true}
        """
        p = Path(path)
        exists = p.exists()
        result = {"exists": exists}
        if exists:
            result["is_file"] = p.is_file()
            result["is_dir"] = p.is_dir()
            try:
                result["size"] = p.stat().st_size
            except OSError:
                pass
        return result

    def check_project_exists(self, workspace_path: str, project_name: str) -> dict:
        """Check if a project directory with .project file exists in workspace.

        Example:
            v.check_project_exists("/home/user/workspace", "MyProject")
            => {"exists": true, "path": "/home/user/workspace/MyProject",
                "has_project_file": true}
        """
        proj_dir = Path(workspace_path) / project_name
        proj_file = proj_dir / ".project"

        exists = proj_dir.is_dir() and proj_file.exists()
        result = {
            "exists": exists,
            "path": str(proj_dir),
            "has_project_file": proj_file.exists(),
        }

        if exists:
            # Verify name in .project matches
            root = _parse_xml(str(proj_file))
            if root is not None:
                name_elem = root.find("name")
                if name_elem is not None and name_elem.text:
                    result["project_name"] = name_elem.text
                    result["name_matches"] = name_elem.text == project_name

        return result

    def check_project_nature(self, project_path: str, nature: str) -> dict:
        """Check if a project has a specific nature.

        Example:
            v.check_project_nature("/home/user/workspace/MyProject",
                                   "org.eclipse.jdt.core.javanature")
            => {"has_nature": true, "all_natures": ["org.eclipse.jdt.core.javanature"]}
        """
        info = self.get_project_info(project_path)
        if "error" in info:
            return info

        natures = info.get("natures", [])
        return {
            "has_nature": nature in natures,
            "nature_label": KNOWN_NATURES.get(nature, nature),
            "all_natures": natures,
        }

    def check_classpath_entry(self, project_path: str, kind: str, path: str) -> dict:
        """Check if a classpath entry with given kind and path exists.

        kind: src, lib, con, output

        Example:
            v.check_classpath_entry("/home/user/workspace/MyProject", "src", "src")
            => {"exists": true, "entry": {"kind": "src", "path": "src"}}
        """
        cp = self.get_classpath(project_path)
        if "error" in cp:
            return cp

        for entry in cp.get("entries", []):
            if entry.get("kind") == kind and entry.get("path") == path:
                return {"exists": True, "entry": entry}

        return {
            "exists": False,
            "searched_kind": kind,
            "searched_path": path,
            "available_entries": cp.get("entries", []),
        }

    def check_source_file_exists(self, project_path: str, relative_path: str) -> dict:
        """Check if a source file exists at the relative path within the project.

        Example:
            v.check_source_file_exists("/home/user/workspace/MyProject",
                                       "src/com/example/Main.java")
            => {"exists": true, "size": 1234, "path": "..."}
        """
        full_path = Path(project_path) / relative_path
        exists = full_path.is_file()
        result = {
            "exists": exists,
            "path": str(full_path),
        }
        if exists:
            try:
                result["size"] = full_path.stat().st_size
            except OSError:
                pass
        return result

    def check_build_output_exists(self, project_path: str, relative_path: str) -> dict:
        """Check if a compiled file exists at the relative path within the project.

        Example:
            v.check_build_output_exists("/home/user/workspace/MyProject",
                                        "bin/com/example/Main.class")
            => {"exists": true, "size": 567}
        """
        full_path = Path(project_path) / relative_path
        exists = full_path.is_file()
        result = {
            "exists": exists,
            "path": str(full_path),
        }
        if exists:
            try:
                result["size"] = full_path.stat().st_size
            except OSError:
                pass
        return result

    def check_project_count(self, workspace_path: str, count: int) -> dict:
        """Check if workspace has exactly the expected number of projects.

        Example:
            v.check_project_count("/home/user/workspace", 3)
            => {"matches": true, "expected": 3, "actual": 3, "projects": [...]}
        """
        projects = self.get_projects(workspace_path)
        if projects and isinstance(projects[0], dict) and "error" in projects[0]:
            return projects[0]

        actual = len(projects)
        return {
            "matches": actual == count,
            "expected": count,
            "actual": actual,
            "projects": [p["name"] for p in projects],
        }

    # === Workspace-level preference checks ===

    def check_workspace_pref(self, workspace_path: str, prefs_file: str,
                              key: str, value: str) -> dict:
        """Check a workspace-level pref at
        .metadata/.plugins/org.eclipse.core.runtime/.settings/<prefs_file>.

        Compares key=value as strings (exact match).
        """
        prefs_path = (Path(workspace_path) / ".metadata" / ".plugins"
                      / "org.eclipse.core.runtime" / ".settings" / prefs_file)
        if not prefs_path.is_file():
            return {"error": f"Prefs file not found: {prefs_path}"}
        try:
            content = prefs_path.read_text(errors="replace")
        except Exception as e:
            return {"error": str(e)}
        props = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()
        actual = props.get(key)
        return {
            "matches": actual == value,
            "expected": value,
            "actual": actual,
            "key": key,
            "prefs_file": prefs_file,
        }

    def check_workspace_pref_contains(self, workspace_path: str, prefs_file: str,
                                       key: str, substring: str) -> dict:
        """Check a workspace pref's value CONTAINS a substring (useful for
        custom_code_templates / custom_templates XML-in-value prefs)."""
        prefs_path = (Path(workspace_path) / ".metadata" / ".plugins"
                      / "org.eclipse.core.runtime" / ".settings" / prefs_file)
        if not prefs_path.is_file():
            return {"error": f"Prefs file not found: {prefs_path}"}
        try:
            content = prefs_path.read_text(errors="replace")
        except Exception as e:
            return {"error": str(e)}
        props = {}
        # Handle escaped = via properties-style; but Eclipse uses simple k=v
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()
        actual = props.get(key, "")
        # Unescape common Java-properties escapes
        unescaped = actual.encode("utf-8").decode("unicode_escape", errors="replace") if actual else ""
        found = substring in actual or substring in unescaped
        return {
            "contains": found,
            "substring": substring,
            "key": key,
            "prefs_file": prefs_file,
            "value_length": len(actual),
        }

    # === Launch configuration checks ===

    def _find_launch_file(self, workspace_path: str, name: str) -> Path | None:
        """Find a .launch file by name. Searches:
          - <workspace>/.metadata/.plugins/org.eclipse.debug.core/.launches/<name>.launch
          - Any <project>/.launches/<name>.launch under workspace
        """
        ws = Path(workspace_path)
        candidates = [
            ws / ".metadata" / ".plugins" / "org.eclipse.debug.core" / ".launches" / f"{name}.launch",
        ]
        for p in candidates:
            if p.is_file():
                return p
        # Search project-local .launches/
        if ws.is_dir():
            for proj in ws.iterdir():
                if not proj.is_dir():
                    continue
                f = proj / ".launches" / f"{name}.launch"
                if f.is_file():
                    return f
        return None

    def get_launch_config(self, workspace_path: str, name: str) -> dict:
        """Parse a .launch XML configuration into its stringAttribute/
        booleanAttribute/intAttribute key-value map.
        """
        path = self._find_launch_file(workspace_path, name)
        if path is None:
            return {"error": f"Launch config '{name}' not found"}
        root = _parse_xml(str(path))
        if root is None:
            return {"error": f"Failed to parse {path}"}
        attrs = {}
        for el in root.iter():
            k = el.get("key")
            v = el.get("value")
            if k is not None:
                attrs[k] = v
        return {
            "path": str(path),
            "type": root.get("type", ""),
            "attributes": attrs,
        }

    def check_launch_config(self, workspace_path: str, name: str,
                             launch_type: str) -> dict:
        """Check a launch config exists with the expected type attribute."""
        info = self.get_launch_config(workspace_path, name)
        if "error" in info:
            return {"exists": False, "error": info["error"]}
        return {
            "exists": True,
            "type_matches": info["type"] == launch_type,
            "type": info["type"],
            "expected_type": launch_type,
        }

    def check_launch_attribute(self, workspace_path: str, name: str,
                                key: str, value: str) -> dict:
        """Check a launch config attribute equals value (string compare)."""
        info = self.get_launch_config(workspace_path, name)
        if "error" in info:
            return {"matches": False, "error": info["error"]}
        actual = info["attributes"].get(key)
        return {
            "matches": actual == value,
            "key": key,
            "expected": value,
            "actual": actual,
        }

    def check_launch_attribute_contains(self, workspace_path: str, name: str,
                                         key: str, substring: str) -> dict:
        """Check a launch config attribute's value contains substring."""
        info = self.get_launch_config(workspace_path, name)
        if "error" in info:
            return {"contains": False, "error": info["error"]}
        actual = info["attributes"].get(key, "") or ""
        return {
            "contains": substring in actual,
            "key": key,
            "substring": substring,
            "actual": actual,
        }

    # === Breakpoint checks ===

    def get_breakpoints(self, workspace_path: str) -> dict:
        """Parse the workspace breakpoints file.

        Eclipse stores breakpoints at
        <workspace>/.metadata/.plugins/org.eclipse.debug.core/.bp_file  (binary)
        or at .../.launches/... — but the reliable channel is the export file
        at <workspace>/.metadata/.plugins/org.eclipse.debug.core/breakpoints.xml
        if the user exports, or .markers per-resource.

        For our verifiable tasks we require the agent (or test fixture) to
        produce a breakpoints.xml export at
        <workspace>/breakpoints.xml — this is the standard File > Export >
        Breakpoints location that task descriptions can reference.
        """
        ws = Path(workspace_path)
        candidates = [
            ws / "breakpoints.xml",
            ws / ".metadata" / ".plugins" / "org.eclipse.debug.core" / "breakpoints.xml",
        ]
        path = None
        for p in candidates:
            if p.is_file():
                path = p
                break
        if path is None:
            return {"error": "No breakpoints.xml export found"}
        root = _parse_xml(str(path))
        if root is None:
            return {"error": f"Failed to parse {path}"}
        breakpoints = []
        for bp in root.iter("breakpoint"):
            marker = bp.find("marker")
            entry = dict(bp.attrib)
            if marker is not None:
                entry["type"] = marker.get("type", "")
                attrs = {}
                for a in marker.findall("attrib"):
                    attrs[a.get("name", "")] = a.get("value", "")
                entry["attribs"] = attrs
            breakpoints.append(entry)
        return {"path": str(path), "count": len(breakpoints), "breakpoints": breakpoints}

    def check_line_breakpoint(self, workspace_path: str, type_name: str,
                               line: int) -> dict:
        """Check a Java line breakpoint exists for type at given line."""
        info = self.get_breakpoints(workspace_path)
        if "error" in info:
            return {"exists": False, "error": info["error"]}
        for bp in info["breakpoints"]:
            attrs = bp.get("attribs", {})
            if attrs.get("org.eclipse.jdt.debug.core.typeName") == type_name \
               and attrs.get("lineNumber") == str(line):
                return {"exists": True, "type_name": type_name, "line": line, "attribs": attrs}
        return {"exists": False, "type_name": type_name, "line": line}

    def check_exception_breakpoint(self, workspace_path: str,
                                    exception_class: str) -> dict:
        """Check a Java exception breakpoint exists for the given exception class."""
        info = self.get_breakpoints(workspace_path)
        if "error" in info:
            return {"exists": False, "error": info["error"]}
        for bp in info["breakpoints"]:
            attrs = bp.get("attribs", {})
            if attrs.get("org.eclipse.jdt.debug.core.typeName") == exception_class \
               and bp.get("type", "").endswith("javaExceptionBreakpointMarker"):
                return {"exists": True, "exception": exception_class, "attribs": attrs}
            if attrs.get("exceptionTypeName") == exception_class:
                return {"exists": True, "exception": exception_class, "attribs": attrs}
        return {"exists": False, "exception": exception_class}

    # === Working set checks ===

    def _workbench_xmi_paths(self, workspace_path: str) -> list[Path]:
        """Candidate locations where working sets are persisted."""
        ws = Path(workspace_path)
        return [
            ws / ".metadata" / ".plugins" / "org.eclipse.ui.workbench" / "workingsets.xml",
            ws / ".metadata" / ".plugins" / "org.eclipse.e4.workbench" / "workbench.xmi",
            ws / "workingsets.xml",
        ]

    def get_working_sets(self, workspace_path: str) -> dict:
        """Parse workingsets.xml into a list of working sets."""
        for path in self._workbench_xmi_paths(workspace_path):
            if not path.is_file():
                continue
            root = _parse_xml(str(path))
            if root is None:
                continue
            sets = []
            for ws_elem in root.iter("workingSet"):
                members = []
                for item in ws_elem.findall("item"):
                    members.append(item.get("elementID") or item.get("factoryID") or
                                   item.get("path") or "")
                sets.append({
                    "name": ws_elem.get("name", ""),
                    "editPageId": ws_elem.get("editPageId", ""),
                    "id": ws_elem.get("id", ""),
                    "label": ws_elem.get("label", ""),
                    "members": members,
                })
            return {"path": str(path), "count": len(sets), "working_sets": sets}
        return {"error": "No workingsets.xml found"}

    def check_working_set(self, workspace_path: str, name: str,
                           edit_page_id: str) -> dict:
        """Check a working set exists with the given name and edit page id."""
        info = self.get_working_sets(workspace_path)
        if "error" in info:
            return {"exists": False, "error": info["error"]}
        for ws in info["working_sets"]:
            if ws["name"] == name:
                return {
                    "exists": True,
                    "page_matches": ws["editPageId"] == edit_page_id,
                    "editPageId": ws["editPageId"],
                    "members": ws["members"],
                    "member_count": len(ws["members"]),
                }
        return {"exists": False, "name": name}

    def check_working_set_member(self, workspace_path: str, name: str,
                                  member_substring: str) -> dict:
        """Check working set has a member whose descriptor contains substring."""
        info = self.get_working_sets(workspace_path)
        if "error" in info:
            return {"contains": False, "error": info["error"]}
        for ws in info["working_sets"]:
            if ws["name"] == name:
                for m in ws["members"]:
                    if member_substring in (m or ""):
                        return {"contains": True, "member": m, "substring": member_substring}
                return {"contains": False, "substring": member_substring,
                        "available_members": ws["members"]}
        return {"contains": False, "error": f"Working set '{name}' not found"}

    # === Git / EGit checks ===

    def check_git_repo(self, project_path: str) -> dict:
        """Check the project directory has a git repository (either .git dir or .git file)."""
        p = Path(project_path) / ".git"
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        head_exists = (p / "HEAD").is_file() if is_dir else False
        return {"exists": exists, "is_dir": is_dir, "head_exists": head_exists,
                "path": str(p)}

    def check_git_commit_message(self, project_path: str, substring: str) -> dict:
        """Check that the current HEAD commit message contains substring.
        Reads .git/HEAD -> .git/refs/<ref> -> object to get commit message.
        Minimal: parse the HEAD pointer, read the log file."""
        import subprocess
        try:
            out = subprocess.run(
                ["git", "-C", project_path, "log", "-1", "--pretty=%B"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode != 0:
                return {"contains": False, "error": out.stderr.strip()}
            msg = out.stdout.strip()
            return {"contains": substring in msg, "message": msg, "substring": substring}
        except Exception as e:
            return {"contains": False, "error": str(e)}

    def check_git_file_tracked(self, project_path: str, relative_path: str) -> dict:
        """Check if a relative file path is tracked in git."""
        import subprocess
        try:
            out = subprocess.run(
                ["git", "-C", project_path, "ls-files", "--error-unmatch", relative_path],
                capture_output=True, text=True, timeout=10,
            )
            return {"tracked": out.returncode == 0, "path": relative_path}
        except Exception as e:
            return {"tracked": False, "error": str(e)}

    # === File-content grep (generic last-resort check) ===

    def check_file_contains(self, path: str, substring: str) -> dict:
        """Check a file exists and its text contents contain the substring."""
        p = Path(path)
        if not p.is_file():
            return {"contains": False, "error": f"File not found: {path}"}
        try:
            content = p.read_text(errors="replace")
        except Exception as e:
            return {"contains": False, "error": str(e)}
        return {"contains": substring in content,
                "substring": substring,
                "path": str(p),
                "size": len(content)}

    def check_xml_attribute(self, path: str, xpath: str, attr: str, value: str) -> dict:
        """Check that an XML element matching xpath has attribute attr==value."""
        p = Path(path)
        if not p.is_file():
            return {"matches": False, "error": f"File not found: {path}"}
        try:
            root = ET.parse(str(p)).getroot()
        except Exception as e:
            return {"matches": False, "error": str(e)}
        try:
            el = root.find(xpath)
        except Exception as e:
            return {"matches": False, "error": f"Bad xpath: {e}"}
        if el is None:
            return {"matches": False, "error": f"No element at xpath {xpath}"}
        actual = el.get(attr)
        return {"matches": actual == value, "actual": actual,
                "expected": value, "xpath": xpath, "attr": attr}

    def check_setting(self, project_path: str, settings_file: str,
                       key: str, value: str) -> dict:
        """Check if a project setting has the expected value.

        Reads from .settings/<settings_file> and checks key=value.

        Example:
            v.check_setting("/home/user/workspace/MyProject",
                           "org.eclipse.jdt.core.prefs",
                           "org.eclipse.jdt.core.compiler.source", "17")
            => {"matches": true, "expected": "17", "actual": "17"}
        """
        settings_path = Path(project_path) / ".settings" / settings_file
        if not settings_path.is_file():
            return {"error": f"Settings file not found: {settings_path}"}

        try:
            content = settings_path.read_text(errors="replace")
        except (PermissionError, OSError) as e:
            return {"error": f"Cannot read settings file: {e}"}

        # Parse as Java properties (key=value)
        props = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()

        actual = props.get(key)
        return {
            "matches": actual == value,
            "expected": value,
            "actual": actual,
            "key": key,
            "settings_file": settings_file,
        }


# ---------------------------------------------------------------------------
# CLI interface -- for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query: project structure
    "projects": (
        "List all projects in workspace",
        lambda v, args: v.get_projects(args[0]),
    ),
    "project-info": (
        "Parse .project file (name, natures, builders)",
        lambda v, args: v.get_project_info(args[0]),
    ),
    "classpath": (
        "Parse .classpath (source dirs, libraries, output)",
        lambda v, args: v.get_classpath(args[0]),
    ),
    "project-settings": (
        "List .settings/ files and contents",
        lambda v, args: v.get_project_settings(args[0]),
    ),
    "source-files": (
        "List source files in project",
        lambda v, args: v.get_source_files(args[0]),
    ),
    "build-output": (
        "List compiled artifacts in bin/build dirs",
        lambda v, args: v.get_build_output(args[0]),
    ),
    "workspace-info": (
        "Workspace metadata",
        lambda v, args: v.get_workspace_info(args[0]),
    ),

    # Check: boolean verification
    "check-file-exists": (
        "Check file exists",
        lambda v, args: v.check_file_exists(args[0]),
    ),
    "check-project-exists": (
        "Check project dir with .project exists",
        lambda v, args: v.check_project_exists(args[0], args[1]),
    ),
    "check-project-nature": (
        "Check project has nature",
        lambda v, args: v.check_project_nature(args[0], args[1]),
    ),
    "check-classpath-entry": (
        "Check classpath has entry (kind, path)",
        lambda v, args: v.check_classpath_entry(args[0], args[1], args[2]),
    ),
    "check-source-file-exists": (
        "Check source file exists in project",
        lambda v, args: v.check_source_file_exists(args[0], args[1]),
    ),
    "check-build-output-exists": (
        "Check compiled file exists in project",
        lambda v, args: v.check_build_output_exists(args[0], args[1]),
    ),
    "check-project-count": (
        "Check number of projects in workspace",
        lambda v, args: v.check_project_count(args[0], int(args[1])),
    ),
    "check-setting": (
        "Check project setting value",
        lambda v, args: v.check_setting(args[0], args[1], args[2], args[3]),
    ),
    # Workspace prefs
    "check-workspace-pref": (
        "Check workspace pref key=value",
        lambda v, args: v.check_workspace_pref(args[0], args[1], args[2], args[3]),
    ),
    "check-workspace-pref-contains": (
        "Check workspace pref value contains substring",
        lambda v, args: v.check_workspace_pref_contains(args[0], args[1], args[2], args[3]),
    ),
    # Launch configs
    "get-launch-config": (
        "Parse a launch config by name",
        lambda v, args: v.get_launch_config(args[0], args[1]),
    ),
    "check-launch-config": (
        "Check launch config exists with type",
        lambda v, args: v.check_launch_config(args[0], args[1], args[2]),
    ),
    "check-launch-attribute": (
        "Check launch config attribute equals value",
        lambda v, args: v.check_launch_attribute(args[0], args[1], args[2], args[3]),
    ),
    "check-launch-attribute-contains": (
        "Check launch config attribute value contains substring",
        lambda v, args: v.check_launch_attribute_contains(args[0], args[1], args[2], args[3]),
    ),
    # Breakpoints
    "get-breakpoints": (
        "List exported breakpoints",
        lambda v, args: v.get_breakpoints(args[0]),
    ),
    "check-line-breakpoint": (
        "Check line breakpoint for type/line exists",
        lambda v, args: v.check_line_breakpoint(args[0], args[1], int(args[2])),
    ),
    "check-exception-breakpoint": (
        "Check Java exception breakpoint exists",
        lambda v, args: v.check_exception_breakpoint(args[0], args[1]),
    ),
    # Working sets
    "get-working-sets": (
        "List working sets",
        lambda v, args: v.get_working_sets(args[0]),
    ),
    "check-working-set": (
        "Check working set exists with edit page id",
        lambda v, args: v.check_working_set(args[0], args[1], args[2]),
    ),
    "check-working-set-member": (
        "Check working set member contains substring",
        lambda v, args: v.check_working_set_member(args[0], args[1], args[2]),
    ),
    # Git
    "check-git-repo": (
        "Check a .git repository exists in project",
        lambda v, args: v.check_git_repo(args[0]),
    ),
    "check-git-commit-message": (
        "Check HEAD commit message contains substring",
        lambda v, args: v.check_git_commit_message(args[0], args[1]),
    ),
    "check-git-file-tracked": (
        "Check a relative file path is tracked in git",
        lambda v, args: v.check_git_file_tracked(args[0], args[1]),
    ),
    # Generic
    "check-file-contains": (
        "Check a file's text contains substring",
        lambda v, args: v.check_file_contains(args[0], args[1]),
    ),
    "check-xml-attribute": (
        "Check an XML element attribute equals value",
        lambda v, args: v.check_xml_attribute(args[0], args[1], args[2], args[3]),
    ),
}


def _print_usage():
    print("Eclipse Verifier -- query Eclipse IDE state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nEclipse binary: {ECLIPSE_BIN}")
    print("All output is JSON.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = EclipseVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
