## ADDED Requirements

### Requirement: The `web_research` workflow SHALL distinguish hard policy from research preferences
The `web_research` tool SHALL normalize caller input into explicit hard policy, soft preferences, and concrete budgets so open-ended search can explore broadly while safety and caller-enforced boundaries remain authoritative.

#### Scenario: Caller invokes focused research with allowed domains
- **WHEN** a caller invokes `web_research` in `focused` mode or supplies explicit hard allowed domains
- **THEN** the delegated workflow SHALL treat those allowed domains as hard policy for every search, fetch, and find operation
- **AND** attempts to inspect sources outside the hard allowed domains SHALL be rejected before network evidence is accepted

#### Scenario: Caller invokes open research with preferred domains
- **WHEN** a caller invokes `web_research` in `open` mode with preferred domains or legacy `domains` treated as preferences
- **THEN** the delegated workflow SHALL use those domains to rank or seed exploration
- **AND** it SHALL NOT treat those preferred domains as the only valid source scope unless the caller also supplies hard allowed-domain policy

### Requirement: The `web_research` workflow SHALL enforce policy and budgets outside the model prompt
The `web_research` implementation SHALL enforce domain policy, blocked domains, search budgets, fetch budgets, find budgets, turn budgets, and concurrency limits through guarded execution state or an equivalent runtime mechanism rather than relying only on delegated-agent prompt instructions.

#### Scenario: Delegated agent omits caller policy from a low-level fetch
- **WHEN** a `web-searcher` child run attempts to call a low-level web tool without including the caller's hard policy fields
- **THEN** the guarded workflow SHALL apply the parent `web_research` policy to that call
- **AND** the call SHALL be rejected if it violates hard allowed-domain, blocked-domain, or public-host policy

#### Scenario: Delegated agent exceeds a configured budget
- **WHEN** a `web-searcher` child run attempts more search, fetch, or find operations than the parent `web_research` budget allows
- **THEN** the guarded workflow SHALL reject the over-budget operation before performing additional network or inspection work
- **AND** the final result SHALL include budget metadata and a terminal stop reason such as `budget_exhausted` or `partial_result`

### Requirement: The `web_research` workflow SHALL automatically aggregate structured evidence
The `web_research` result SHALL include structured source references, inspected evidence, budget usage, and trace summary derived from actual child-run web tool results, even when the delegated agent returns only a textual final answer.

#### Scenario: Delegated child run searches and fetches evidence then returns text
- **WHEN** the `web-searcher` child run calls low-level web tools and then returns a plain text synthesis
- **THEN** `web_research` SHALL return the synthesis as `answer`
- **AND** it SHALL populate `sources`, `evidence`, `budget`, and `trace_summary` from the recorded tool results without requiring special model-emitted terminal metadata

#### Scenario: Delegated child run returns richer structured metadata
- **WHEN** the `web-searcher` child run returns structured web research metadata in addition to recorded tool results
- **THEN** `web_research` MAY merge the structured metadata with ledger-derived evidence
- **AND** it SHALL preserve the tool-owned policy, budget, and trace contract as the authoritative fallback

### Requirement: The `web_research` workflow SHALL support bounded concurrent URL inspection
The `web_research` workflow SHALL support bounded concurrent inspection of multiple candidate URLs when useful for open-ended research, while enforcing shared policy, shared budgets, deterministic output ordering, and partial-failure accounting.

#### Scenario: Workflow inspects multiple URLs concurrently
- **WHEN** a delegated research workflow requests inspection of multiple candidate URLs
- **THEN** the workflow SHALL cap concurrent fetches with an explicit `max_concurrent_fetches` budget
- **AND** each URL SHALL consume from the same fetch budget and receive the same hard policy validation
- **AND** the returned sources and evidence SHALL use deterministic ordering based on input order, rank, or another stable ordering rule

#### Scenario: Some concurrent URL inspections fail
- **WHEN** one or more concurrent URL inspections fail because of policy, network, parsing, or budget errors
- **THEN** the workflow SHALL record bounded trace entries for those failures
- **AND** it SHALL still return usable evidence from successful inspections when available
- **AND** the stop reason SHALL identify partial results when failures or budget limits prevent a complete answer

### Requirement: The `web_research` workflow SHALL expose meaningful terminal stop reasons
The `web_research` result SHALL map child-run status, budget state, policy rejections, unsupported freshness constraints, and evidence sufficiency into meaningful stop reasons for callers.

#### Scenario: Workflow completes with enough inspected evidence
- **WHEN** the child run completes and the evidence ledger contains enough inspected evidence for the requested source count or objective
- **THEN** the result SHALL use `sufficient_evidence` or an equivalent success stop reason
- **AND** the result SHALL include the evidence and source metadata that justify that terminal state

#### Scenario: Workflow cannot satisfy constraints fully
- **WHEN** hard policy blocks all useful sources, budget is exhausted, freshness cannot be enforced, or only partial evidence is available
- **THEN** the result SHALL use a specific stop reason such as `policy_blocked`, `budget_exhausted`, `freshness_unsupported`, `needs_wider_scope`, or `partial_result`
- **AND** it SHALL include trace and policy metadata sufficient for the caller to understand the limitation

### Requirement: Regression coverage SHALL exercise real delegated web research behavior
The repository SHALL include regression coverage that runs `web_research` through the assembled runtime's ordinary child-run path and verifies policy enforcement, budget enforcement, evidence aggregation, open/focused mode behavior, and concurrent inspection.

#### Scenario: Runtime-level test exercises delegated web research
- **WHEN** tests invoke `web_research` in an assembled runtime with a scripted model client
- **THEN** the tests SHALL verify that the `web-searcher` child run receives only the authorized web tool pool
- **AND** the public result SHALL contain ledger-derived sources and evidence without mocked terminal metadata

#### Scenario: Runtime-level tests exercise defensive boundaries
- **WHEN** tests script a child agent to omit policy, fetch outside hard policy, or exceed budgets
- **THEN** the tests SHALL verify that guarded execution rejects the violating operations and reports structured stop reasons or trace entries
