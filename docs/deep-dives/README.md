# Deep Dives

These files are detailed references, not the default documentation journey.
Use them after the primary docs path in `../README.md`.

## When to use this folder

- You already know the public guide or concept page and now need the lower-level boundary ledger.
- You are evaluating framework seams and ownership in detail.
- You are maintaining or extending the repository and need deeper implementation context.

## Start from the question you have

- What owns what across app, assembly, session, turn, and control-plane layers?
  - [current-system-architecture.md](current-system-architecture.md)
- Where should an app or host integrate with the runtime?
  - [weavert-integration-guide.md](weavert-integration-guide.md)
- Which extension layer should I use before I start changing infrastructure?
  - [weavert-user-extension-guide.md](weavert-user-extension-guide.md)
- What is the stable contract for tools, agents, and skills?
  - [weavert-definition-authoring-guide.md](weavert-definition-authoring-guide.md)
- How do host, permissions, elicitation, hooks, and context contributors divide responsibility?
  - [weavert-control-plane-extension-guide.md](weavert-control-plane-extension-guide.md)
- What is the low-level hook registration model?
  - [weavert-hook-configuration-platform.md](weavert-hook-configuration-platform.md)
- How do scenario packs and shared packages fit into package composition?
  - [weavert-scenario-runtime-pack-architecture.md](weavert-scenario-runtime-pack-architecture.md)
- I already know the package boundary and only want the shortest activation reminder.
  - [weavert-scenario-runtime-pack-quickstart.md](weavert-scenario-runtime-pack-quickstart.md)
- How does layered memory divide durable artifacts and diagnostics?
  - [layered-memory-weavert-v2.md](layered-memory-weavert-v2.md)
- What is the shared workflow observability model across streams, reports, host events, and child runs?
  - [weavert-workflow-observability.md](weavert-workflow-observability.md)
- What are the OpenAI adapter's transport, schema, and failure-mode specifics?
  - [weavert-openai-responses-adapter.md](weavert-openai-responses-adapter.md)

## What this folder is not

- not the default getting-started path
- not the best place to learn one task for the first time
- not where maintainer-only validation ledgers should live

## Maintainer ledgers

The maintainer-facing migration and validation ledgers live under `../maintainers/`:

- [../maintainers/migration-notes.md](../maintainers/migration-notes.md)
- [../maintainers/validation-findings.md](../maintainers/validation-findings.md)
