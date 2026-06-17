# Task Extension Workflow

Use this workflow when an app's current tasks leave important functionality uncovered.

## Goal

Find meaningful coverage gaps, document them, and add tasks that close them.

## Inputs

- existing tasks in `task_generator/tasks/`
- `task_generator/CLAUDE.md`
- `task_generator/LESSONS.md`
- `verifiers/<app>/README.md`
- `task_generator/tasks/COVERAGE_GAPS.md` if it already exists

## Process

1. Review the existing tasks for each app and group them by feature area.
2. Identify major workflows that are missing, weakly covered, or overly repetitive.
3. Write or update `task_generator/tasks/COVERAGE_GAPS.md` with:
   - what is already covered
   - what is missing
   - why the gap matters
   - whether it looks verifiable
4. Choose the apps with the largest useful gaps and realistic verification paths.
5. Generate roughly 10 new tasks per selected app, adjusting up or down as needed.
6. Follow `task_generator/CLAUDE.md` to evaluate, verify, and finalize those tasks.

## Rules

- Prefer meaningful workflow gaps, not cosmetic variations.
- Do not create filler tasks just to hit a number.
- Avoid near-duplicates of existing tasks.
- Keep a reasonable spread of difficulty and feature coverage.
- If a good task needs a new verifier endpoint, follow `task_generator/ENDPOINT_EXTENSION.md`.

## Outputs

- updated `task_generator/tasks/COVERAGE_GAPS.md`
- new task folders under `task_generator/tasks/<task_id>/`
- updated combined app task files if needed
