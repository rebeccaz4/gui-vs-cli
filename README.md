# A Unified GUI-CLI Desktop Agent Benchmark

This repository provides a unified desktop-agent benchmark for controlled comparison between GUI agents and skill-mediated CLI agents on real Linux desktop applications. It fixes the task goal, initial state, and final-state verifier across modalities while preserving modality-native action spaces.

The repository ships finalized task definitions, task environment files, application verifiers, a Docker desktop environment, and evaluation runners for both modalities.

The current public benchmark task set is under `task_generator/tasks`. Task generation artifacts are not part of the main workflow.

The bundled `CLI-Anything/` directory is the verifier-guided patched skill set used for CLI-agent evaluation. Its desktop-application workflows were revised against benchmark verifier feedback so that CLI agents are evaluated with the repaired skill interface rather than the original unpatched skill collection.

## Benchmark Contents

- Standard benchmark tasks: `456`
- Grounded-prompt tasks: `176`
  - These are procedure-guided GUI diagnostic tasks. They keep the same initial state, target state, and verifier as the standard tasks, but use more detailed GUI workflow descriptions with cues such as menu paths, dialog confirmations, action order, and exact object names.
- Standard task directory: `task_generator/tasks`
- Grounded task directory: `task_generator/tasks_grounding`
- Default result directory:
  - GUI runs: `evaluation/runs/gui/<run_id>/`
  - CLI runs: `evaluation/runs/cli/<run_id>/`

The standard benchmark currently covers 17 applications plus a cross-application set:

| App | Tasks |
|---|---:|
| Audacity | 24 |
| Chrome | 17 |
| CloudCompare | 23 |
| draw.io | 15 |
| FreeCAD | 30 |
| GIMP | 19 |
| Krita | 17 |
| LibreOffice Calc | 40 |
| LibreOffice Impress | 36 |
| LibreOffice Writer | 44 |
| MuseScore 3 | 25 |
| OBS Studio | 18 |
| Obsidian | 23 |
| RenderDoc | 41 |
| Shotcut | 20 |
| Zoom | 20 |
| Zotero | 26 |
| Cross-app (multi-application workflows) | 18 |

## Repository Layout

```text
unified-gui-cli-desktop-benchmark/
├── agents/                    # GUI-agent implementations and model registry
├── computer_env/              # Docker/E2B environment backends
│   └── provision/docker/      # Dockerfile and desktop startup scripts
├── evaluation/
│   ├── apps/                  # App launch, save, and ready-check specs
│   ├── runtime/               # Shared task, sandbox, verifier, and reporting code
│   ├── run_eval.py            # GUI evaluation runner
│   └── run_cli_eval.py        # CLI evaluation runner
├── task_generator/
│   ├── tasks/                 # 456 standard benchmark task directories
│   └── tasks_grounding/       # 176 grounded-prompt task directories
├── verifiers/                 # App-specific verifier CLIs
├── E2B/                       # Vendored E2B Python SDK dependency
├── desktop/                   # Vendored E2B desktop SDK dependency
├── CLI-Anything/              # Verifier-guided patched CLI workflows for CLI-agent evaluation
├── requirements.txt
└── .env.example
```

Each task directory has this shape:

```text
task_generator/tasks/<task_id>/
├── task.json
├── env_manifest.json
└── env/                       # Seed files copied into the sandbox
```

`task.json` contains the app name, natural-language task, environment setup metadata, and verifier commands.

## Requirements

- Docker with Linux container support.
- Python 3.10 or newer. Python 3.11 is recommended.
- Enough local disk space for a large desktop Docker image.
- API credentials for the agent models you plan to evaluate.
- For CLI evaluation, a Docker image where Claude Code and/or Codex are installed and logged in.

Install host-side Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Create a local `.env` if you use hosted API agents:

```bash
cp .env.example .env
```

Fill only the keys you need. `.env` is gitignored.

## Docker Images

The benchmark uses two Docker image roles:

- `paraverse-desktop:latest`: base desktop image with applications, desktop services, and verifier dependencies.
- `paraverse-agent-runtime:latest`: agent-ready image created from the desktop image after manually installing/logging in the agent runtimes needed for the selected modality.

Build the base desktop image:

```bash
bash computer_env/provision/docker/build_image.sh paraverse-desktop:latest
```

The Dockerfile targets `linux/amd64`.

### Prepare The Agent Image

For GUI-only API agents, the base desktop image can be enough if credentials are supplied through `.env` or command-line arguments.

For CLI evaluation, first create an agent-ready image:

1. Start a container from the base desktop image.
2. Open the noVNC desktop URL printed by Docker or by the evaluation runner.
3. Install Claude Code and/or Codex inside the container.
4. Complete login/authentication inside the container.
5. Verify that the commands are available:

```bash
which claude
which codex
```

6. Commit the configured container:

```bash
docker commit <container_id> paraverse-agent-runtime:latest
```

Use `paraverse-agent-runtime:latest` for evaluation commands below.

## Run GUI Evaluation

List apps and models:

```bash
python evaluation/run_eval.py --list-apps
python evaluation/run_eval.py --list-models
```

Run one smoke task per app using Docker:

```bash
python evaluation/run_eval.py \
  --env-backend docker \
  --docker-image paraverse-agent-runtime:latest \
  --one-task-per-app \
  --model gpt-5.4 \
  --output-dir smoke-gui
```

Run a single task:

```bash
python evaluation/run_eval.py \
  --env-backend docker \
  --docker-image paraverse-agent-runtime:latest \
  --app chrome \
  --task chrome_form_fill_httpbin \
  --model gpt-5.4 \
  --output-dir chrome-test
```

Run grounded prompts:

```bash
python evaluation/run_eval.py \
  --env-backend docker \
  --docker-image paraverse-agent-runtime:latest \
  --tasks-dir task_generator/tasks_grounding \
  --task-field task_grounding \
  --one-task-per-app \
  --model gpt-5.4 \
  --output-dir grounding-smoke
```

## Run CLI Evaluation

CLI evaluation runs inside Docker and expects the chosen CLI agent to already be installed and authenticated in the image.

List CLI tasks:

```bash
python evaluation/run_cli_eval.py --list-tasks
```

Run one task per app with Codex:

```bash
python evaluation/run_cli_eval.py \
  --provider codex \
  --model gpt-5.5 \
  --docker-image paraverse-agent-runtime:latest \
  --tasks-per-app 1 \
  --output-dir smoke-codex
```

Run one task per app with Claude Code:

```bash
python evaluation/run_cli_eval.py \
  --provider claude \
  --model opus-4.7 \
  --docker-image paraverse-agent-runtime:latest \
  --tasks-per-app 1 \
  --output-dir smoke-claude
```

## Outputs

Each task produces a trajectory directory:

```text
evaluation/runs/gui/<run_id>/trajectories/<task_id>/trajectory.json
evaluation/runs/cli/<run_id>/trajectories/<task_id>/trajectory.json
```

The trajectory records the task text, agent actions, verifier details, reward, elapsed time, and errors if any.

Run directories are gitignored by default.

## Useful Evaluation Options

Common GUI runner options:

```bash
--app <app_id>
--task <task_id>
--model <model_alias>
--tasks-dir <path>
--task-field task|task_grounding
--parallel <N>
--resume <run_id>
--output-dir <name>
--skip-completed true|false
--ready-check-only
```

Common CLI runner options:

```bash
--provider claude|codex
--model <model_name>
--app <app_id>
--task <task_id>
--tasks-per-app <N>
--parallel <N>
--resume <run_id>
--output-dir <name>
--skip-completed true|false
--docker-image <image>
```

## Configuration

Configuration is read from environment variables and `.env`.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI-compatible agents and judge calls |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible endpoint override |
| `ANTHROPIC_API_KEY` | Claude API agents |
| `E2B_API_KEY` | E2B backend, if used |
| `EVAL_MODEL` | Default GUI model |
| `EVAL_MAX_ITERATIONS` | Max GUI agent steps per task |
| `EVAL_SANDBOX_TIMEOUT` | Sandbox timeout in seconds |
| `DOCKER_ENV_IMAGE` | Default Docker image |
| `DOCKER_ENV_PLATFORM` | Docker platform, usually `linux/amd64` |
| `DOCKER_ENV_SHM_SIZE` | Docker shared memory size |
