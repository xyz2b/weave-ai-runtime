# Memory Model

WeaveRT treats memory as a layered runtime system, not as one giant prompt blob.

## Who is this for?

- Adopters who already know the landing-page story and now need the core runtime vocabulary.

## Prerequisites

- Read `../introduction/what-is-weavert.md` first.
- Skim `../getting-started/quickstart.md` if you want the terminology anchored in a runnable path.

## The four-layer model

### Long-term memory

Shared durable memory for facts that should outlive one session.
Typical examples include:

- preferences
- conventions
- topics
- shared reference notes

Typical durable root:

- `.weavert/memory/documents/`

### Agent namespace memory

Durable memory scoped to one agent namespace.
Use this when an agent needs its own persistent notes without escaping the current user, project, or local boundary.

Typical durable root:

- `.weavert/memory/agents/<agent>/documents/`

### Session memory

Continuity artifacts for one session.
This is where the runtime can keep things like:

- session summaries
- open threads
- session metadata

Typical durable root:

- `.weavert/memory/sessions/<session>/`

### Consolidation memory

Slower background memory work that merges useful session outcomes back into longer-lived memory.
It is not just another prompt-time layer; it is the long-horizon maintenance layer.

Typical durable root:

- `.weavert/memory/consolidations/`

## Retrieval is hybrid

Memory retrieval follows a "deterministic first, enhanced second" posture.
A typical flow is:

1. manifest or header prefilter
2. deterministic lexical shortlist
3. optional embedding shortlist
4. optional LLM rerank
5. per-layer materialization into the turn context

This keeps retrieval inspectable while still allowing stronger ranking when configured.

## Extraction is layered too

Memory writing also uses a hybrid path:

- obvious facts can be captured on the main thread
- higher-value synthesis can happen in slower background work
- consolidation can later merge outcomes across closed sessions

If a fact should not be stored, the runtime should preserve the rejection reason in diagnostics or receipts rather than silently dropping it.

## Why this design matters

The layered model protects several important boundaries:

- prompt-visible context is not the whole durable memory system
- session continuity should not be treated as the same thing as shared long-term memory
- background consolidation should not silently rewrite runtime truth without diagnostics
- memory policy should remain configurable without breaking safety boundaries

## What ordinary users usually need first

Most adopters do not need to replace the entire memory subsystem on day one.
They usually start by understanding:

- where durable artifacts live
- what layer a fact belongs to
- how retrieval and extraction are shaped
- how to tune behavior through config rather than custom code

## Next step

- Use `../reference/memory-configuration.md` to configure or inspect the layered memory policy.
- Read `../architecture/persistence-and-state.md` when you need the broader durable-state ownership map.

## See also

- `hosts-permissions-memory.md`
- `../reference/memory-configuration.md`
- `../architecture/persistence-and-state.md`
- `../deep-dives/layered-memory-weavert-v2.md`
