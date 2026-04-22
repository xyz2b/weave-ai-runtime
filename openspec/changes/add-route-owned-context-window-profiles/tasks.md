## 1. Context Window Models

- [ ] 1.1 Add a structured `TokenEstimationHint` model.
- [ ] 1.2 Add a structured `RecoveryClassificationRule` model.
- [ ] 1.3 Add a structured `MinimalRecoveryClassificationHints` model with required `context_limit` support and optional `output_limit`.
- [ ] 1.4 Add a structured `ModelContextWindowProfile` model.
- [ ] 1.5 Add a structured `RouteContextWindowPolicy` model.
- [ ] 1.6 Add a structured `ResolvedContextWindowSnapshot` model.
- [ ] 1.7 Extend `ModelRouteBinding` or equivalent runtime-owned route config surfaces so named routes can carry optional context window policy without breaking existing `model_routes` configuration.
- [ ] 1.8 Ensure all new context-window-related route/config fields remain optional and backward compatible for existing runtimes.

## 2. Integration Profile Catalog And Matching

- [ ] 2.1 Extend model integration or equivalent provider registration surfaces so integrations can expose optional context window profile catalogs.
- [ ] 2.2 Support exact-model profile entries in the integration-owned catalog.
- [ ] 2.3 Support pattern-based profile entries in the integration-owned catalog.
- [ ] 2.4 Support provider-default profile entries in the integration-owned catalog.
- [ ] 2.5 Support token-estimation hints and minimal recovery classification hints on integration-owned profiles.
- [ ] 2.6 Implement deterministic matching precedence `exact > pattern > provider-default > unknown`.
- [ ] 2.7 Reject same-specificity profile collisions during registration or assembly instead of relying on declaration order.

## 3. Bundled OpenAI Baseline

- [ ] 3.1 Add a first-party bundled OpenAI provider baseline that participates in the same route-resolution path as other integrations.
- [ ] 3.2 Provide a bundled OpenAI provider binding named `openai-prod`.
- [ ] 3.3 Provide a bundled OpenAI named route `openai_default`.
- [ ] 3.4 Wire bundled OpenAI credentials through `OPENAI_API_KEY` or equivalent host-supplied replacement.
- [ ] 3.5 Wire optional bundled OpenAI endpoint overrides through `OPENAI_BASE_URL` or equivalent host-supplied replacement.
- [ ] 3.6 Wire optional bundled OpenAI default-model overrides through `OPENAI_MODEL` or equivalent host-supplied replacement.
- [ ] 3.7 Add bundled OpenAI context window profile baselines under the same contract used by third-party integrations.
- [ ] 3.8 Add bundled OpenAI minimal recovery classification hints under the same contract used by third-party integrations.
- [ ] 3.9 Ensure missing bundled OpenAI credentials produce a structured invocation-time configuration error without silently removing the built-in route from discovery.

## 4. Route Resolution And Snapshot Derivation

- [ ] 4.1 Preserve the existing `model_route` / `model` precedence while ensuring agent definitions do not need new context-window-specific fields.
- [ ] 4.2 Resolve the final provider/model identity before context-window profile lookup.
- [ ] 4.3 Resolve the integration baseline profile for the final provider/model using exact, pattern, provider-default, then unknown precedence.
- [ ] 4.4 Apply route-level narrowing or override after baseline profile selection.
- [ ] 4.5 Derive `fallback_mode` for the final resolved context window snapshot.
- [ ] 4.6 Derive `source` and `confidence` for the final resolved context window snapshot.
- [ ] 4.7 Produce the final `ResolvedContextWindowSnapshot` object or equivalent structured runtime surface.

## 5. Metadata Threading And Observability

- [ ] 5.1 Thread resolved context window ownership, fallback mode, source, confidence, and bounded hints into execution metadata or equivalent structured runtime surfaces.
- [ ] 5.2 Expose canonical host-visible structured `context_window` metadata.
- [ ] 5.3 Expose canonical host-visible `context_window_policy_tag` metadata when a policy tag exists.
- [ ] 5.4 Expose bounded request-shaping hints from the resolved snapshot to context-preparation and hook surfaces.

## 6. Compaction And Recovery Integration

- [ ] 6.1 Update context preparation and compaction policy derivation so known context window snapshots can drive proactive pre-request compaction triggers.
- [ ] 6.2 Keep routes with unknown context window metadata in reactive-only mode.
- [ ] 6.3 Ensure `context_limit` or equivalent provider failures still trigger compact-and-retry recovery when the route is in reactive-only mode.
- [ ] 6.4 Consume minimal recovery classification hints from the resolved snapshot for `context_limit` recognition.
- [ ] 6.5 Optionally consume minimal recovery classification hints from the resolved snapshot for `output_limit` recognition.
- [ ] 6.6 Preserve provider-neutral fallback classification when integration hints are absent or incomplete.

## 7. Context-Control Vocabulary Rename

- [ ] 7.1 Rename context-window-related control-plane types to remove `budget` wording from context-control surfaces: `ContextBudgetHook` -> `ContextWindowHook`, `ContextBudgetRequest` -> `ContextWindowRequest`, `ProviderBudgetHints` -> `ProviderContextWindowHints`, `BudgetCandidate` -> `ContextWindowCandidate`, `BudgetDecision` -> `ContextWindowDecision`, `BudgetPlan` -> `ContextWindowPlan`, and `ContextBudgetHookFailureMode` -> `ContextWindowHookFailureMode`.
- [ ] 7.2 Rename directly associated config keys such as `budget_hook*` to canonical context-window-oriented names.
- [ ] 7.3 Rename directly associated observability and metadata surfaces such as `budget_policy_tag` to canonical context-window-oriented names.
- [ ] 7.4 Rename diagnostics such as `context_budget_hook_*` to canonical context-window-oriented names.
- [ ] 7.5 Rename effect naming such as `BUDGET_DECISION` to canonical context-window-oriented naming such as `CONTEXT_WINDOW_DECISION`.
- [ ] 7.6 Add canonical context-window diagnostics/effects such as `context_window_hook_error`, `context_window_hook_unparseable`, and `CONTEXT_WINDOW_DECISION`.

## 8. Compatibility And Deprecation

- [ ] 8.1 Add compatibility aliases for renamed context-window control-plane types so existing integrations can migrate without an immediate hard break.
- [ ] 8.2 Add compatibility parsing for legacy config keys alongside canonical context-window keys.
- [ ] 8.3 Ensure canonical context-window keys win when both canonical and legacy config keys are present.
- [ ] 8.4 Emit structured deprecation diagnostics when legacy config keys or legacy type aliases are exercised through public runtime surfaces.
- [ ] 8.5 If migration requires dual-write metadata or diagnostics, bound that compatibility projection explicitly so old fields do not become the canonical source of truth.

## 9. Verification And Examples

- [ ] 9.1 Add regression tests for integration-owned context window profile resolution and agent execution without context-window fields.
- [ ] 9.2 Add regression tests for exact/pattern/provider-default profile precedence.
- [ ] 9.3 Add regression tests for same-specificity collision rejection.
- [ ] 9.4 Add regression tests for route-level override and narrowing after baseline profile selection.
- [ ] 9.5 Add regression tests covering known-context-window proactive compaction.
- [ ] 9.6 Add regression tests covering unknown-context-window reactive fallback behavior.
- [ ] 9.7 Add regression tests covering minimal recovery classification hints for `context_limit`.
- [ ] 9.8 Add regression tests covering optional minimal recovery classification hints for `output_limit`.
- [ ] 9.9 Add regression tests for canonical context-window observability, including structured `context_window` metadata and `context_window_policy_tag`.
- [ ] 9.10 Add regression tests for canonical context-window diagnostics and effect names.
- [ ] 9.11 Add regression tests for legacy compatibility, including alias acceptance, canonical-key precedence, deprecation diagnostics, and any required dual-write behavior during migration.
- [ ] 9.12 Update runtime configuration examples or fixtures to show route-owned context window policy and semantic route selection instead of agent-local context-window configuration.
- [ ] 9.13 Add examples or fixtures showing the bundled OpenAI provider baseline and how hosts override credentials, models, or routes without replacing the first-party integration contract.
