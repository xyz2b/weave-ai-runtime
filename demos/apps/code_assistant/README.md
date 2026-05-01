# AI Coding Shell MVP

Run every command from the repository root.

This app is the repository's first AI coding shell MVP. It keeps the durable live-runtime path from the earlier demo, but the main surface is now an interactive host shell built from four layers:

- `host`: shell loop, local commands, approvals, event rendering
- `tool`: bundled coding tools plus an app-specific `bash` replacement
- `agent`: `code-assistant`, `coding-planner`, `reviewer`, and `verifier`
- `skill`: coding discipline and reusable workflow skills

## Prerequisites

Required:

- `OPENAI_API_KEY`

Optional overrides:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

If `OPENAI_API_KEY` is missing, the app still uses the bundled live route and surfaces the provider auth failure directly.

## Mutable state model

The fixture is immutable:

- `demos/apps/code_assistant/fixtures/mini_repo/`

The live app edits a generated mutable workspace:

- `demos/apps/code_assistant/state/mini_repo/`

The mutable workspace also stores durable runtime artifacts under `state/mini_repo/.weavert/`, including transcripts, child runs, task lists, jobs, and memory.

## Primary shell path

Reset the mutable workspace first:

```bash
python3 -B -m demos.apps.code_assistant reset
```

Start the interactive shell:

```bash
python3 -B -m demos.apps.code_assistant shell
```

Use automatic approvals when you want a non-interactive shell session:

```bash
python3 -B -m demos.apps.code_assistant shell --auto-approve
```

The shell keeps one session alive across multiple prompts and supports local commands that do not spend model turns:

- `/help`
- `/inspect`
- `/resume`
- `/tasks`
- `/jobs`
- `/review`
- `/verify`
- `/exit`

## Scripted smoke path

The deterministic smoke path still exists and uses the same workspace layout, runtime config, and durable-state conventions as the shell:

```bash
python3 -B -m demos.apps.code_assistant run
```

Harness mode:

```bash
python3 -B -m demos.apps.code_assistant run --auto-approve
```

Stable session id:

```bash
python3 -B -m demos.apps.code_assistant run \
  --session-id live-smoke \
  --auto-approve
```

## Approval behavior

The host uses the ordinary permission path for `edit`, `write`, and `bash`.

- default mode: prompts on each write or shell action
- `--auto-approve`: keeps the same runtime assembly and provider path, but pre-answers host approvals for harness-style runs

## Coding surfaces

The app reuses bundled runtime tools for the main coding loop:

- `read`, `glob`, `grep`, `edit`, `write`
- `agent`, `skill`
- `task_*`, `job_*`

Only `bash` is replaced locally for this app. The replacement keeps the public tool name `bash`, but adds:

- command classification for coding-oriented shell work
- workspace-aware guardrails and clearer high-risk summaries
- structured stdout or stderr previews
- background job projection for long-running commands

## Deferred scope

This MVP intentionally does not try to solve broader product surfaces yet. The following remain deferred:

- plugins and plugin marketplaces
- MCP integration
- IDE bridges
- worktree automation
- broader permissions product work

## Inspect and reset story

Inspect the current durable state:

```bash
python3 -B -m demos.apps.code_assistant inspect
```

`inspect` summarizes:

- transcript sessions
- child-run state
- shared task lists
- memory root and document count

`reset` deletes the mutable workspace and recreates it from the pristine fixture. That clears live edits and durable runtime artifacts together.

## Manual live smoke path

A manual live smoke run that preserves the bundled live model route is:

```bash
export OPENAI_API_KEY=your-key
python3 -B -m demos.apps.code_assistant reset
python3 -B -m demos.apps.code_assistant run --session-id live-smoke --auto-approve
python3 -B -m demos.apps.code_assistant inspect
```

You should see all of the following:

- host approval handling, unless `--auto-approve` is used
- a durable transcript at `demos/apps/code_assistant/state/mini_repo/.weavert/transcripts/live-smoke.jsonl`
- child-run records for `coding-planner`, `reviewer`, and `verifier`
- a shared task list whose id starts with `session:live-smoke`
- a structured `bash` verification result
- `notes/live_demo.md` created inside the mutable workspace
