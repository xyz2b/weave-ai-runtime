# WeaveRT Layered Memory Runtime

> Documentation note: This file remains the deep-dive reference for memory details. Start with `docs/concepts/memory-model.md`; use `docs/reference/memory-configuration.md` for configuration and diagnostics lookup, and `docs/architecture/persistence-and-state.md` for the wider persistence boundary.

This reference keeps the memory boundary ledger: durable layers, hybrid retrieval and extraction posture, configuration limits, consolidation ownership, and diagnostics vocabulary.

Primary docs path:

- Memory concepts -> `docs/concepts/memory-model.md`
- Memory configuration quick reference -> `docs/reference/memory-configuration.md`
- Persistence boundary -> `docs/architecture/persistence-and-state.md`

Use this page when you need the deeper artifact and boundary model rather than the quick reference.

## 1. Layer model

Memory v2 divides durable behavior into four layers:

| Layer | Typical role | Typical durable root |
| --- | --- | --- |
| `LongTermMemory` | shared durable facts such as preferences, conventions, topics, shared notes | `.weavert/memory/documents/` |
| `AgentNamespaceMemory` | durable memory scoped to one agent namespace | `.weavert/memory/agents/<agent>/documents/` |
| `SessionMemory` | continuity artifacts for one session | `.weavert/memory/sessions/<session>/` |
| `ConsolidationMemory` | slower cross-session background synthesis and merge work | `.weavert/memory/consolidations/` |

The key boundary is:

- session continuity is not the same thing as shared long-term memory
- consolidation is not just another prompt-time retrieval layer

## 2. Hybrid policy

Memory uses a deterministic-first, enhancement-second posture.

### 2.1 Retrieval

Typical flow:

1. manifest or header prefilter
2. deterministic lexical shortlist
3. optional embedding shortlist
4. optional LLM rerank
5. per-layer materialization into turn context

This keeps retrieval inspectable while still allowing stronger ranking when configured.

### 2.2 Extraction

Typical posture:

- obvious facts can be captured on the main thread
- higher-value synthesis can happen in background work
- consolidation can merge useful session outcomes back into shared durable memory

If a fact should not be stored, the runtime should preserve rejection reasons in receipts or diagnostics instead of dropping the write silently.

## 3. Declarative configuration surface

Supported entry points:

- `.weavert/memory/config.yaml`
- `.weavert/memory/config.yml`
- `RuntimeConfig.memory_config`

The main configurable families are:

- retrieval
  - result count and ranking posture
  - preferred or suppressed tags
- extraction
  - never-capture rules
  - safe routing overrides
- session memory
  - refresh thresholds
- consolidation
  - background enablement and cadence

## 4. Safety boundaries

Some boundaries remain runtime-owned even when config changes:

- scope-boundary safety
- guarded memory roots
- secret and privacy baselines
- provenance recording
- rollback-safe consolidation writes

Unsafe or invalid config should be ignored with warnings rather than crashing the runtime.

## 5. Consolidation ownership

`ConsolidationMemory` is the long-horizon maintenance layer.
Its job is to:

- observe closed-session backlog
- stage and checkpoint merge work
- merge useful proposals back into shared durable memory
- preserve enough logs and manifests for recovery and inspection

Typical artifact families include:

- checkpoints
- staging records
- run logs
- a consolidation manifest that tracks backlog, locks, and recent run state

Important boundary:

- consolidation may update shared durable memory
- it should do so through explicit manifests, logs, and rollback-safe writes
- it should not silently redefine transcript truth

## 6. Diagnostics vocabulary

Useful retrieval diagnostics may include:

- `applied_filters`
- `boosts`
- `decays`
- `selected_doc_ids`
- `budget_decisions`
- `config`

Useful write or host-visible diagnostics may include:

- write receipts
- rejection reasons
- background extraction task ids
- config source and warnings
- consolidation backlog or last-run state

These diagnostics should help answer:

- why a memory fragment was recalled
- why a fact was written or rejected
- whether consolidation ran, is blocked, or still has backlog

## 7. Related docs

- `docs/concepts/memory-model.md`
- `docs/reference/memory-configuration.md`
- `docs/architecture/persistence-and-state.md`
- `docs/deep-dives/current-system-architecture.md`
