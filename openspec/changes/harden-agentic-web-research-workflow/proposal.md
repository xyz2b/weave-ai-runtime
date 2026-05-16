## Why

The current `web_research` surface wires a delegated `web-searcher` child run, but review and runtime probes show that policy and budget controls are still prompt-mediated, structured evidence is not reliably produced by real child runs, and existing tests mostly exercise idealized mocked projections. This weakens the AI-first web research goal, especially for open-ended questions where the system needs exploratory search without giving up hard safety and budget boundaries.

## What Changes

- Harden `web_research` so caller policy and budgets are enforced by tool wrappers or equivalent runtime state instead of relying on the delegated agent prompt.
- Split open-ended research guidance into hard policy, preferences, and budget profiles so exploratory search can remain useful without bypassing safety constraints.
- Add automatic evidence and trace aggregation for search, fetch, and find calls made during a `web_research` child run, so `sources`, `evidence`, and `trace_summary` do not depend on the model emitting special terminal metadata.
- Support bounded concurrent inspection of multiple candidate URLs inside the same policy and budget ledger, with deterministic aggregation and failure accounting.
- Replace optimistic mocked-only tests with runtime-level tests that exercise real `web_research -> web-searcher -> grounding_web_*` execution, policy rejection, budget exhaustion, structured evidence projection, and concurrent fetch behavior.
- Refresh or validate generated build artifacts for `weavert-kit-common-web` so local distributable outputs match the source implementation.

## Capabilities

### New Capabilities
- `agentic-web-research-workflows`: Defines hardened high-level `web_research` workflow semantics, open/focused mode behavior, tool-owned policy and budget enforcement, automatic evidence ledgers, and bounded concurrent URL inspection.

### Modified Capabilities
- `chat-grounding-packages`: Clarifies that chat-facing `web_research` remains read-only while supporting open-ended research through hard policy, soft preferences, structured evidence output, and bounded concurrent page inspection.

## Impact

- Affected shared web package code under `packages/product-kits/common/web/`, especially `web_research` input normalization, delegated tool execution, evidence projection, and package docs.
- Affected framework/runtime tests under `tests/test_scenario_runtime_packs.py` or related focused test modules that exercise real runtime delegation.
- Affected package build outputs under `packages/product-kits/common/web/build/` and `packages/product-kits/common/web/dist/` so generated artifacts no longer lag the source tree.
- No browser navigation, shell execution, workspace mutation, long-running job ownership, or background deep-research coordinator is introduced by this change.
