## 1. Tool Contract

- [x] 1.1 Define `ToolExecutionSemantics`, `ResolvedToolExecutionSemantics`, presentation payloads, classifier payloads, and failure-policy models
- [x] 1.2 Fix the concrete shape of `ToolFailurePolicy`, `ToolClassifierInput`, `ToolUsePresentation`, and `ToolResultSummary`
- [x] 1.3 Resolve execution semantics once per normalized tool call and thread the resolved snapshot through scheduler, permission evaluation, host presentation, and tool result mapping
- [x] 1.4 Add a legacy compatibility adapter that maps existing trait-based tool definitions onto static execution semantics
- [x] 1.5 Replace raw `ToolContext` service-bag exposure with an explicit capability container for catalogs, query context, app state, file state, progress, notifications, capability refresh, and memory access
- [x] 1.6 Fix the concrete shape of `QueryContext`, `AppState`, `FileState`, `ProgressHandle`, `NotificationsHandle`, `CapabilityRefreshHandle`, and `MemoryAccess`
- [x] 1.7 Fix the concrete shape of `CatalogEntryView`, `ToolCatalog`, `AgentCatalog`, `SkillCatalog`, `PermissionContextView`, and `PermissionRuleView`
- [x] 1.8 Implement policy-aware catalog views, read-only permission-context views, and namespaced `app_state` / `file_state` handles instead of relying on unstructured metadata
- [x] 1.9 Update builtin tool discovery and builtin tool definitions to expose the required semantics, including explicit failure mapping for shell-like tools

## 2. Streaming Orchestration

- [x] 2.0 Land Slice A (`definitions.py`, `tool_lifecycle.py`, `turn_engine/models.py`) so richer contract, lifecycle objects, and typed lifecycle-event surface exist before orchestration behavior changes
- [x] 2.1 Add a normalized model capability profile and selector that chooses between `FullStreamingToolExecutor`, `BufferedToolExecutor`, and `BatchToolExecutor`
- [x] 2.2 Define `ToolCallEnvelope`, `ResolvedToolCall`, `ResolvedPermissionDecision`, `ToolCapabilityContext`, `ToolSchedulerLane`, `ContextUpdate`, `ToolOutcome`, and the observable transition points between them
- [x] 2.2.1 Fix `ResolvedPermissionDecision` as a closed terminal union (`PermissionAllowed` / `PermissionDenied`) with no lingering `ask` / `pending` state after resolution
- [x] 2.2.2 Fix `ContextUpdate` as a closed typed union with explicit apply-phase rules and a compatibility-only wrapper for legacy closure-style context modifiers
- [x] 2.2.3 Fix `ToolLifecycleEvent` as a closed typed union and define the monotonic lifecycle-stage projection from observation through replay commit
- [x] 2.2.4 Extract concrete module ownership across `definitions.py`, `tool_runtime.py`, `tool_lifecycle.py`, `tool_resolution.py`, `tool_orchestration.py`, `tool_executors.py`, and `turn_engine/*` so lifecycle, resolution, replay, and tier selection do not collapse back into one file
- [x] 2.2.5 Add explicit transition guards so forbidden jumps like `resolving -> running` or `queued -> replayed` cannot occur without a terminal `ToolOutcome`
- [x] 2.3 Land Slice B (`tool_resolution.py`, permission mediation integration, compat glue in `tool_runtime.py`) so a single tool call resolves into `ResolvedToolCall`
- [x] 2.3.1 Build the tool-call resolution pipeline so final execution input, resolved semantics, permission updates, call-scoped capability context, resolution status, lane assignment, and replay index are frozen into `ResolvedToolCall`
- [x] 2.4 Land Slice C (`tool_orchestration.py` plus batch-path integration) so batch execution already uses replay ordering, lane assignment, lifecycle events, and `ToolOutcome`
- [x] 2.4.1 Add a `StreamingToolOrchestrator` abstraction first on the batch path, before enabling streamed early start
- [x] 2.5 Land Slice E (`tool_executors.py` plus `turn_engine/engine.py` selector wiring) so `Buffered` and `Batch` tiers share the same lifecycle model and downgrade remains observable
- [x] 2.5.1 Implement `BufferedToolExecutor` and `BatchToolExecutor` fallback paths that preserve ordered replay and explicit tool outcome mapping without early start
- [x] 2.6 Land Slice F (`FullStreamingToolExecutor` plus orchestrator early start path) after lower tiers and replay semantics are stable
- [x] 2.6.1 Implement input-aware execution lanes, conservative lane downgrade when precise conflict domains are unavailable, and fatal sibling failure cascade behavior across all executor tiers using `ResolvedToolCall` and `ToolOutcome`
- [x] 2.7 Land Slice G (builtin semantics opt-in and compat hardening) so shell-like tools expose explicit fatal failure behavior while legacy tools still execute via adapter

## 3. Control Plane Integration

- [x] 3.0 Land Slice D (`turn_engine/*`, `session_runtime/controller.py`, `hosts/base.py`) so tool lifecycle is surfaced as first-class turn events end-to-end
- [x] 3.1 Route tool progress updates through turn events and host bridge callbacks instead of tool-local dead-end sinks
- [x] 3.1.1 Add a first-class turn-stream event shape for tool lifecycle events so `session_runtime/controller.py` and host adapters can relay typed lifecycle observations without transcript scraping
- [x] 3.2 Propagate tool-triggered capability refresh into shared execution policy and subsequent provider request assembly
- [x] 3.3 Reconcile permission, hook, and abort handling with the tool-call lifecycle so cancellation, denial, updatedInput transitions, and lifecycle events stay explicit

## 4. Conformance Coverage

- [x] 4.0 Establish the minimal test matrix before enabling full streaming by default
- [x] 4.1 Add `T1_resolution_allow_updated_input` covering final execution input, resolved semantics, and `PermissionAllowed`
- [x] 4.2 Add `T2_resolution_denied_non_executable` covering denied `ResolvedToolCall`, missing `execution_started`, and synthetic terminal outcome
- [x] 4.3 Add `T3_batch_replay_ordering` covering out-of-order completion and in-order replay commit
- [x] 4.4 Add `T4_lane_conservative_downgrade` covering serialized fallback when reliable conflict domains are unavailable
- [x] 4.5 Add `T5_fatal_sibling_cascade` covering fatal failure propagation and replay-slot preservation for affected siblings
- [x] 4.6 Add `T6_context_update_apply_phases` covering `before_replay`, `with_replay`, and `after_replay` ordering
- [x] 4.7 Add `T7_lifecycle_event_ordering` covering the happy-path observable event sequence from `envelope_observed` through `replay_committed`
- [x] 4.8 Add `T8_executor_downgrade_selection` covering capability-based tier selection and observable runtime downgrade
- [x] 4.9 Add `T9_legacy_trait_tool_compat` proving trait-based tools still execute correctly under the richer runtime contract
- [x] 4.10 Add `T10_full_streaming_early_start` as the final rollout gate for true early-start behavior before `message_stop`
- [x] 4.11 Expand regression coverage for fatal sibling cancellation, progress event emission, and capability refresh affecting subsequent requests beyond the minimal matrix
- [x] 4.12 Expand compatibility coverage beyond `T9_legacy_trait_tool_compat` for multiple legacy trait-based tools and aliases
