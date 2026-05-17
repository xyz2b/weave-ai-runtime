# Testing Toolchain Package

Canonical import root: `weavert_testing`

## What this package owns

- the deterministic validation-path testing harness
- scripted model support, fixtures, and assertions used by examples and developer workflows
- web research assertions for delegated tool use, ledger evidence, provider metadata, freshness outcomes, and stop reasons

## Web research evaluation helpers

- Use deterministic `FixtureWebResearchProvider` instances from `weavert_web_research` for search results, fetched pages, page-local matches, failures, fallback, and freshness support.
- Use `assert_web_research_outcome`, `assert_web_research_ledger_evidence`, `assert_web_research_source_classes`, `assert_web_research_selection_rationale`, `assert_web_research_claims_bound`, `assert_web_research_conflicts`, `assert_web_research_gaps`, and `assert_delegated_web_research_tool_use` for scripted-model web research evaluations.
- Prefer fixture providers and pages for profile source-selection, duplicate ordering, conflict, gap, provider fallback, and freshness assertions. Live provider checks should remain smoke tests because external ranking changes are not stable regression fixtures.
- Keep live-provider smoke validation separate from default tests; opt in with provider credentials such as `BRAVE_SEARCH_API_KEY` or `WEAVERT_BRAVE_SEARCH_API_KEY`.

## Canonical names

- install name: `weavert-testing`
- import root: `weavert_testing`
- runtime activation: none

This package stays outside runtime package selection and is reached through direct imports in validation workflows.

## See also

- `../README.md`
- `../../../examples/README.md`
- `../../../docs/guides/testing-and-observability.md`
