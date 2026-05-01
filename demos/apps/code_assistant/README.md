# Live Code Assistant App Demo

Run every command from the repository root.

This demo is the first app-shaped live workflow in the repository. Unlike the offline seam and project demos, it uses the bundled full runtime, enters through `bind_host()`, and targets the bundled `openai_default` route by default.

## Prerequisites

Required:

- `OPENAI_API_KEY`

Optional overrides:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

If `OPENAI_API_KEY` is missing, the demo stays a live app demo and surfaces the bundled `auth_error` instead of falling back to the scripted offline helper.

## Mutable state model

The fixture is immutable:

- `demos/apps/code_assistant/fixtures/mini_repo/`

The live app edits a generated mutable workspace:

- `demos/apps/code_assistant/state/mini_repo/`

The mutable workspace also holds durable runtime artifacts under `state/mini_repo/.weavert/`, including transcripts, child runs, task lists, team state, and memory.

## Canonical workflow

Reset the mutable workspace first:

```bash
python3 -B -m demos.apps.code_assistant reset
```

Run the live app with the canonical prompt and interactive approvals:

```bash
python3 -B -m demos.apps.code_assistant run
```

Run the same flow in harness mode with automatic approvals:

```bash
python3 -B -m demos.apps.code_assistant run --auto-approve
```

Use a stable session id when you want predictable transcript and task-list paths:

```bash
python3 -B -m demos.apps.code_assistant run \
  --session-id live-smoke \
  --auto-approve
```

Inspect durable state after one or more runs:

```bash
python3 -B -m demos.apps.code_assistant inspect
```

## Approval behavior

The app binds a host and uses the host permission path for `edit`, `write`, and `bash` actions.

- default mode: prompts on each write or shell action
- `--auto-approve`: keeps the same runtime assembly and provider path, but pre-answers host approvals for non-interactive smoke runs

The host also captures notifications, terminal events, and reviewer or verifier child-run events so the demo exercises the ordinary host bridge instead of a bare helper call.

## What the default prompt does

The built-in prompt asks the assistant to:

1. fix the failing greeting test in the mutable mini repo
2. write a short `notes/live_demo.md` file
3. run `python3 -m unittest discover -s tests`
4. ask the `reviewer` child agent for a quick review
5. ask the `verifier` child agent to confirm the verification result
6. keep the shared task list current while working

That gives the live path a small but real coding shape: `read`, `grep`, `edit`, `write`, `bash`, planning, and child-agent execution against a durable workspace.

## Inspect and reset story

`inspect` summarizes:

- persistence profile
- transcript sessions and transcript file locations
- child-run sessions
- task-list snapshots
- the memory root and current document count

`reset` deletes the mutable workspace and recreates it from the pristine fixture. That intentionally clears live edits and durable runtime artifacts together so the demo always has a predictable fresh start.

## Manual live smoke path

A manual end-to-end smoke run is:

```bash
export OPENAI_API_KEY=your-key
python3 -B -m demos.apps.code_assistant reset
python3 -B -m demos.apps.code_assistant run --session-id live-smoke
python3 -B -m demos.apps.code_assistant inspect
```

You should see all of the following:

- one or more approval prompts, unless `--auto-approve` is used
- a durable transcript at `demos/apps/code_assistant/state/mini_repo/.weavert/transcripts/live-smoke.jsonl`
- reviewer and verifier child-run records
- a task list whose id starts with `session:live-smoke`
- the greeting test command reported as successful
- `notes/live_demo.md` created inside the mutable workspace
