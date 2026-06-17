"""
CLI Agent Runner for evaluating Claude Code on tasks.

This module runs Claude Code CLI inside a Docker sandbox and captures
the complete execution process for analysis.

CRITICAL: For fairness with GUI testing, CLI testing follows the EXACT SAME
setup and verification flow. The ONLY difference is the agent execution method:
- GUI Agent: Uses screenshots and visual interaction
- CLI Agent: Uses claude CLI with commands (bash, cli-anything skills, etc.)

Everything else is IDENTICAL:
- ✅ Same app launch
- ✅ Same verifier upload
- ✅ Same task env file upload
- ✅ Same verification logic
- ✅ Same sandbox configuration
"""

from __future__ import annotations

import json
import re
import shlex
import time
from datetime import datetime
from pathlib import Path

from computer_env.backends.base import CommandExitException

from .run_config import TASK_GEN_DIR


# ── System Prompts for CLI Agent ─────────────────────────────────────────────
CLI_SYSTEM_PROMPT = """<SYSTEM_CAPABILITY>
* You are utilising an Ubuntu virtual machine (Docker container) using x86_64 architecture with internet access.
* You can feel free to install Ubuntu applications with your bash tool. Use curl instead of wget.
* DO NOT ask users for clarification during task execution. DO NOT stop to request more information from users. Always take action using available tools.
* When using bash commands that are expected to output very large quantities of text, redirect into a tmp file and use Read or grep to confirm output.
* TASK FEASIBILITY: You can declare a task infeasible at any point during execution. If you determine that a task cannot be completed, output exactly "[INFEASIBLE]" (including the square brackets) anywhere in your response.
* Home directory of this Ubuntu system is '/home/user'.
* If you need a password for sudo, the password of the computer is 'user'.
* The current date is {date}.

<IMPORTANT_CAPABILITIES>
* You have access to CLI-anything skills for various applications installed in the system
* The system includes desktop applications for office work, graphics editing, development, media playback, music notation, and more
* Available CLI-anything skills can be discovered and used as needed for different target applications

* You also have access to standard tools with strict limits:
  - Bash: Use for read-only inspection, skill discovery, invoking CLI-anything/application commands, and verification.
  - Read: Inspect files when needed.

<CLI_ANYTHING_ONLY_POLICY>
You must solve the task by using CLI-anything skills for the target application.

Hard requirements:
* First discover the relevant CLI-anything skill(s) for the application and use those skill-provided commands/workflows as the primary and mandatory way to complete the task.
* All task-result changes must be performed through CLI-anything skill workflows or application-level commands explicitly recommended by those skills.
* You must not directly modify task files, project files, application config files, databases, document archives, or other target artifacts with generic file-editing methods.
* Do not use Python, sed, awk, perl, node scripts, shell redirection, heredocs, Write/Edit tools, or manual archive/database editing to change the target artifact.
* Bash is allowed only for read-only inspection, skill discovery, invoking CLI-anything/application commands, and verification. It must not be used to directly rewrite target files.
* Python is allowed only for read-only inspection if absolutely necessary. It must never write, patch, serialize, save, or mutate task artifacts.
* If the task cannot be completed through CLI-anything skills or skill-approved application commands, output exactly "[INFEASIBLE]" instead of bypassing the restriction with direct file edits.
</CLI_ANYTHING_ONLY_POLICY>

<TASK_EXECUTION_APPROACH>
Use this order:
1. Identify the target application and discover its CLI-anything skill.
2. Follow the skill's documented workflow to perform the requested changes.
3. Use read-only commands to inspect results when needed.
4. If no CLI-anything path exists, declare "[INFEASIBLE]".

Direct file mutation is not an acceptable fallback.
</TASK_EXECUTION_APPROACH>
</IMPORTANT_CAPABILITIES>
</SYSTEM_CAPABILITY>"""


def build_task_prompt(task: dict) -> str:
    """Build the task prompt for Claude Code CLI.

    Args:
        task: Task dictionary containing the task description

    Returns:
        Complete prompt with system prompt + task description
    """
    from datetime import datetime

    # Use neutral system prompt
    system_prompt = CLI_SYSTEM_PROMPT
    
    # Format with current date
    formatted_system = system_prompt.format(
        date=datetime.today().strftime("%A, %B %d, %Y")
    )
    
    # Get the task description (same as GUI Agent)
    task_description = task.get("task", "")

    # Combine system prompt with task
    return f"{formatted_system}\n\n<USER_TASK>\n{task_description}\n</USER_TASK>"


def _extract_reported_models(value) -> list[str]:
    """Extract model names reported by provider JSON events, if present."""
    models: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "model" and isinstance(item, str) and item:
                models.append(item)
            else:
                models.extend(_extract_reported_models(item))
    elif isinstance(value, list):
        for item in value:
            models.extend(_extract_reported_models(item))
    return models


def _codex_run_completed(parsed_events: list[dict]) -> bool:
    """Return true when a Codex JSON stream reached a normal turn completion."""
    fatal_event_types = {"error", "turn.failed"}
    if any(event.get("type") in fatal_event_types for event in parsed_events):
        return False
    return any(
        event.get("type") in {"turn.completed", "success"}
        or event.get("status") == "completed"
        for event in parsed_events
    )


def run_cli_agent_interactive(
    sandbox,
    task: dict,
    provider: str,
    model_name: str,
    max_iterations: int,
    traj_dir: Path,
) -> tuple[bool, int, list]:
    """
    Run Claude Code CLI in non-interactive mode with stream-json logging.

    Uses: claude -p --output-format stream-json --verbose

    Captures the complete execution process including thinking, tool calls, and outputs.

    Args:
        sandbox: Docker sandbox instance
        task: Task dictionary
        model_name: Model to use for Claude Code
        max_iterations: Maximum iterations to run
        traj_dir: Directory to save trajectory

    Returns:
        (done, steps, trajectory, model_metadata)
    """
    import shlex

    task_id = task.get("id", "unknown")
    task_prompt = build_task_prompt(task)

    trajectory = []
    start_time = time.time()

    # Create working directory
    work_dir = f"/home/user/claude_work_{task_id}"
    sandbox.commands.run(f"mkdir -p {work_dir}", timeout=10)

    # Set up log file path - use /home/user for codex to avoid auth issues
    if provider == "codex":
        log_file = "/home/user/claude_stream.json"
    else:
        log_file = f"{work_dir}/claude_stream.json"

    # Use model mapping to get the actual model ID
    from evaluation.runtime.model_mapping import get_model_id

    model_id = get_model_id(provider, model_name)
    model_metadata = {
        "requested_model": model_name,
        "resolved_model": model_id,
        "reported_model": None,
        "model_source": "cli_arg",
    }

    print(f"  Provider: {provider}")
    print(f"  Model mapping: {model_name} -> {model_id}")

    # Determine CLI command based on provider
    if provider == "claude":
        cli_command = "claude"
        # Add --model parameter to specify which Claude model to use
        cli_args = f"-p --model {model_id} --output-format stream-json --verbose --dangerously-skip-permissions"
    elif provider == "codex":
        cli_command = "codex"
        # Use --json for JSONL output similar to claude's stream-json
        cli_args = f"exec --json --dangerously-bypass-approvals-and-sandbox -m {model_id}"
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Step 1: Use existing API configuration from Docker image
    print(f"  Using existing API configuration from Docker image...")
    print(f"  Model: {model_name} (will be passed to Claude Code)")

    # Check current config
    config_check_cmd = "cat /home/user/.claude/settings.json 2>/dev/null | python3 -c 'import json,sys; data=json.load(sys.stdin); print(json.dumps(data, indent=2))' 2>/dev/null || cat /home/user/.claude/settings.json 2>/dev/null"
    try:
        config_result = sandbox.commands.run(config_check_cmd, timeout=10)
        print(f"  Docker config (first 300 chars): {config_result.stdout.strip()[:300]}...")
    except:
        pass

    # Do NOT modify the API configuration - use what's in the Docker image
    # The Docker image should have Zhipu API key configured

    # Verify the config
    verify_cmd = "cat /home/user/.claude/settings.json 2>/dev/null"
    try:
        verify_result = sandbox.commands.run(verify_cmd, timeout=10)
        print(f"  Verified config: {verify_result.stdout.strip()}")
    except:
        pass

    # Step 3: Execute the actual task
    # The config file should set the model, but we also set env vars as backup
    prompt_escaped = task_prompt.replace("'", "'\\''")  # Escape single quotes

    # Build CLI command based on provider
    # IMPORTANT: Use shorter timeout (200s) to prevent runaway tasks
    task_timeout = 200

    if provider == "codex":
        # Use exact same format as manual test that worked
        # Don't use env vars in the command, let container environment handle it
        cli_cmd = f"bash -lc 'cd /home/user && echo \"{prompt_escaped}\" | timeout {task_timeout}s codex exec --json --dangerously-bypass-approvals-and-sandbox -m {model_id} 2>&1 | tee {log_file}'"
    else:
        # Wrap entire command in timeout, not just the claude part
        cli_exec_cmd = f"echo '{prompt_escaped}' | {cli_command} {cli_args} 2>&1 | tee {log_file}"
        work_cmd = f"cd {work_dir} && {cli_exec_cmd}"
        # Apply timeout at the bash level, not inside the pipeline
        cli_cmd = f"""timeout {task_timeout}s bash << 'EOF'
set -o pipefail
{work_cmd}
EOF
"""

    try:
        # For codex, wait a bit longer to ensure all services are ready
        if provider == "codex":
            import time as time_module
            print(f"  Waiting for container to fully initialize...")
            time_module.sleep(10)  # Extra wait for codex

            # Debug: Check if codex auth files exist and are readable
            try:
                auth_check = sandbox.commands.run("ls -la ~/.codex/ 2>&1", timeout=10)
                print(f"  Codex directory contents: {auth_check.stdout[:300] if auth_check.stdout else auth_check.stderr[:300]}")

                # Check if auth.json exists
                auth_file_check = sandbox.commands.run("test -f ~/.codex/auth.json && echo 'EXISTS' || echo 'MISSING'", timeout=10)
                print(f"  Auth file status: {auth_file_check.stdout.strip()}")

                if "MISSING" in auth_file_check.stdout:
                    print("  WARNING: Codex auth.json is missing! Trying to restore...")
                    # Try to restore from a backup or reinitialize
                    restore_cmd = "codex login 2>&1 || echo 'Login failed'"
                    restore_result = sandbox.commands.run(restore_cmd, timeout=30)
                    print(f"  Restore result: {restore_result.stdout[:200] if restore_result.stdout else restore_result.stderr[:200]}")
            except Exception as e:
                print(f"  Codex auth check failed: {e}")

        # Execute Claude Code with HARD timeout as failsafe
        # Use 200s for both inner and outer timeout to prevent runaway tasks
        hard_timeout = 200
        print(f"  Starting agent with {task_timeout}s timeout...")
        result = sandbox.commands.run(cli_cmd, timeout=hard_timeout)

        # Try to read and parse the stream-json log
        try:
            log_content = sandbox.files.read(log_file)
            parsed_events = parse_stream_json(log_content)
            reported_models = _extract_reported_models(parsed_events)
            if reported_models:
                model_metadata["reported_model"] = reported_models[-1]
                model_metadata["model_source"] = "provider_event"

            trajectory.append({
                "step": 1,
                "timestamp": datetime.now().isoformat(),
                "type": f"{provider}_execution",
                "events": parsed_events,
                "raw_log": log_content[:10000],  # First 10k chars
                "model_metadata": dict(model_metadata),
            })

            # Check if execution was successful
            # For claude: look for result with subtype success
            # For codex: look for similar success indicators
            if provider == "claude":
                done = any(e.get("type") == "result" and e.get("subtype") == "success" for e in parsed_events)
            else:  # codex
                done = _codex_run_completed(parsed_events)

        except Exception as e:
            # If log parsing fails, use stdout
            trajectory.append({
                "step": 1,
                "timestamp": datetime.now().isoformat(),
                "type": f"{provider}_output",
                "output": result.stdout,
                "stderr": result.stderr,
                "parse_error": str(e),
                "model_metadata": dict(model_metadata),
            })
            done = result.exit_code == 0

        steps = len(trajectory)

    except CommandExitException as exc:
        # Check if this was a timeout
        is_timeout = exc.exit_code == 124  # timeout command returns 124
        trajectory.append({
            "step": len(trajectory),
            "timestamp": datetime.now().isoformat(),
            "type": "execution_error",
            "error": exc.stderr,
            "stdout": exc.stdout,
            "exit_code": exc.exit_code,
            "is_timeout": is_timeout,
            "timeout_reason": "Command exceeded time limit" if is_timeout else None,
        })
        done = False
        steps = len(trajectory)
        if is_timeout:
            print(f"  WARNING: Command timed out after {task_timeout}s (exit code 124)")
    except Exception as exc:
        # Check for timeout-related errors
        error_str = str(exc).lower()
        is_timeout = any(keyword in error_str for keyword in ['timeout', 'timed out', 'deadline exceeded'])
        trajectory.append({
            "step": len(trajectory),
            "timestamp": datetime.now().isoformat(),
            "type": "unexpected_error",
            "error": str(exc),
            "is_timeout": is_timeout,
        })
        done = False
        steps = len(trajectory)
        if is_timeout:
            print(f"  WARNING: Exception indicates timeout: {exc}")

    elapsed = time.time() - start_time

    # Check for excessive execution time (even if no timeout exception was raised)
    max_expected_time = 250  # Allow 50s buffer for cleanup after 200s timeout
    if elapsed > max_expected_time:
        print(f"  WARNING: Execution took {elapsed:.1f}s, exceeding expected {max_expected_time:.1f}s")

    # Summary
    summary = {
        "step": steps + 1,
        "timestamp": datetime.now().isoformat(),
        "type": "summary",
        "elapsed_seconds": elapsed,
        "done": done,
        "total_steps": steps,
        "model_metadata": dict(model_metadata),
        "timeout_config": {
            "timeout_seconds": 200,
        },
        "exceeded_expected_time": elapsed > max_expected_time,
    }
    trajectory.append(summary)

    # Save raw log
    with open(traj_dir / f"{provider}_trajectory.json", "w") as f:
        json.dump(trajectory, f, indent=2, default=str)

    return done, steps, trajectory, model_metadata


def parse_stream_json(content: str) -> list:
    """Parse stream-json output from Claude Code CLI.

    Each line is a separate JSON object.
    Returns a list of parsed events.
    """
    events = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            events.append(event)
        except json.JSONDecodeError:
            # Skip non-JSON lines
            continue
    return events


def parse_claude_output(output: str) -> list:
    """Parse Claude Code CLI output into structured steps.

    This function handles different output formats from Claude Code CLI
    and extracts thinking, tool calls, and results.
    """
    steps = []

    # Try to parse as JSON first
    try:
        data = json.loads(output)
        if isinstance(data, list):
            steps.extend(data)
        elif isinstance(data, dict) and "steps" in data:
            steps.extend(data["steps"])
        else:
            steps.append({"type": "unknown_format", "data": data})
    except json.JSONDecodeError:
        # Not JSON, parse line by line
        lines = output.split("\n")
        current_thinking = []
        in_thinking = False

        for line in lines:
            line = line.strip()

            # Detect thinking markers
            if line.startswith("<thinking>") or line.startswith("Thinking:"):
                in_thinking = True
                current_thinking.append(line)
                continue
            elif line.startswith("</thinking>") or line.startswith("Thinking done"):
                if current_thinking:
                    steps.append({
                        "type": "thinking",
                        "content": "\n".join(current_thinking),
                    })
                    current_thinking = []
                in_thinking = False
                continue

            if in_thinking:
                current_thinking.append(line)
                continue

            # Detect tool calls
            if line.startswith("$") or line.startswith("Running:") or line.startswith("Command:"):
                if current_thinking:
                    steps.append({
                        "type": "thinking",
                        "content": "\n".join(current_thinking),
                    })
                    current_thinking = []

                cmd = line.lstrip("$").lstrip("Running:").lstrip("Command:").strip()
                steps.append({
                    "type": "command",
                    "command": cmd,
                })
            elif line and not line.startswith("#") and not line.startswith("//"):
                # Regular output
                if steps and steps[-1].get("type") == "command":
                    steps[-1]["output"] = steps[-1].get("output", "") + "\n" + line
                else:
                    current_thinking.append(line)

    return steps
