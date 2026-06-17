# cli-anything-eth2-quickstart Test Plan

## Unit

- repo root detection from explicit path and environment
- config file upsert behavior
- CLI help and JSON output
- phase 2 command construction
- validator guidance generation
- status and health aggregation with mocked subprocess results

## E2E

- skip automatically when no real `eth2-quickstart` checkout is configured
- verify wrapper discovery
- verify read-only commands (`help`, `health-check`) against a real checkout

## Latest Pytest Results

### Unit

```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-7.4.4, pluggy-1.4.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /root/.openclaw/workspace/dev/CLI-Anything/eth2-quickstart/agent-harness
plugins: anyio-4.12.1
collecting ... collected 18 items

cli_anything/eth2_quickstart/tests/test_core.py::TestProjectHelpers::test_find_repo_root_from_explicit_path PASSED [  5%]
cli_anything/eth2_quickstart/tests/test_core.py::TestProjectHelpers::test_find_repo_root_from_env PASSED [ 11%]
cli_anything/eth2_quickstart/tests/test_core.py::TestProjectHelpers::test_upsert_user_config PASSED [ 16%]
cli_anything/eth2_quickstart/tests/test_core.py::TestValidatorPlan::test_prysm_plan PASSED [ 22%]
cli_anything/eth2_quickstart/tests/test_core.py::TestValidatorPlan::test_invalid_client PASSED [ 27%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_help PASSED [ 33%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_missing_repo_root_returns_clean_json_error PASSED [ 38%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_health_check_json PASSED [ 44%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_install_clients_json PASSED [ 50%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_install_clients_rejects_unknown_execution_client PASSED [ 55%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_setup_node_auto_with_network_only_uses_ensure PASSED [ 61%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_setup_node_auto_with_client_selection_uses_phase2 PASSED [ 66%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_start_rpc_requires_confirm PASSED [ 72%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_configure_validator_json PASSED [ 77%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_configure_validator_rejects_unknown_consensus_client PASSED [ 83%]
cli_anything/eth2_quickstart/tests/test_core.py::TestCLI::test_status_json PASSED [ 88%]
cli_anything/eth2_quickstart/tests/test_core.py::TestBackendErrors::test_run_handles_missing_wrapper PASSED [ 94%]
cli_anything/eth2_quickstart/tests/test_core.py::TestBackendErrors::test_run_handles_permission_error PASSED [100%]

============================== 18 passed in 0.07s ==============================
```

### E2E

```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-7.4.4, pluggy-1.4.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /root/.openclaw/workspace/dev/CLI-Anything/eth2-quickstart/agent-harness
plugins: anyio-4.12.1
collecting ... collected 3 items

cli_anything/eth2_quickstart/tests/test_full_e2e.py::TestRealCheckoutE2E::test_help SKIPPED [ 33%]
cli_anything/eth2_quickstart/tests/test_full_e2e.py::TestRealCheckoutE2E::test_health_check_json SKIPPED [ 66%]
cli_anything/eth2_quickstart/tests/test_full_e2e.py::TestRealCheckoutE2E::test_status_json SKIPPED [100%]

============================== 3 skipped in 0.02s ==============================
```
