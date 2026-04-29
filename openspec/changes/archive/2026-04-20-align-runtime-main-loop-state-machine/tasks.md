## 1. Turn Loop Models

- [x] 1.1 Add explicit turn-loop models for `TurnPhase`, `TurnLoopState`, transition reason, recovery action, terminal reason, and post-turn effects
- [x] 1.2 Refactor `TurnEngine` internals so `run_turn_stream()` remains the canonical async-generator surface while explicit phase/transition state preserves the current request/message/terminal event contract
- [x] 1.3 Enforce the legal phase graph so continuation only re-enters through `advance_or_finish -> prepare`, `compact_or_rebuild`, or `build_request`
- [x] 1.4 Keep `SessionController` responsible for session command flow and transcript persistence while removing reliance on implicit turn-only metadata where explicit turn outcomes are available
- [x] 1.5 Ensure aggregate helpers such as `run_turn()` and session-level non-streaming entrypoints are derived from the same async-generator main-loop contract
- [x] 1.6 Split attempt outcome from turn terminal, reserving host-facing `TERMINAL` for turn-final completion only and moving provider-attempt completion to a non-terminal surface
- [x] 1.7 Update [engine.py](../../../../src/runtime/turn_engine/engine.py) so `TERMINAL` is turn-final only, `tool_use` no longer uses final terminal semantics, and every exit path emits one explicit final terminal
- [x] 1.8 Define and emit an explicit `ATTEMPT_FINISHED` payload with required fields for iteration, request id, attempt stop reason, usage, error, abort reason, and tool-call production

## 2. Sidecar Preparation

- [x] 2.1 Implement a pre-turn sidecar supervisor with deterministic join/cancel/restart semantics for memory retrieval and hook-context collection
- [x] 2.2 Wire compaction and request-rebuild invalidation boundaries into the sidecar supervisor so stale sidecar results cannot shape a later request
- [x] 2.3 Dispatch `PreCompact` / `PostCompact` phases and surface compaction transitions through turn-scoped metadata or events

## 3. Stop And Recovery

- [x] 3.1 Introduce a structured stop-phase / post-turn-effects contract between `TurnEngine` and `SessionController`
- [x] 3.2 Make session memory persistence and background extraction consume explicit turn outcomes instead of inferring everything from transcript mutations
- [x] 3.3 Add a budget/recovery policy surface covering provider stop reasons, max-turn exhaustion, tool-result growth, and reactive compaction
- [x] 3.4 Surface continuation transition reasons and recovery decisions through host-visible metadata or turn events
- [x] 3.5 Define explicit turn terminal reasons and map them deterministically onto `SessionStatus` values such as `READY`, `WAITING`, `INTERRUPTED`, and `FAILED`
- [x] 3.6 Ensure every turn exits with exactly one explicit `TurnTerminalReason`, including `max_turns`, `error`, `interrupted`, and `blocked`
- [x] 3.7 Remove bool-based status classification so `SessionController` and child-run projection use terminal reason and terminal metadata instead of `completed`
- [x] 3.8 Update [agent_execution_service.py](../../../../src/runtime/agent_execution_service.py#L202) so child-run status projection is driven by explicit turn terminal reason rather than `turn_result.completed`
- [x] 3.9 Enforce terminal precedence so failure-class outcomes (`model_error`, `aborted_*`, `prompt_too_long`, `image_error`) cannot be rewritten into blocking or waiting-class terminals by stop hooks
- [x] 3.10 Define `TurnResult` so `attempts[]` remain attempt-scoped, `stop_reason` is turn-final only, and `completed` is derived only from the final terminal reason

## 4. Verification

- [x] 4.1 Add tests proving that streaming interfaces are the canonical main-loop path, that aggregate helpers reuse the same contract, and that only legal phase transitions occur
- [x] 4.2 Add tests for sidecar join/cancel/restart behavior across compaction and recovery boundaries
- [x] 4.3 Add tests for `max_tokens` or equivalent budget-recovery paths and terminal observability
- [x] 4.4 Add regression tests ensuring streaming tool orchestration and ordered tool-result replay semantics remain unchanged under the new loop contract
- [x] 4.5 Add tests for session-state projection from turn terminal reasons, including `WAITING`, `INTERRUPTED`, and non-blocking `READY` outcomes
- [x] 4.6 Add tests proving that tool continuation emits attempt outcome without prematurely ending the turn, and that no turn events occur after the unique final terminal
- [x] 4.7 Add tests proving that child-run `error` / `blocked` / `interrupted` outcomes are not mislabeled as `max_turns`
- [x] 4.8 Add tests proving that provider/model error cannot be rewritten into `blocked` / `WAITING` by stop hooks
- [x] 4.9 Add tests proving that `TurnResult.stop_reason` is always turn-final while `TurnResult.attempts[]` remain attempt-scoped
- [x] 4.10 Add migration tests or adapter checks for legacy consumers moving from `TERMINAL(stop_reason=tool_use)` to `ATTEMPT_FINISHED` or equivalent attempt metadata
