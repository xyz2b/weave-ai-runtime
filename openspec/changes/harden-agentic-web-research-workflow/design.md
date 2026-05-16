## Context

The current shared `common/web` implementation registers `web_research` and delegates to a package-owned `web-searcher` child agent. That path is useful, but the tool-owned contract is not yet authoritative in real child runs: domain policy and budget controls are embedded in the delegation prompt, the child agent can call low-level tools without those controls, and structured evidence is only returned when a mocked agent runner supplies special terminal metadata.

Open-ended web research adds another tension. If every source constraint is hard, exploratory search becomes brittle; if every constraint is soft, policy is not trustworthy. The hardened workflow needs to distinguish safety and budget boundaries from ranking preferences while keeping the first version a bounded single-call workflow.

## Goals / Non-Goals

**Goals:**

- Make `web_research` policy and budget controls enforceable by implementation, not by prompt wording alone.
- Support both focused and open-ended research modes.
- Preserve hard safety controls for public-host validation, blocked domains, allowed domains when explicitly requested, and maximum budgets.
- Treat preferred domains, freshness hints, and source-shaping guidance as soft preferences unless promoted to hard policy.
- Automatically aggregate structured sources, evidence, and trace summaries from child-run tool results.
- Support bounded concurrent inspection of multiple URLs while sharing one budget ledger and preserving deterministic output ordering.
- Expand tests to exercise real runtime delegation rather than only mocked child results.
- Refresh package build artifacts so local distributables match source.

**Non-Goals:**

- Creating a background deep-research job system.
- Adding browser navigation, clicking, form filling, shell execution, or workspace mutation to the shared web package.
- Replacing the low-level `grounding_web_search`, `grounding_web_fetch`, or `grounding_web_find` primitives.
- Guaranteeing freshness when the active backend cannot enforce it; unsupported freshness remains explicit metadata.
- Introducing a new hosted search provider dependency.

## Decisions

### Decision: Separate hard policy from preferences

`web_research` will normalize legacy fields into a contract with:

- `mode`: `focused` or `open`
- `hard_policy`: blocked domains, optional allowed domains, maximum budgets, and safety controls
- `preferences`: preferred domains, freshness hints, desired source count, and output hints
- `budget`: concrete search, fetch, find, turn, and concurrency limits

Legacy `domains`/`allowed_domains` remain accepted. In `focused` mode they act as hard allowed domains. In `open` mode they may be treated as preferred domains unless the caller supplies `hard_policy.allowed_domains` or an explicit strict/focused request.

Alternative considered: keep the existing flat schema and document softer behavior. Rejected because flat fields make it hard to tell which constraints are safety-critical and which are ranking guidance.

### Decision: Use a web research run state with guarded tool execution

`web_research` will create per-call run state that records normalized policy, budget usage, evidence, and trace events. During the delegated child run, package-owned guarded execution will enforce that low-level web calls remain inside that state:

- Inject or validate allowed/blocked domains on search/fetch/find calls.
- Refuse over-budget search, fetch, and find calls before network work begins.
- Record every successful and rejected operation in a bounded trace.
- Preserve low-level primitives for direct callers outside a `web_research` run.

The implementation can use context metadata, a runtime service hook, or package-local context variables. The important contract is that the child agent cannot bypass `web_research` controls by omitting fields from its tool input.

Alternative considered: rely on `web-searcher` prompt instructions plus tests. Rejected because runtime probes showed a child agent can fetch out-of-policy URLs and exceed budget.

### Decision: Build structured output from an EvidenceLedger

The final `web_research` result will be projected from the ledger plus child-run synthesis. The answer can still come from the child agent's final message, but `sources`, `evidence`, `trace_summary`, `budget`, and `stop_reason` must not require special `terminal_metadata.web_research` from the model.

If the child returns richer structured metadata, the projection may merge it with the ledger, but ledger-derived data remains the fallback contract.

Alternative considered: require `web-searcher` to output JSON. Rejected because model-only JSON is brittle and does not prove inspected evidence came from actual tool results.

### Decision: Add bounded concurrent URL inspection

The package may expose an internal concurrent fetch helper or support multiple URL inspection through the guarded workflow. Concurrent fetches must:

- Share one fetch budget.
- Apply the same hard policy to every URL.
- Cap concurrency with an explicit `max_concurrent_fetches` limit.
- Return deterministic ordering based on input order or stable rank.
- Account for partial failures without failing the entire research result when useful evidence remains.

Alternative considered: keep all inspection sequential. Rejected because open-ended research often needs to inspect several candidate pages, and bounded concurrency improves latency without widening the public behavior.

### Decision: Test against real runtime delegation

Regression coverage must include scripted-model runtime tests that execute `web_research`, delegate to `web-searcher`, run low-level tools, and then inspect the public result. Tests must cover:

- Structured evidence generated without mocked terminal metadata.
- Out-of-policy child fetch rejection.
- Budget exhaustion when the child attempts too many operations.
- Open-mode preferred domains that do not hard-block unrelated public sources.
- Concurrent URL inspection and partial failure accounting.
- Package build artifacts containing the same public surfaces as source.

## Risks / Trade-offs

- [Risk] Guarded wrappers may introduce hidden state coupling between `web_research` and low-level tools. -> Mitigation: keep state per call, scoped to the delegated child run, and preserve direct primitive behavior outside a run.
- [Risk] Open mode may surprise callers who expected `domains` to be strict. -> Mitigation: retain focused/strict behavior for `allowed_domains` and document mode-specific normalization.
- [Risk] Concurrent fetches can amplify network load. -> Mitigation: enforce small defaults, hard maximums, shared budget accounting, and deterministic partial results.
- [Risk] Ledger output may include low-quality sources if the model explores poorly. -> Mitigation: expose trace, stop reason, and partial result metadata; leave ranking improvements incremental.
- [Risk] Build artifact refresh could touch generated files. -> Mitigation: limit generated updates to the common web package build/dist outputs needed to make local distributables match source.

## Migration Plan

1. Add normalization for mode, hard policy, preferences, and concurrency budget while preserving legacy input fields.
2. Add guarded per-run state and connect it to child-run low-level tool execution.
3. Add ledger-derived result projection and stop-reason mapping.
4. Add bounded concurrent URL inspection support.
5. Expand runtime-level tests and build-artifact checks.
6. Rebuild `weavert-kit-common-web` local artifacts.

Rollback strategy:

- Disable guarded `web_research` state and return to the existing delegated prompt path while keeping low-level primitives intact.
- Revert artifact refresh if needed without changing source contracts.

## Open Questions

- None. The first implementation should choose conservative defaults for concurrency and budget caps.
