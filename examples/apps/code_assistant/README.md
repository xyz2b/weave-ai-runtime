# Reactive AI Coding Shell V2

Run every command from the repository root.

## Positioning

This app is the repository's advanced integration sample for AI coding, not the default getting-started path for ordinary framework users.
Starter remains the adoption path. This app sits at the end of the validation path.

## What this example proves

- host-owned shell UX layered on top of the runtime
- durable runtime state, approvals, and reactive workflow rendering
- app-owned customization on top of the official coding scenario pack and shared coding packages

## Use this when

- the ordinary coding workflow demo already makes sense
- you need host-owned UX, durable state, approvals, or builtin replacement behavior
- you want to inspect an advanced sample without treating it as the default starter path

If you want the layered validation path first, use this order:

1. `examples/README.md` seam-basics and semantic demos
2. `python3 -B -m examples.projects.coding_workflow_demo`
3. `python3 -B -m examples.projects.coding_workflow_demo --live`
4. `python3 -B -m examples.apps.code_assistant shell`

Move to this app when you specifically need host-owned UX, durable runtime state, approvals, or builtin replacement behavior.

This app keeps the durable live-runtime path from the earlier demo, but combines an interactive `bash v2` surface, reactive runtime observability, and an app-owned workflow ledger on top of the same host, agent, tool, and skill composition:

- `host`: shell loop, local commands, approvals, reactive job or task rendering, workflow warnings and advisories
- `tool`: bundled coding tools plus the app-specific `bash v2` replacement
- `agent`: `code-assistant`, `coding-planner`, `reviewer`, and `verifier`
- `skill`: coding discipline and reusable plan, verify, and review workflow skills

## Prerequisites

Live workflow turns require:

- `OPENAI_API_KEY`

The deterministic validation path and the shell local-command smoke path do not require provider credentials.

Optional overrides:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

If `OPENAI_API_KEY` is missing and you use the live `run` path or spend a model turn in `shell`, the app still uses the bundled live route and surfaces the provider auth failure directly.

## Mutable state model

The fixture is immutable:

- `examples/apps/code_assistant/fixtures/mini_repo/`

The live app edits a generated mutable workspace:

- `.local/examples/code_assistant/mini_repo/`

The mutable workspace also stores durable runtime artifacts under `.local/examples/code_assistant/mini_repo/.weavert/`, including transcripts, child runs, task lists, jobs, and memory.

## Split ownership model

This sample intentionally keeps the advanced app split across four physical parts:

- app-owned shell layer under `examples/apps/code_assistant/`, including the host loop, local commands, approvals, workflow ledger, and the app-configured `bash` replacement behavior
- the official coding scenario pack, which owns `coding-planner`, `reviewer`, `verifier`, and the core coding-loop skills
- the shared git package, which owns the `git_*` tool family
- the shared workspace-intelligence package, which owns the `workspace_*` tool family

Both the live and deterministic validation paths should report the same package-manifest, tool-family, and definition-owner anchors for that split stack.

## Shell mode

Reset the mutable workspace first:

```bash
python3 -B -m examples.apps.code_assistant reset
```

Start the interactive shell:

```bash
python3 -B -m examples.apps.code_assistant shell
```

Use automatic approvals when you want a non-interactive shell session:

```bash
python3 -B -m examples.apps.code_assistant shell --auto-approve
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

### Local-command smoke path

For startup, snapshot, transcript, and shutdown smoke coverage, you can validate the shell without a model turn:

```bash
python3 -B -m examples.apps.code_assistant reset
python3 -B -m examples.apps.code_assistant shell --session-id local-shell --auto-approve
```

At the prompt, run:

```text
/inspect
/tasks
/jobs
/exit
```

Success anchors for this local shell smoke are:

- startup lines such as `code assistant shell`, `session: local-shell`, and `workspace: ...`
- `/inspect` output that includes `current transcript: local-shell`, `current task list: session:local-shell`, and at least one `workflow:` snapshot line
- a final shell report with `transcript: ...`, `child run index: ...`, and `status: ok`

## Run modes

### Live workflow run

Use the live bundled provider route when you want the real planner -> edit -> verify -> review -> summarize loop against provider-backed model turns:

```bash
export OPENAI_API_KEY=your-key
python3 -B -m examples.apps.code_assistant run \
  --session-id live-smoke \
  --auto-approve
```

### Deterministic validation run

Use the deterministic replay when you want the same split runtime assembly and durable artifact layout without live provider credentials:

```bash
python3 -B -m examples.apps.code_assistant run \
  --deterministic \
  --session-id deterministic-smoke \
  --auto-approve
```

The deterministic path replays repository-local scripted model support, but it still uses the same app-owned shell layer, package-backed workflow surfaces, approval handling, task list, workflow ledger, transcript store, child-run store, and `bash` replacement contract as the live path.

Success anchors for both `run` modes are:

- `mode: live` or `mode: deterministic`
- `status: ok`
- `task list: session:<session-id>`
- `workflow: ready_to_summarize (change=2, verified=2, reviewed=2)`
- `package manifests: weavert-scenario-coding, weavert-shared-git, weavert-shared-workspace-intelligence`
- `tool families: git_*=weavert-shared-git, workspace_*=weavert-shared-workspace-intelligence`
- `definition owners: code-assistant=app, coding-planner=weavert-scenario-coding, reviewer=weavert-scenario-coding, verifier=weavert-scenario-coding, coding-loop=weavert-scenario-coding`
- `bash replacement: app-configured v2 over weavert-devtools`
- `transcript: .../.weavert/transcripts/<session-id>.jsonl`
- `child run index: .../.weavert/child_runs/sessions/<session-id>.json`

The `run` path succeeds when the workflow leaves a real planning outcome, inspects the repo before the first material edit, verifies the latest revision, reviews the latest revision, and returns a final summary. If the planner degrades after leaving a usable shared plan, the command still succeeds and prints that condition as a non-blocking `workflow advisories` entry.

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
python3 -B -m examples.apps.code_assistant inspect
```

`inspect` summarizes:

- transcript sessions
- child-run state
- shared task lists
- package manifests, tool-family owners, and definition owners for the split app/package assembly
- semantic changed files, with `.weavert`, `__pycache__`, `*.pyc`, and `*.pyo` filtered out
- memory root and document count

`reset` deletes the mutable workspace and recreates it from the pristine fixture. That clears live edits and durable runtime artifacts together.

## Acceptance checklist

- unsupported TUI commands return a structured unsupported-shell result instead of hanging the host
- asynchronous job or task updates leave a readable prompt boundary in the interactive shell
- `/tasks`, `/jobs`, and `/inspect` still work as fallback snapshot commands
- summarize or exit while the ledger is still pending verification or pending review surfaces an advisory warning

## See also

- `../../README.md`
- `../../projects/workspaces/coding_workflow/README.md`
- `../../../docs/guides/use-scenario-packs.md`
- `../../../packages/product-kits/coding/README.md`
- `fixtures/mini_repo/README.md`
- `../../../docs/guides/use-scenario-packs.md`
- `../../../packages/product-kits/coding/README.md`
- `fixtures/mini_repo/README.md`
