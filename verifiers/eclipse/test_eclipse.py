"""
Test Eclipse verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing workspace, bad args)
  - Query endpoints (projects, project-info, classpath, project-settings,
    source-files, build-output, workspace-info)
  - Check endpoints (positive and negative cases for all check-* commands)

Setup:
  Creates a test workspace with two projects:
    - JavaProject: Java project with .project, .classpath, .settings, src, bin
    - EmptyProject: Minimal project with only .project

Usage:
    python verifiers/eclipse/test_eclipse.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "eclipse.py"
VERIFIER_REMOTE = "/home/user/verifiers/eclipse.py"
V = f"python3 {VERIFIER_REMOTE}"

WORKSPACE = "/home/user/test-workspace"
JAVA_PROJECT = f"{WORKSPACE}/JavaProject"
EMPTY_PROJECT = f"{WORKSPACE}/EmptyProject"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    """Minimal wrapper to normalize both success and CommandExitException results."""
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
    """Run a verifier CLI command, parse JSON output."""
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    """Run a command and return a CmdResult (never throws on non-zero exit)."""
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    """Record a test result."""
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Test workspace setup
# ---------------------------------------------------------------------------

DOT_PROJECT_JAVA = """\
<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
    <name>JavaProject</name>
    <comment>A test Java project</comment>
    <projects/>
    <buildSpec>
        <buildCommand>
            <name>org.eclipse.jdt.core.javabuilder</name>
            <arguments/>
        </buildCommand>
    </buildSpec>
    <natures>
        <nature>org.eclipse.jdt.core.javanature</nature>
    </natures>
    <linkedResources>
        <link>
            <name>docs</name>
            <type>2</type>
            <location>/home/user/shared-docs</location>
        </link>
    </linkedResources>
</projectDescription>
"""

DOT_CLASSPATH_JAVA = """\
<?xml version="1.0" encoding="UTF-8"?>
<classpath>
    <classpathentry kind="src" path="src"/>
    <classpathentry kind="con" path="org.eclipse.jdt.launching.JRE_CONTAINER"/>
    <classpathentry kind="lib" path="lib/junit.jar"/>
    <classpathentry kind="output" path="bin"/>
</classpath>
"""

JDT_CORE_PREFS = """\
eclipse.preferences.version=1
org.eclipse.jdt.core.compiler.compliance=17
org.eclipse.jdt.core.compiler.source=17
org.eclipse.jdt.core.compiler.codegen.targetPlatform=17
"""

MAIN_JAVA = """\
package com.example;

public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, Eclipse!");
    }
}
"""

DOT_PROJECT_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
    <name>EmptyProject</name>
    <comment/>
    <projects/>
    <buildSpec/>
    <natures/>
</projectDescription>
"""


LAUNCH_CONFIG_MAIN = """\
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<launchConfiguration type="org.eclipse.jdt.launching.localJavaApplication">
<stringAttribute key="org.eclipse.jdt.launching.MAIN_TYPE" value="com.example.Main"/>
<stringAttribute key="org.eclipse.jdt.launching.PROJECT_ATTR" value="JavaProject"/>
<stringAttribute key="org.eclipse.jdt.launching.PROGRAM_ARGUMENTS" value="--flag hello world"/>
<booleanAttribute key="org.eclipse.debug.core.capture_output" value="true"/>
</launchConfiguration>
"""

LAUNCH_CONFIG_JUNIT = """\
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<launchConfiguration type="org.eclipse.jdt.junit.launchconfig">
<stringAttribute key="org.eclipse.jdt.launching.MAIN_TYPE" value="com.example.MainTest"/>
<stringAttribute key="org.eclipse.jdt.launching.PROJECT_ATTR" value="JavaProject"/>
</launchConfiguration>
"""

BREAKPOINTS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<breakpoints>
  <breakpoint enabled="true" registered="true">
    <marker type="org.eclipse.jdt.debug.javaLineBreakpointMarker">
      <attrib name="org.eclipse.jdt.debug.core.typeName" value="com.example.Main"/>
      <attrib name="lineNumber" value="5"/>
    </marker>
  </breakpoint>
  <breakpoint enabled="true" registered="true">
    <marker type="org.eclipse.jdt.debug.javaExceptionBreakpointMarker">
      <attrib name="org.eclipse.jdt.debug.core.typeName" value="java.lang.NullPointerException"/>
      <attrib name="exceptionTypeName" value="java.lang.NullPointerException"/>
    </marker>
  </breakpoint>
</breakpoints>
"""

WORKINGSETS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<workingSets>
  <workingSet name="MainSet" editPageId="org.eclipse.jdt.ui.JavaWorkingSetPage" id="ws1" label="MainSet">
    <item elementID="=JavaProject" factoryID="org.eclipse.jdt.ui.PersistableJavaElementFactory"/>
    <item elementID="=JavaProject/src" factoryID="org.eclipse.jdt.ui.PersistableJavaElementFactory"/>
  </workingSet>
  <workingSet name="EmptySet" editPageId="org.eclipse.ui.resourceWorkingSetPage" id="ws2" label="EmptySet">
  </workingSet>
</workingSets>
"""

WORKSPACE_UI_PREFS = """\
eclipse.preferences.version=1
showIntro=false
PROBLEMS_FILTERS_MIGRATE=true
custom_templates=<?xml version\\="1.0" encoding\\="UTF-8"?><templates><template name\\="MyTemplate"/></templates>
"""


def setup_test_workspace(sandbox: Sandbox):
    """Create test workspace with project directories, XML files, source, and build output."""
    print("\nSetting up test workspace...")

    # Create directory structure
    sandbox.commands.run(
        f"mkdir -p {JAVA_PROJECT}/src/com/example "
        f"{JAVA_PROJECT}/bin/com/example "
        f"{JAVA_PROJECT}/.settings "
        f"{JAVA_PROJECT}/lib "
        f"{EMPTY_PROJECT} "
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.core.runtime/.settings "
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.debug.core/.launches "
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.debug.core "
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.ui.workbench"
    )

    # Write files
    sandbox.files.write(f"{JAVA_PROJECT}/.project", DOT_PROJECT_JAVA)
    sandbox.files.write(f"{JAVA_PROJECT}/.classpath", DOT_CLASSPATH_JAVA)
    sandbox.files.write(
        f"{JAVA_PROJECT}/.settings/org.eclipse.jdt.core.prefs",
        JDT_CORE_PREFS,
    )
    sandbox.files.write(
        f"{JAVA_PROJECT}/src/com/example/Main.java",
        MAIN_JAVA,
    )
    # Fake compiled output
    sandbox.files.write(
        f"{JAVA_PROJECT}/bin/com/example/Main.class",
        "CAFEBABE",  # fake class file marker
    )
    # Fake library
    sandbox.files.write(f"{JAVA_PROJECT}/lib/junit.jar", "PK_FAKE_JAR")

    # Empty project
    sandbox.files.write(f"{EMPTY_PROJECT}/.project", DOT_PROJECT_EMPTY)

    # Workspace metadata — UI prefs (used for workspace-pref tests)
    sandbox.files.write(
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.core.runtime/.settings/org.eclipse.ui.prefs",
        WORKSPACE_UI_PREFS,
    )

    # Launch configurations
    sandbox.files.write(
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.debug.core/.launches/MainLaunch.launch",
        LAUNCH_CONFIG_MAIN,
    )
    sandbox.files.write(
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.debug.core/.launches/JUnitLaunch.launch",
        LAUNCH_CONFIG_JUNIT,
    )

    # Breakpoints exported at workspace root (primary location for verifier)
    sandbox.files.write(f"{WORKSPACE}/breakpoints.xml", BREAKPOINTS_XML)

    # Working sets
    sandbox.files.write(
        f"{WORKSPACE}/.metadata/.plugins/org.eclipse.ui.workbench/workingsets.xml",
        WORKINGSETS_XML,
    )

    # Git repo inside JavaProject
    sandbox.commands.run(
        f"cd {JAVA_PROJECT} && "
        f"git init -q && "
        f"git config user.email test@example.com && "
        f"git config user.name Tester && "
        f"git add .project .classpath src/com/example/Main.java && "
        f"git commit -q -m 'Initial commit: add JavaProject scaffolding'"
    )

    print("  Test workspace created.")


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions eclipse", "Eclipse" in result.stdout, result.stdout[:100])


def test_errors(sandbox: Sandbox):
    """Error cases: missing workspace, bad args, unknown command."""
    print("\n=== Errors ===")

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing required arg
    result = run_raw(sandbox, "projects")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Nonexistent workspace
    data = run(sandbox, "projects /nonexistent/workspace")
    if isinstance(data, list) and data:
        data = data[0]
    check("nonexistent workspace returns error", "error" in data, str(data)[:100])

    # Nonexistent project
    data = run(sandbox, "project-info /nonexistent/project")
    check("nonexistent project returns error", "error" in data, str(data)[:100])

    # Missing args for check commands
    result = run_raw(sandbox, "check-project-exists /tmp")
    check("check-project-exists missing arg exits 1", result.exit_code == 1)


def test_query_projects(sandbox: Sandbox):
    """Test projects and workspace-info query endpoints."""
    print("\n=== Query: Projects ===")

    # projects
    data = run(sandbox, f"projects {WORKSPACE}")
    check("projects returns list", isinstance(data, list), str(type(data)))
    check("projects has 2 entries", len(data) == 2, f"got {len(data)}")
    names = [p["name"] for p in data]
    check("projects has EmptyProject", "EmptyProject" in names, str(names))
    check("projects has JavaProject", "JavaProject" in names, str(names))

    # Find JavaProject entry
    java_proj = next((p for p in data if p["name"] == "JavaProject"), None)
    if java_proj:
        check("JavaProject has_classpath=true", java_proj.get("has_classpath") is True)
        check("JavaProject has_settings=true", java_proj.get("has_settings") is True)

    # workspace-info
    data = run(sandbox, f"workspace-info {WORKSPACE}")
    check("workspace-info returns dict", isinstance(data, dict))
    check("workspace-info has_metadata=true", data.get("has_metadata") is True)
    check("workspace-info project_count=2", data.get("project_count") == 2,
          f"got {data.get('project_count')}")


def test_query_project_info(sandbox: Sandbox):
    """Test project-info endpoint."""
    print("\n=== Query: Project Info ===")

    data = run(sandbox, f"project-info {JAVA_PROJECT}")
    check("project-info returns dict", isinstance(data, dict))
    check("project-info name=JavaProject", data.get("name") == "JavaProject",
          f"got {data.get('name')}")
    check("project-info has comment", data.get("comment") == "A test Java project",
          f"got {data.get('comment')}")
    check("project-info has javanature",
          "org.eclipse.jdt.core.javanature" in data.get("natures", []),
          str(data.get("natures")))
    check("project-info nature_labels has Java",
          "Java" in data.get("nature_labels", []),
          str(data.get("nature_labels")))
    check("project-info has javabuilder",
          "org.eclipse.jdt.core.javabuilder" in data.get("builders", []),
          str(data.get("builders")))
    check("project-info has linked resources",
          len(data.get("linked_resources", [])) > 0,
          str(data.get("linked_resources")))

    # Empty project
    data = run(sandbox, f"project-info {EMPTY_PROJECT}")
    check("empty project name=EmptyProject", data.get("name") == "EmptyProject")
    check("empty project no natures", len(data.get("natures", [])) == 0)


def test_query_classpath(sandbox: Sandbox):
    """Test classpath endpoint."""
    print("\n=== Query: Classpath ===")

    data = run(sandbox, f"classpath {JAVA_PROJECT}")
    check("classpath returns dict", isinstance(data, dict))
    check("classpath has entries", len(data.get("entries", [])) == 4,
          f"got {len(data.get('entries', []))}")
    check("classpath source_dirs has src", "src" in data.get("source_dirs", []),
          str(data.get("source_dirs")))
    check("classpath output_dir=bin", data.get("output_dir") == "bin",
          f"got {data.get('output_dir')}")
    check("classpath has JRE container",
          any("JRE_CONTAINER" in c for c in data.get("containers", [])),
          str(data.get("containers")))
    check("classpath has junit lib",
          "lib/junit.jar" in data.get("libraries", []),
          str(data.get("libraries")))

    # Empty project has no .classpath
    data = run(sandbox, f"classpath {EMPTY_PROJECT}")
    check("empty project classpath returns error", "error" in data, str(data)[:100])


def test_query_settings(sandbox: Sandbox):
    """Test project-settings endpoint."""
    print("\n=== Query: Settings ===")

    data = run(sandbox, f"project-settings {JAVA_PROJECT}")
    check("settings returns dict", isinstance(data, dict))
    files = data.get("files", {})
    check("settings has jdt.core.prefs", "org.eclipse.jdt.core.prefs" in files,
          str(list(files.keys())))

    jdt_prefs = files.get("org.eclipse.jdt.core.prefs", {})
    check("jdt.core compiler.source=17",
          jdt_prefs.get("org.eclipse.jdt.core.compiler.source") == "17",
          str(jdt_prefs))

    # Empty project has no .settings
    data = run(sandbox, f"project-settings {EMPTY_PROJECT}")
    check("empty project settings returns error", "error" in data, str(data)[:100])


def test_query_source_files(sandbox: Sandbox):
    """Test source-files endpoint."""
    print("\n=== Query: Source Files ===")

    data = run(sandbox, f"source-files {JAVA_PROJECT}")
    check("source-files returns dict", isinstance(data, dict))
    check("source-files count >= 1", data.get("count", 0) >= 1,
          f"got {data.get('count')}")

    paths = [f["path"] for f in data.get("files", [])]
    check("source-files has Main.java",
          any("Main.java" in p for p in paths),
          str(paths))


def test_query_build_output(sandbox: Sandbox):
    """Test build-output endpoint."""
    print("\n=== Query: Build Output ===")

    data = run(sandbox, f"build-output {JAVA_PROJECT}")
    check("build-output returns dict", isinstance(data, dict))
    check("build-output found bin dir", "bin" in data.get("output_dirs_found", []),
          str(data.get("output_dirs_found")))
    check("build-output count >= 1", data.get("count", 0) >= 1,
          f"got {data.get('count')}")

    paths = [f["path"] for f in data.get("files", [])]
    check("build-output has Main.class",
          any("Main.class" in p for p in paths),
          str(paths))


def test_checks_positive(sandbox: Sandbox):
    """Positive cases for all check-* endpoints."""
    print("\n=== Checks (positive) ===")

    # check-file-exists
    data = run(sandbox, f"check-file-exists {JAVA_PROJECT}/.project")
    check("check-file-exists .project exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-project-exists
    data = run(sandbox, f"check-project-exists {WORKSPACE} JavaProject")
    check("check-project-exists JavaProject exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-project-nature
    data = run(sandbox,
               f"check-project-nature {JAVA_PROJECT} org.eclipse.jdt.core.javanature")
    check("check-project-nature java has_nature=true",
          data.get("has_nature") is True, str(data)[:100])

    # check-classpath-entry (src)
    data = run(sandbox, f"check-classpath-entry {JAVA_PROJECT} src src")
    check("check-classpath-entry src exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-classpath-entry (output)
    data = run(sandbox, f"check-classpath-entry {JAVA_PROJECT} output bin")
    check("check-classpath-entry output exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-classpath-entry (lib)
    data = run(sandbox, f"check-classpath-entry {JAVA_PROJECT} lib lib/junit.jar")
    check("check-classpath-entry lib exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-source-file-exists
    data = run(sandbox,
               f"check-source-file-exists {JAVA_PROJECT} src/com/example/Main.java")
    check("check-source-file-exists Main.java exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-build-output-exists
    data = run(sandbox,
               f"check-build-output-exists {JAVA_PROJECT} bin/com/example/Main.class")
    check("check-build-output-exists Main.class exists=true",
          data.get("exists") is True, str(data)[:100])

    # check-project-count
    data = run(sandbox, f"check-project-count {WORKSPACE} 2")
    check("check-project-count 2 matches=true",
          data.get("matches") is True, str(data)[:100])

    # check-setting
    data = run(sandbox,
               f"check-setting {JAVA_PROJECT} org.eclipse.jdt.core.prefs "
               f"org.eclipse.jdt.core.compiler.source 17")
    check("check-setting source=17 matches=true",
          data.get("matches") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Negative cases for check-* endpoints."""
    print("\n=== Checks (negative) ===")

    # check-file-exists (nonexistent)
    data = run(sandbox, f"check-file-exists {WORKSPACE}/nonexistent.txt")
    check("check-file-exists nonexistent exists=false",
          data.get("exists") is False, str(data)[:100])

    # check-project-exists (nonexistent project)
    data = run(sandbox, f"check-project-exists {WORKSPACE} NoSuchProject")
    check("check-project-exists NoSuchProject exists=false",
          data.get("exists") is False, str(data)[:100])

    # check-project-nature (wrong nature)
    data = run(sandbox,
               f"check-project-nature {JAVA_PROJECT} org.eclipse.cdt.core.cnature")
    check("check-project-nature C has_nature=false",
          data.get("has_nature") is False, str(data)[:100])

    # check-classpath-entry (nonexistent)
    data = run(sandbox, f"check-classpath-entry {JAVA_PROJECT} lib nonexistent.jar")
    check("check-classpath-entry nonexistent exists=false",
          data.get("exists") is False, str(data)[:100])

    # check-source-file-exists (nonexistent)
    data = run(sandbox,
               f"check-source-file-exists {JAVA_PROJECT} src/NoSuch.java")
    check("check-source-file-exists nonexistent exists=false",
          data.get("exists") is False, str(data)[:100])

    # check-build-output-exists (nonexistent)
    data = run(sandbox,
               f"check-build-output-exists {JAVA_PROJECT} bin/NoSuch.class")
    check("check-build-output-exists nonexistent exists=false",
          data.get("exists") is False, str(data)[:100])

    # check-project-count (wrong count)
    data = run(sandbox, f"check-project-count {WORKSPACE} 99")
    check("check-project-count 99 matches=false",
          data.get("matches") is False, str(data)[:100])

    # check-setting (wrong value)
    data = run(sandbox,
               f"check-setting {JAVA_PROJECT} org.eclipse.jdt.core.prefs "
               f"org.eclipse.jdt.core.compiler.source 11")
    check("check-setting source!=11 matches=false",
          data.get("matches") is False, str(data)[:100])

    # check-setting (nonexistent key)
    data = run(sandbox,
               f"check-setting {JAVA_PROJECT} org.eclipse.jdt.core.prefs "
               f"nonexistent.key somevalue")
    check("check-setting nonexistent key matches=false",
          data.get("matches") is False, str(data)[:100])


def test_workspace_prefs(sandbox: Sandbox):
    """check-workspace-pref and check-workspace-pref-contains (pos+neg)."""
    print("\n=== Checks: Workspace Prefs ===")

    # Positive: exact match
    data = run(sandbox,
               f"check-workspace-pref {WORKSPACE} org.eclipse.ui.prefs "
               f"showIntro false")
    check("workspace-pref showIntro=false matches=true",
          data.get("matches") is True, str(data)[:120])

    # Negative: value mismatch
    data = run(sandbox,
               f"check-workspace-pref {WORKSPACE} org.eclipse.ui.prefs "
               f"showIntro true")
    check("workspace-pref showIntro!=true matches=false",
          data.get("matches") is False, str(data)[:120])

    # Negative: nonexistent key
    data = run(sandbox,
               f"check-workspace-pref {WORKSPACE} org.eclipse.ui.prefs "
               f"no.such.key anything")
    check("workspace-pref missing key matches=false",
          data.get("matches") is False, str(data)[:120])

    # Negative: nonexistent prefs file
    data = run(sandbox,
               f"check-workspace-pref {WORKSPACE} no.such.prefs key value")
    check("workspace-pref missing prefs file returns error",
          "error" in data, str(data)[:120])

    # Positive: substring contains
    data = run(sandbox,
               f"check-workspace-pref-contains {WORKSPACE} org.eclipse.ui.prefs "
               f"custom_templates MyTemplate")
    check("workspace-pref-contains MyTemplate contains=true",
          data.get("contains") is True, str(data)[:120])

    # Negative: substring absent
    data = run(sandbox,
               f"check-workspace-pref-contains {WORKSPACE} org.eclipse.ui.prefs "
               f"custom_templates NotPresent")
    check("workspace-pref-contains NotPresent contains=false",
          data.get("contains") is False, str(data)[:120])


def test_launch_configs(sandbox: Sandbox):
    """get-launch-config, check-launch-config, check-launch-attribute(-contains)."""
    print("\n=== Checks: Launch Configs ===")

    # get-launch-config (positive)
    data = run(sandbox, f"get-launch-config {WORKSPACE} MainLaunch")
    check("get-launch-config returns dict", isinstance(data, dict))
    check("get-launch-config type correct",
          data.get("type") == "org.eclipse.jdt.launching.localJavaApplication",
          str(data)[:120])
    attrs = data.get("attributes", {}) if isinstance(data, dict) else {}
    check("get-launch-config has MAIN_TYPE attribute",
          attrs.get("org.eclipse.jdt.launching.MAIN_TYPE") == "com.example.Main",
          str(attrs)[:200])

    # get-launch-config (negative — nonexistent name)
    data = run(sandbox, f"get-launch-config {WORKSPACE} NoSuchLaunch")
    check("get-launch-config missing returns error",
          "error" in data, str(data)[:120])

    # check-launch-config (positive)
    data = run(sandbox,
               f"check-launch-config {WORKSPACE} MainLaunch "
               f"org.eclipse.jdt.launching.localJavaApplication")
    check("check-launch-config type matches",
          data.get("type_matches") is True, str(data)[:120])

    # check-launch-config (negative — wrong type)
    data = run(sandbox,
               f"check-launch-config {WORKSPACE} MainLaunch "
               f"org.eclipse.jdt.junit.launchconfig")
    check("check-launch-config wrong type matches=false",
          data.get("type_matches") is False, str(data)[:120])

    # check-launch-config (negative — nonexistent name)
    data = run(sandbox,
               f"check-launch-config {WORKSPACE} NoSuchLaunch sometype")
    check("check-launch-config missing name exists=false",
          data.get("exists") is False, str(data)[:120])

    # check-launch-attribute (positive)
    data = run(sandbox,
               f"check-launch-attribute {WORKSPACE} MainLaunch "
               f"org.eclipse.jdt.launching.MAIN_TYPE com.example.Main")
    check("check-launch-attribute MAIN_TYPE matches",
          data.get("matches") is True, str(data)[:120])

    # check-launch-attribute (negative — wrong value)
    data = run(sandbox,
               f"check-launch-attribute {WORKSPACE} MainLaunch "
               f"org.eclipse.jdt.launching.MAIN_TYPE com.example.Other")
    check("check-launch-attribute wrong value matches=false",
          data.get("matches") is False, str(data)[:120])

    # check-launch-attribute-contains (positive)
    data = run(sandbox,
               f"check-launch-attribute-contains {WORKSPACE} MainLaunch "
               f"org.eclipse.jdt.launching.PROGRAM_ARGUMENTS hello")
    check("check-launch-attribute-contains hello contains=true",
          data.get("contains") is True, str(data)[:120])

    # check-launch-attribute-contains (negative — substring absent)
    data = run(sandbox,
               f"check-launch-attribute-contains {WORKSPACE} MainLaunch "
               f"org.eclipse.jdt.launching.PROGRAM_ARGUMENTS notfound")
    check("check-launch-attribute-contains notfound contains=false",
          data.get("contains") is False, str(data)[:120])


def test_breakpoints(sandbox: Sandbox):
    """get-breakpoints, check-line-breakpoint, check-exception-breakpoint."""
    print("\n=== Checks: Breakpoints ===")

    # get-breakpoints (positive)
    data = run(sandbox, f"get-breakpoints {WORKSPACE}")
    check("get-breakpoints returns dict", isinstance(data, dict))
    check("get-breakpoints count=2", data.get("count") == 2, str(data)[:200])

    # check-line-breakpoint (positive)
    data = run(sandbox,
               f"check-line-breakpoint {WORKSPACE} com.example.Main 5")
    check("check-line-breakpoint Main:5 exists=true",
          data.get("exists") is True, str(data)[:150])

    # check-line-breakpoint (negative — wrong line)
    data = run(sandbox,
               f"check-line-breakpoint {WORKSPACE} com.example.Main 999")
    check("check-line-breakpoint Main:999 exists=false",
          data.get("exists") is False, str(data)[:150])

    # check-line-breakpoint (negative — wrong type)
    data = run(sandbox,
               f"check-line-breakpoint {WORKSPACE} com.example.NoSuch 5")
    check("check-line-breakpoint NoSuch:5 exists=false",
          data.get("exists") is False, str(data)[:150])

    # check-exception-breakpoint (positive)
    data = run(sandbox,
               f"check-exception-breakpoint {WORKSPACE} java.lang.NullPointerException")
    check("check-exception-breakpoint NPE exists=true",
          data.get("exists") is True, str(data)[:150])

    # check-exception-breakpoint (negative)
    data = run(sandbox,
               f"check-exception-breakpoint {WORKSPACE} java.io.IOException")
    check("check-exception-breakpoint IOException exists=false",
          data.get("exists") is False, str(data)[:150])


def test_working_sets(sandbox: Sandbox):
    """get-working-sets, check-working-set, check-working-set-member."""
    print("\n=== Checks: Working Sets ===")

    # get-working-sets (positive)
    data = run(sandbox, f"get-working-sets {WORKSPACE}")
    check("get-working-sets returns dict", isinstance(data, dict))
    check("get-working-sets count=2", data.get("count") == 2, str(data)[:200])

    # check-working-set (positive — name + editPageId)
    data = run(sandbox,
               f"check-working-set {WORKSPACE} MainSet "
               f"org.eclipse.jdt.ui.JavaWorkingSetPage")
    check("check-working-set MainSet page_matches=true",
          data.get("page_matches") is True, str(data)[:200])

    # check-working-set (negative — wrong page)
    data = run(sandbox,
               f"check-working-set {WORKSPACE} MainSet wrong.page.id")
    check("check-working-set wrong page page_matches=false",
          data.get("page_matches") is False, str(data)[:200])

    # check-working-set (negative — nonexistent name)
    data = run(sandbox,
               f"check-working-set {WORKSPACE} NoSuchSet anything")
    check("check-working-set missing name exists=false",
          data.get("exists") is False, str(data)[:200])

    # check-working-set-member (positive)
    data = run(sandbox,
               f"check-working-set-member {WORKSPACE} MainSet JavaProject")
    check("check-working-set-member JavaProject contains=true",
          data.get("contains") is True, str(data)[:200])

    # check-working-set-member (negative — substring absent)
    data = run(sandbox,
               f"check-working-set-member {WORKSPACE} MainSet NotAMember")
    check("check-working-set-member NotAMember contains=false",
          data.get("contains") is False, str(data)[:200])

    # check-working-set-member (negative — working set missing)
    data = run(sandbox,
               f"check-working-set-member {WORKSPACE} NoSuchSet anything")
    check("check-working-set-member missing set contains=false",
          data.get("contains") is False, str(data)[:200])


def test_git(sandbox: Sandbox):
    """check-git-repo, check-git-commit-message, check-git-file-tracked."""
    print("\n=== Checks: Git ===")

    # check-git-repo (positive)
    data = run(sandbox, f"check-git-repo {JAVA_PROJECT}")
    check("check-git-repo JavaProject head_exists=true",
          data.get("head_exists") is True, str(data)[:150])

    # check-git-repo (negative — EmptyProject has no git)
    data = run(sandbox, f"check-git-repo {EMPTY_PROJECT}")
    check("check-git-repo EmptyProject head_exists=false",
          data.get("head_exists") is False, str(data)[:150])

    # check-git-commit-message (positive)
    data = run(sandbox,
               f"check-git-commit-message {JAVA_PROJECT} 'Initial'")
    check("check-git-commit-message Initial contains=true",
          data.get("contains") is True, str(data)[:200])

    # check-git-commit-message (negative)
    data = run(sandbox,
               f"check-git-commit-message {JAVA_PROJECT} 'NeverWritten'")
    check("check-git-commit-message NeverWritten contains=false",
          data.get("contains") is False, str(data)[:200])

    # check-git-file-tracked (positive)
    data = run(sandbox,
               f"check-git-file-tracked {JAVA_PROJECT} "
               f"src/com/example/Main.java")
    check("check-git-file-tracked Main.java tracked=true",
          data.get("tracked") is True, str(data)[:200])

    # check-git-file-tracked (negative — untracked file)
    data = run(sandbox,
               f"check-git-file-tracked {JAVA_PROJECT} lib/junit.jar")
    check("check-git-file-tracked junit.jar tracked=false",
          data.get("tracked") is False, str(data)[:200])

    # check-git-file-tracked (negative — nonexistent)
    data = run(sandbox,
               f"check-git-file-tracked {JAVA_PROJECT} no/such/file.java")
    check("check-git-file-tracked nonexistent tracked=false",
          data.get("tracked") is False, str(data)[:200])


def test_file_contains_and_xml_attribute(sandbox: Sandbox):
    """check-file-contains and check-xml-attribute (pos+neg across multiple files)."""
    print("\n=== Checks: File contents & XML attributes ===")

    # check-file-contains (positive)
    data = run(sandbox,
               f"check-file-contains {JAVA_PROJECT}/src/com/example/Main.java "
               f"'Hello, Eclipse!'")
    check("check-file-contains Hello contains=true",
          data.get("contains") is True, str(data)[:150])

    # check-file-contains (negative — substring absent)
    data = run(sandbox,
               f"check-file-contains {JAVA_PROJECT}/src/com/example/Main.java "
               f"'Goodbye'")
    check("check-file-contains Goodbye contains=false",
          data.get("contains") is False, str(data)[:150])

    # check-file-contains (negative — nonexistent file)
    data = run(sandbox,
               f"check-file-contains {WORKSPACE}/no-such-file.txt foo")
    check("check-file-contains missing file returns error",
          "error" in data, str(data)[:150])

    # check-xml-attribute on .launch — POSITIVE (type matches)
    launch_path = (f"{WORKSPACE}/.metadata/.plugins/"
                   f"org.eclipse.debug.core/.launches/MainLaunch.launch")
    data = run(sandbox,
               f"check-xml-attribute {launch_path} . type "
               f"org.eclipse.jdt.launching.localJavaApplication")
    check("check-xml-attribute MainLaunch.type matches=true",
          data.get("matches") is True, str(data)[:200])

    # check-xml-attribute on .launch — NEGATIVE (value mismatch)
    data = run(sandbox,
               f"check-xml-attribute {launch_path} . type "
               f"org.eclipse.jdt.junit.launchconfig")
    check("check-xml-attribute MainLaunch.type mismatch matches=false",
          data.get("matches") is False, str(data)[:200])

    # check-xml-attribute on JUnitLaunch — POSITIVE (different file, matches)
    junit_path = (f"{WORKSPACE}/.metadata/.plugins/"
                  f"org.eclipse.debug.core/.launches/JUnitLaunch.launch")
    data = run(sandbox,
               f"check-xml-attribute {junit_path} . type "
               f"org.eclipse.jdt.junit.launchconfig")
    check("check-xml-attribute JUnitLaunch.type matches=true",
          data.get("matches") is True, str(data)[:200])

    # check-xml-attribute on nested stringAttribute — POSITIVE (using xpath
    # predicate to find the MAIN_TYPE stringAttribute and check its value).
    # Note: single quotes inside the predicate must survive shell parsing,
    # so we wrap the xpath argument in double quotes.
    data = run(sandbox,
               f"check-xml-attribute {launch_path} "
               f"\"stringAttribute[@key='org.eclipse.jdt.launching.MAIN_TYPE']\" "
               f"value com.example.Main")
    check("check-xml-attribute MAIN_TYPE value matches=true",
          data.get("matches") is True, str(data)[:200])

    # check-xml-attribute on nested stringAttribute — NEGATIVE
    data = run(sandbox,
               f"check-xml-attribute {launch_path} "
               f"\"stringAttribute[@key='org.eclipse.jdt.launching.MAIN_TYPE']\" "
               f"value com.example.Wrong")
    check("check-xml-attribute MAIN_TYPE wrong value matches=false",
          data.get("matches") is False, str(data)[:200])

    # check-xml-attribute — negative (nonexistent file)
    data = run(sandbox,
               f"check-xml-attribute {WORKSPACE}/no.xml . type foo")
    check("check-xml-attribute missing file returns error",
          "error" in data, str(data)[:200])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands with valid args that should produce JSON
    cmds = [
        f"projects {WORKSPACE}",
        f"project-info {JAVA_PROJECT}",
        f"classpath {JAVA_PROJECT}",
        f"project-settings {JAVA_PROJECT}",
        f"source-files {JAVA_PROJECT}",
        f"build-output {JAVA_PROJECT}",
        f"workspace-info {WORKSPACE}",
        f"check-file-exists {JAVA_PROJECT}/.project",
        f"check-project-exists {WORKSPACE} JavaProject",
        f"check-project-nature {JAVA_PROJECT} org.eclipse.jdt.core.javanature",
        f"check-classpath-entry {JAVA_PROJECT} src src",
        f"check-source-file-exists {JAVA_PROJECT} src/com/example/Main.java",
        f"check-build-output-exists {JAVA_PROJECT} bin/com/example/Main.class",
        f"check-project-count {WORKSPACE} 2",
        f"check-setting {JAVA_PROJECT} org.eclipse.jdt.core.prefs org.eclipse.jdt.core.compiler.source 17",
        f"check-workspace-pref {WORKSPACE} org.eclipse.ui.prefs showIntro false",
        f"check-workspace-pref-contains {WORKSPACE} org.eclipse.ui.prefs custom_templates MyTemplate",
        f"get-launch-config {WORKSPACE} MainLaunch",
        f"check-launch-config {WORKSPACE} MainLaunch org.eclipse.jdt.launching.localJavaApplication",
        f"check-launch-attribute {WORKSPACE} MainLaunch org.eclipse.jdt.launching.MAIN_TYPE com.example.Main",
        f"check-launch-attribute-contains {WORKSPACE} MainLaunch org.eclipse.jdt.launching.PROGRAM_ARGUMENTS hello",
        f"get-breakpoints {WORKSPACE}",
        f"check-line-breakpoint {WORKSPACE} com.example.Main 5",
        f"check-exception-breakpoint {WORKSPACE} java.lang.NullPointerException",
        f"get-working-sets {WORKSPACE}",
        f"check-working-set {WORKSPACE} MainSet org.eclipse.jdt.ui.JavaWorkingSetPage",
        f"check-working-set-member {WORKSPACE} MainSet JavaProject",
        f"check-git-repo {JAVA_PROJECT}",
        f"check-git-commit-message {JAVA_PROJECT} Initial",
        f"check-git-file-tracked {JAVA_PROJECT} src/com/example/Main.java",
        f"check-file-contains {JAVA_PROJECT}/src/com/example/Main.java Hello",
        (f"check-xml-attribute {WORKSPACE}/.metadata/.plugins/"
         f"org.eclipse.debug.core/.launches/MainLaunch.launch . type "
         f"org.eclipse.jdt.launching.localJavaApplication"),
    ]

    for cmd in cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        label = cmd.split()[0]
        check(f"{label} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Eclipse Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Setup test workspace
        setup_test_workspace(sandbox)

        # --- Run tests ---
        test_help(sandbox)
        test_errors(sandbox)
        test_query_projects(sandbox)
        test_query_project_info(sandbox)
        test_query_classpath(sandbox)
        test_query_settings(sandbox)
        test_query_source_files(sandbox)
        test_query_build_output(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_workspace_prefs(sandbox)
        test_launch_configs(sandbox)
        test_breakpoints(sandbox)
        test_working_sets(sandbox)
        test_git(sandbox)
        test_file_contains_and_xml_attribute(sandbox)
        test_all_commands_return_json(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    # --- Summary ---
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
