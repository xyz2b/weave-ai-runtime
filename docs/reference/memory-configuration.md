# Memory Configuration Reference

This page summarizes the stable configuration and diagnostics vocabulary around the layered memory system.

## Who is this for?

- Readers who already know the workflow and now need a stable lookup page.

## Prerequisites

- Read the matching guide or concept page first.
- Treat this page as a reference sheet, not the first-stop tutorial.

## Configuration entry points

Project-local config files:

- `.weavert/memory/config.yaml`
- `.weavert/memory/config.yml`

Programmatic entry point:

- `RuntimeConfig.memory_config`

## Example

```yaml
memory:
  retrieval:
    max_results: 5
    prefer_tags: [testing, workflow]
    suppress_tags: [scratch]
    embedding_enabled: true
    llm_rerank: auto

  extraction:
    never_capture:
      - transient_task
      - secret
    routing:
      preference: long_term.preferences
      project_convention: long_term.conventions
      agent_workflow: agent_namespace
      session_thread: session

  session_memory:
    refresh:
      token_growth_threshold: 4000
      tool_call_threshold: 8
      turn_threshold: 6

  consolidation:
    enable_background: true
    min_closed_sessions: 4
    min_hours_since_last_run: 12
    backlog_threshold: 4
```

## Supported retrieval fields

- `max_results`
- `embedding_enabled`
- `llm_rerank`
- `prefer_tags`
- `suppress_tags`

## Supported extraction fields

- `never_capture`
- safe routing overrides

## Supported session-memory fields

- summary refresh thresholds such as token, tool-call, and turn thresholds

## Supported consolidation fields

- background enable or disable
- minimum closed sessions
- minimum hours since last run
- backlog threshold

## Safety boundaries

The runtime should continue to own these boundaries even when config changes:

- scope-boundary safety
- guarded memory roots
- secret and privacy baselines
- provenance recording
- rollback-safe consolidation writes

Invalid or unsafe config should be ignored with warnings rather than crashing the runtime.

## Consolidation artifacts

Typical consolidation artifacts include:

- `consolidations/checkpoints/<run-id>.json`
- `consolidations/staging/<run-id>.json`
- `consolidations/logs/<run-id>.md`
- `manifests/consolidation-manifest.json`

Common manifest concerns include backlog, active locks, last successful run, and recent checkpoint or log references.

## Diagnostics vocabulary

Useful retrieval diagnostics may include:

- `applied_filters`
- `boosts`
- `decays`
- `selected_doc_ids`
- `budget_decisions`
- `config`

Useful host- or session-visible diagnostics may include:

- retrieval trace
- write receipts
- background extraction task ids
- config source and warnings
- `background_memory_tasks`
- `background_memory_consolidation_tasks`
- `durable_memory_deltas`
- `last_consolidated_at`

## Operational questions this helps answer

- why was a memory fragment recalled?
- why was a fact written or rejected?
- is consolidation running or blocked?
- how much closed-session backlog still exists?

## Next step

- Return to `../concepts/memory-model.md` if you need the layer model behind these knobs and diagnostics.
- Use `../guides/testing-and-observability.md` when the next step is validating retrieval, writes, or consolidation behavior.
- Read `../architecture/persistence-and-state.md` if you need the broader durable-state ownership story.

## See also

- `../concepts/memory-model.md`
- `../architecture/persistence-and-state.md`
- `workflow-observability.md`
- `../deep-dives/layered-memory-weavert-v2.md`
