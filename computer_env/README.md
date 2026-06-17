# Computer Env

`computer_env/` is the environment layer for GUI task execution.

- `backends/` contains runtime adapters
- `provision/` contains backend-specific setup/build assets

## Setup Docker Backend

Build the Docker desktop image.

From the repository root:

```bash
bash computer_env/provision/docker/build_image.sh
```

## Docker Cleanup CLI

List or clean up Docker containers managed by `gui-synth-env`:

```bash
python -m computer_env.backends.docker.cleanup_containers
python -m computer_env.backends.docker.cleanup_containers --state running
python -m computer_env.backends.docker.cleanup_containers --metadata run_id=<run_id>
python -m computer_env.backends.docker.cleanup_containers --force
```

## Setup E2B Backend

Build the all-apps E2B template.

From the repository root:

```bash
python computer_env/provision/e2b/build_all_apps_template.py
```

## E2B Sandbox CLI

Open or resume an E2B sandbox from the local sandbox registry:

```bash
python -m computer_env.backends.e2b.sandbox_cli --list
python -m computer_env.backends.e2b.sandbox_cli <sandbox_id>
```

The sandbox registry defaults to:

```text
~/.config/gui-synth-env/e2b/sandboxes.json
```

Override it with `GUI_SYNTH_E2B_SANDBOXES_FILE` if needed.

To list or clean up active E2B sandboxes in your account:

```bash
python -m computer_env.backends.e2b.cleanup_sandboxes
python -m computer_env.backends.e2b.cleanup_sandboxes --force
```
