## 1. Contract And Normalization

- [x] 1.1 Extend `web_research` input normalization to support `mode`, `hard_policy`, `preferences`, `budget_profile`, and `max_concurrent_fetches` while preserving legacy fields.
- [x] 1.2 Update `web_research` tool schemas, package metadata, and docs to explain focused vs open research, hard policy vs preferences, and bounded concurrent inspection.

## 2. Guarded Research Runtime

- [x] 2.1 Add per-call `web_research` run state for hard policy, preferences, budget ledger, evidence ledger, and bounded trace summary.
- [x] 2.2 Enforce parent hard policy and budgets when `web-searcher` calls `grounding_web_search`, `grounding_web_fetch`, or `grounding_web_find`, including cases where the child omits policy fields.
- [x] 2.3 Map policy rejections, budget exhaustion, unsupported freshness, and partial evidence into stable `stop_reason` values.

## 3. Evidence And Concurrency

- [x] 3.1 Populate `sources`, `evidence`, `budget`, and `trace_summary` from actual low-level web tool results instead of requiring model-emitted `terminal_metadata.web_research`.
- [x] 3.2 Add bounded concurrent URL inspection support that shares fetch budget, applies the same hard policy to each URL, preserves deterministic ordering, and records partial failures.

## 4. Tests And Validation

- [x] 4.1 Add runtime-level tests for successful delegated `web_research` that produces structured evidence without mocked terminal metadata.
- [x] 4.2 Add runtime-level tests for out-of-policy child fetch rejection and over-budget child operations.
- [x] 4.3 Add tests for open-mode preferred-domain behavior, focused hard-domain behavior, and bounded concurrent URL inspection with partial failures.
- [x] 4.4 Add or update tests that verify common web local build/distribution artifacts contain the same public surfaces as source.

## 5. Packaging

- [x] 5.1 Refresh `weavert-kit-common-web` generated build and dist artifacts so they include the hardened source implementation.
- [x] 5.2 Run focused OpenSpec and pytest validation for the change and update task checkboxes as work completes.
