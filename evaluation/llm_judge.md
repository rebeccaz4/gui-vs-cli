# LLM-as-Judge Evaluation

When using an LLM (Claude) as a judge to evaluate whether a task was completed successfully, follow this process:

## Step 1: Read Trajectory Traces

Read the full trajectory traces (reasoning and actions) from the agent's execution. Use these traces to:

- Understand the sequence of steps the agent took.
- Determine which screenshots are most relevant for verifying task success.

### Screenshot–Action Mapping

The naming convention follows this rule:

- `step_N.png` is the screenshot the agent **observed before** producing `step_N.json`.
- `step_N.json` contains the agent's reasoning and action based on that observation.
- The **result** of executing the action in `step_N.json` is visible in `step_(N+1).png`.

For example: the agent sees `step_001.png`, reasons and acts in `step_001.json`, and the outcome of that action is captured in `step_002.png`. So when you want to verify whether a particular action succeeded, read the **next** screenshot (N+1), not the one with the same number.

## Step 2: Read Selected Screenshots + Final Screenshots

Based on the trajectory analysis, read:

1. **Key step screenshots** — the images identified in Step 1 as most informative for verifying specific sub-tasks or checker conditions.
2. **Final 3 screenshots** — always include the last 3 screenshots from the execution to capture the end state of the application.

For evaluation flows that apply post-agent save logic, remember that the harness may send a save shortcut after the agent stops and before verification/final-state capture. For save-dependent or file-based criteria, do not fail a check only because the agent itself never explicitly pressed save; judge the final persisted end state after any harness save attempt, and only mark failure when there is concrete evidence the state is still unsaved or stale.

## Step 3: Read the Checker

Read the checker (verifier) for the task. The checker defines the list of conditions that must be satisfied for the task to be considered complete.

## Step 4: Evaluate Each Checker Condition

Using the screenshots and trajectory context, determine for each condition in the checker:

- **Finished** — the condition is visually confirmed as met in the screenshots.
- **Not finished** — the condition is not met or cannot be confirmed from the available evidence.

Report the result per condition so it is clear exactly which parts of the task succeeded and which did not.

## Required Output Format

The LLM judge **must** output a JSON object in the following format (and nothing else outside the JSON):

```json
{
  "checks": [
    {
      "description": "Description of the checker condition",
      "passed": true,
      "reasoning": "Brief explanation of why this check passed or failed based on the screenshots and trajectory"
    },
    {
      "description": "Another checker condition",
      "passed": false,
      "reasoning": "Brief explanation..."
    }
  ],
  "summary": "One-sentence overall assessment of the task completion"
}
```

- `checks` — one entry per verification condition in the task's checker, in the same order. Each has:
  - `description` — the checker condition description (copied from the task)
  - `passed` — `true` if the condition appears met from visual/trajectory evidence, `false` otherwise
  - `reasoning` — brief explanation of the evidence used to make the judgment
- `summary` — a one-sentence overall assessment
