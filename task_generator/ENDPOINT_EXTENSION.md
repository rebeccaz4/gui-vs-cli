# Endpoint Extension Workflow

When a proposed task has no matching verifier endpoint, do **not** automatically discard it. Instead, attempt to extend the verifier:

1. **Identify the verification channel.** Determine whether the task's outcome is inspectable at all — is there a file on disk, a config/preference file, an IPC/API channel (CDP, D-Bus, UNO, AT-SPI), a SQLite database, or any other programmatic way to read the state? If no channel exists (the app provides zero ways to read this state), skip to step 6.

2. **Design the endpoint.** Following the patterns in `verifiers/CLAUDE.md`, design a new `check-*` (or query) endpoint that reads the relevant state and returns JSON. Model it on existing endpoints in `verifiers/<app>/<app>.py`.

3. **Implement the endpoint.** Add the new endpoint to `verifiers/<app>/<app>.py`. Follow the same conventions: JSON to stdout, `{"error": "..."}` on failure, one primary boolean key for `check-*` endpoints.

4. **Generate synthetic test data.** If the endpoint needs test fixtures (a config file, a document with specific content, etc.), create them following the fixture guidelines in `verifiers/CLAUDE.md` section 3c. Upload them to the sandbox during testing.

5. **Test the endpoint.** Add test cases to `verifiers/<app>/test_<app>.py` covering:
   - Positive case (condition is true)
   - Negative case (condition is false)
   - Error case (app not running, bad args)
   - JSON validity

   Run `python verifiers/<app>/test_<app>.py` and enter the debug-fix-retry loop from `verifiers/CLAUDE.md` (up to 5 retries). Update `Test.md` and `README.md` to document the new endpoint.

   **If tests pass:** The endpoint is live. Update `verifiers/<app>/README.md` with the new endpoint reference. The task proposal can now use it — proceed with the task.

   **If tests fail after 5 retries:** The endpoint is not viable. Proceed to step 6.

6. **Log unverifiable tasks.** If no verification channel exists (step 1) or the endpoint cannot be made to work (step 5), delete the task proposal and append an entry to `task_generator/unverifiable_<app>.md` with:
   - Task ID and objective
   - What verification was attempted (channel, endpoint design)
   - Why it failed (no channel exists / endpoint unreliable / test failures)
   - Date

   This file is for the human operator to review — some tasks may become verifiable later if the app adds new APIs or the verifier is extended through other means.

**Scope guard:** Only extend the verifier for endpoints that serve the task's *main goal*. Do not add endpoints for minor cosmetic checks or criteria that can be dropped without weakening the task. The point is to unlock genuinely useful tasks that the verifier happens to not cover yet, not to bloat the verifier with one-off checks.
