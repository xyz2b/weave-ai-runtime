# Reactive AI Coding Shell V2

Run every command from the repository root.

This app is the repository's reactive V2 AI coding shell. It keeps the durable live-runtime path from the earlier demo, but now combines an interactive `bash v2` surface, reactive runtime observability, and an app-owned workflow ledger on top of the same host, agent, tool, and skill composition:

- `host`: shell loop, local commands, approvals, reactive job or task rendering, workflow warnings and advisories
- `tool`: bundled coding tools plus the app-specific `bash v2` replacement
- `agent`: `code-assistant`, `coding-planner`, `reviewer`, and `verifier`
- `skill`: coding discipline and reusable plan, verify, and review workflow skills

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

The shell keeps one runtime session alive across multiple prompts, reactively renders task or job updates from runtime watchers, and supports local commands that do not spend model turns:

- `/help`
- `/inspect`
- `/resume`
- `/tasks`
- `/jobs`
- `/review`
- `/verify`
- `/exit`

The app-local `bash` replacement keeps the public tool name `bash`, but the V2 contract now supports:

- one-shot `exec` behavior for existing short commands
- `start`, `send`, `read`, `interrupt`, and `stop` actions for longer-lived shell sessions
- shared job visibility and structured shell-session metadata
- explicit unsupported outcomes for full-screen terminal UIs such as `vim`, `less`, or `top`

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

The live `run` path now succeeds when the workflow leaves a real planning outcome, inspects the repo before the first material edit, verifies the latest revision, reviews the latest revision, and returns a final summary. If the planner degrades after leaving a usable shared plan, the command still succeeds and prints that condition as a non-blocking `workflow advisories` entry.

## Approval behavior

The host uses the ordinary permission path for `edit`, `write`, and `bash`.

- default mode: prompts on each write or shell action
- `--auto-approve`: keeps the same runtime assembly and provider path, but pre-answers host approvals for harness-style runs

## Coding surfaces

The app reuses bundled runtime tools for the main coding loop:

- `read`, `glob`, `grep`, `edit`, `write`
- `agent`, `skill`
- `task_*`, `job_*`

Only `bash` is replaced locally for this app. The V2 replacement keeps the public tool name `bash`, while adding:

- command classification for coding-oriented shell work
- workspace-aware guardrails and clearer high-risk summaries
- structured stdout or stderr previews
- background or session-oriented job projection for longer-lived commands
- line-oriented shell-session lifecycle support through `start`, `send`, `read`, `interrupt`, and `stop`

## Workflow ledger

The host computes a workflow ledger from durable runtime-owned signals:

- `clean`
- `pending_verification`
- `pending_review`
- `ready_to_summarize`

Successful `edit` or `write` results advance the change revision and invalidate older verification or review coverage. Successful verification outcomes and successful reviewer or verifier summaries move the session forward again. `/inspect` and the interactive shell both show this state without spending another model turn.

## Reliable success contract

The app now separates blocking workflow failures from visible-but-non-blocking degradation:

- `workflow gaps`: blocking failures such as missing planner outcome, missing pre-edit inspection, or missing latest-revision verification or review coverage
- `workflow advisories`: non-blocking diagnostics such as the planner hitting `max_turns` after it already left a usable shared task plan

The planner contract for the default live task is intentionally narrow: inspect the shared task list first, inspect only the files needed for the greeting change, leave a visible shared task plan, and then return a concise summary. The workspace-local planner definition uses `maxTurns: 8`, and the live prompt now tells the parent agent to invoke the planner with `max_turns: 8` so the effective planner budget is no longer capped lower at runtime.

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

A manual V2 smoke run that preserves the bundled live model route is:

```bash
export OPENAI_API_KEY=your-key
python3 -B -m demos.apps.code_assistant reset
python3 -B -m demos.apps.code_assistant shell --session-id live-smoke --auto-approve
python3 -B -m demos.apps.code_assistant inspect
```

You should see all of the following:

- host approval handling, unless `--auto-approve` is used
- reactive task or job updates while the shell is live
- workflow state lines such as `pending_verification` or `pending_review`
- `workflow advisories` only when the workflow materially succeeds but the planner still degraded
- a durable transcript at `demos/apps/code_assistant/state/mini_repo/.weavert/transcripts/live-smoke.jsonl`
- child-run records for `coding-planner`, `reviewer`, and `verifier`
- a shared task list whose id starts with `session:live-smoke`
- structured `bash` verification results and shell-session metadata
- `notes/live_demo.md` created inside the mutable workspace

## Acceptance checklist

- unsupported TUI commands return a structured unsupported-shell result instead of hanging the host
- asynchronous job or task updates leave a readable prompt boundary in the interactive shell
- `/tasks`, `/jobs`, and `/inspect` still work as fallback snapshot commands
- summarize or exit while the ledger is still pending verification or pending review surfaces an advisory warning
