# Verifier Repair Pipeline

Iteratively repair broken verification scripts for generated tasks. One persistent E2B sandbox per task — the agent runs once, an LLM judge produces ground truth from the trajectory, and the verifier script is re-run and compared against the judge. When they disagree, a headless Claude Code invocation edits the verifier (or the task's verification entries) and the loop re-verifies **without re-running the agent**. Up to 3 rounds per task.

All reasoning stages (judge, disagreement analysis, repair) are spawned as `claude -p` subprocesses. This file's Python code only owns the sandbox and wires stages together.

## Files

```
evaluation/repair/
├── README.md              # This file
├── repair_loop.py         # Orchestrator (CLI entry point)
├── prompts/
│   ├── judge.md           # Stage B — LLM-as-judge ground truth
│   ├── comparator.md      # Stage D — classify script↔judge disagreements
│   └── repair.md          # Stage E — edit verifier / task.json
└── runs/
    └── <task_id>_<ts>/
        ├── trajectory/          # Agent screenshots + trajectory.json
        ├── judge/
        │   ├── llm_judge.json   # Ground truth (written once)
        │   └── judge_cc.log     # Prompt + CC stdout/stderr
        ├── round_0/
        │   ├── script_result.json
        │   ├── llm_judge.json         # copy of judge/llm_judge.json
        │   ├── disagreements.json     # Comparator output
        │   ├── repair_log.md          # Repair agent's edit log
        │   ├── comparator_cc.log
        │   └── repair_cc.log
        ├── round_1/ ...
        ├── round_2/ ...
        └── SOLVED.md             # Final human-readable summary
```

## Pipeline stages

| Stage | What runs | Inputs | Output |
|---|---|---|---|
| A | Python (orchestrator) | `task.json` | Open sandbox, upload env + verifier, launch app, run kimi agent, save trajectory |
| B | `claude -p` (`judge.md`) | trajectory screenshots + criteria | `judge/llm_judge.json` — ground-truth pass/fail per criterion, with reasoning |
| C | Python (orchestrator) | live sandbox + current `task.json` | `round_N/script_result.json` |
| D | `claude -p` (`comparator.md`) | script result + judge result + trajectory | `round_N/disagreements.json` — classified, with suggested fixes |
| E | `claude -p` (`repair.md`) | disagreements + task + verifier | Edits applied to `task.json` and/or `verifiers/<app>/`; `round_N/repair_log.md` |
| F | Python (orchestrator) | edited verifier | Re-upload verifier to sandbox; loop back to C |
| G | Python (orchestrator) | all rounds | `SOLVED.md` |

Early-exit after any round where the verifier agrees with the judge on every non-LLM-judged criterion.

## The `SOLVED.md` report

Per task, written after the loop finishes. Contains:

- Task metadata (id, app, agent model, whether the agent marked DONE, step count)
- The full LLM judge verdict (pass/fail + reasoning per criterion) — this is the ground truth you can trust
- One section per round with:
  - Script result summary (passed/failed/llm-judged counts)
  - Mechanical divergences vs. the judge
  - Comparator's classifications and suggested fixes
  - Collapsible repair log
- Final state — either "all reconciled ✅" or a list of unresolved divergences that need manual review

## Stage ownership

**The sandbox is held by the Python orchestrator and only the orchestrator.** Headless reasoning stages (claude or codex) are pure file-I/O — they read logs, edit files on disk, and exit. They never talk to the sandbox directly. This is why the sandbox can stay open across rounds at zero complexity cost: nothing else knows it exists.

**The judge runs exactly once** (not per round). The trajectory doesn't change between rounds — only the verifier does — so re-judging would waste tokens and introduce noise.

## What the repair stage is allowed to change

| Classification | Allowed edit targets |
|---|---|
| `script_wrong` | `task.json` verification entry (command, key, expected, eval, or convert to `judge:llm`) |
| `script_missing_endpoint` | Add endpoint to `verifiers/<app>/<app>.py` + update README, OR add task-local `verify_helper.py` |
| `task_description_ambiguous` | Tighten `task.json` description/criterion text |
| `judge_wrong` | Nothing — logged only |
| `agent_false_success` | Whatever fixes the false positive (highest priority) |

In addition, when any round produces a **generalizable insight** for future task authoring, the repair agent appends a single markdown bullet to `task_generator/LESSONS.md` under the app's heading (creating the heading if missing). This is an append-only, fire-and-forget write — the agent does not read the existing lessons, so it cannot regress them. Lessons are skipped when the round was a pure typo fix, was all `judge_wrong`, or the insight is already captured.

Every headless stage runs in YOLO mode (Claude: `--dangerously-skip-permissions`; Codex: `--dangerously-bypass-approvals-and-sandbox`), so all tools are available in both backends. The prompt itself is what tells the repair agent to stay within `task.json`, the task directory, and the target verifier — honor-system, not enforced by CLI flags. Tighten via `--allowedTools` (claude) or equivalent sandbox flags (codex) in `call_claude_code()` if you need hard scoping later.

## Usage

`--app` is **optional** — if omitted, the loop auto-detects the app from `task.json["app"]`. Every app referenced by any `task.json` under `task_generator/tasks/` is supported (the supported set is exactly `APP_CONFIGS` in `evaluation/run_eval.py`; `--list-apps` prints it).

```bash
# Single task — app auto-detected from task.json
python evaluation/repair/repair_loop.py --task blender_animated_object

# LibreOffice tasks: prefix is calc_/draw_/impress_/writer_, app key is libreoffice_*.
# You no longer need to know that mapping — just pass --task.
python evaluation/repair/repair_loop.py --task calc_class_roster_grade_band

# Override the auto-detected app (rarely needed; emits a warning)
python evaluation/repair/repair_loop.py --task blender_animated_object --app blender

# Codex backend instead of Claude
python evaluation/repair/repair_loop.py --task blender_animated_object --backend codex

# Tune rounds / agent iterations
python evaluation/repair/repair_loop.py \
    --task calc_class_roster_grade_band \
    --max-rounds 3 --max-iterations 60

# See every app the repair loop accepts
python evaluation/repair/repair_loop.py --list-apps
```

## Reasoning backends

The judge, comparator, and repair stages all shell out to a headless CLI. Two backends are supported; both run with full permissions (no sandboxing, no approval prompts).

| Backend | Binary | Invocation | YOLO flag |
|---|---|---|---|
| `claude` (default) | `claude` | `claude -p "<prompt>"` | `--dangerously-skip-permissions` |
| `codex` | `codex` | `codex exec "<prompt>"` | `--dangerously-bypass-approvals-and-sandbox` |

The pipeline is backend-agnostic: each stage writes its output to a specific file path (`llm_judge.json`, `disagreements.json`, `repair_log.md`), and the orchestrator checks for that file's existence rather than parsing stdout. Prompts are the same for both backends — the first real Codex run may need minor prompt tuning if Codex is less strict about the "print only `REPAIR_DONE`" convention.

Environment overrides (all optional):
- `REPAIR_BACKEND` — default reasoning backend (`claude` or `codex`)
- `REPAIR_MODEL` — default GUI agent model (default `kimi-k2.5`)
- `REPAIR_MAX_ITERATIONS` — default max agent steps
- `REPAIR_MAX_ROUNDS` — default max repair rounds
- `REPAIR_SANDBOX_TIMEOUT` — default sandbox lifetime seconds (repair loops are long — default 3600)
- `CLAUDE_BIN` — path to the `claude` CLI binary (default `claude`)
- `CODEX_BIN` — path to the `codex` CLI binary (default `codex`)

## Assumptions / invariants

- **Verifier is idempotent.** Running a verification command twice against the same sandbox state returns the same result. If this is ever violated, add explicit state-reset steps to the offending verifier endpoint, not to this pipeline.
- **Only one task per run.** Running a batch is just shell-loop this script; each task gets a fresh sandbox.
- **LLM judge is the oracle.** When script and judge disagree, default to script-wrong unless the comparator finds clear trajectory evidence that the judge misread the screenshots.
- **Repair cannot touch agents, evaluation infrastructure, or cross-app verifiers.** The tool scope and the prompt both forbid this.

## Not (yet) implemented

- Batch mode with per-app rollup report (run in a shell loop for now)
- Re-judging after task description changes (currently the judge verdict is frozen after stage B; if a `task_description_ambiguous` repair rewrites criteria significantly, consider re-running the task from scratch rather than trusting the round-0 judge)
- Automatic escalation when a repair round increases divergences instead of decreasing them
