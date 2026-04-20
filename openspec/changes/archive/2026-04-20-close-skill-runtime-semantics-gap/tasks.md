> 这一版任务单补到了“实现约束级”：每项都说明主要模块、状态合同、依赖与验收口径，但不下沉到具体函数实现。

## 1. Session-Scoped Dynamic Skill Roots

- [x] 1.1 Add session metadata / private-context support for dynamic skill roots and resume-safe activation evidence.
  Owner modules: `src/runtime/session_runtime/controller.py`, `src/runtime/contracts.py`, `src/runtime/runtime_kernel/kernel.py`.
  State contract: persist serializable `skill_dynamic_roots` records in session metadata / private-context extensions; reuse existing `observed_paths` as activation evidence.
  Dependencies: none.
  Acceptance: after `SessionController.resume()`, invocation resolution sees the same discovered roots and path-backed activation evidence as before suspend.
- [x] 1.2 Implement de-duplicated upward discovery of nested `.runtime/skills` roots from observed workspace paths.
  Owner modules: `src/runtime/runtime_kernel/kernel.py`, `src/runtime/tool_orchestration.py`, `src/runtime/registries/discovery.py`.
  State contract: only walk upward from observed paths that remain under the session cwd; root records must be de-duplicated by normalized absolute root path.
  Dependencies: 1.1.
  Acceptance: observing a file under a nested subtree discovers the closer `.runtime/skills` root during the same session without duplicating broader roots.
- [x] 1.3 Add a runtime-kernel cache for parsing skill definitions from discovered roots.
  Owner modules: `src/runtime/runtime_kernel/kernel.py`, `src/runtime/registries/discovery.py`.
  State contract: cache is kernel-local and keyed by normalized root path; cached values may include parsed definitions and diagnostics, but never transcript/session state.
  Dependencies: 1.2.
  Acceptance: repeated resolution against the same discovered root reuses cached parse results until the root is explicitly refreshed.
- [x] 1.4 Build merged effective skill views that preserve existing source precedence and prefer deeper roots within the same source class.
  Owner modules: `src/runtime/runtime_kernel/kernel.py`, `src/runtime/registries/skill_registry.py`, `src/runtime/definitions.py`.
  State contract: source-class priority remains unchanged; only same-source conflicts receive a deeper-root-wins tie-breaker.
  Dependencies: 1.2, 1.3.
  Acceptance: same-name project-root and nested-root skills resolve to the nested root, while cross-source conflicts still follow existing origin priority.

## 2. Activation, Visibility, And Diagnostics

- [x] 2.1 Extend invocation resolution to track discovered roots, activation eligibility, and richer hidden reasons.
  Owner modules: `src/runtime/definitions.py`, `src/runtime/invocation_catalog.py`.
  State contract: diagnostics metadata must identify discovery source/root, path match state, and policy narrowing without creating a second authority outside `ResolvedInvocation`.
  Dependencies: 1.4.
  Acceptance: hidden skills can be explained as inactive, path-mismatched, indeterminate, or policy-narrowed with root-aware diagnostics.
- [x] 2.2 Unify host-visible, model-visible, and executable skill gating on top of one resolved invocation decision path.
  Owner modules: `src/runtime/invocation_catalog.py`, `src/runtime/turn_engine/engine.py`, `src/runtime/runtime_kernel/kernel.py`.
  State contract: host listings, model skill pool construction, and explicit execution validation must all read the same resolved catalog decision.
  Dependencies: 2.1.
  Acceptance: a host-only skill remains visible to host queries but excluded from model skill pools, and policy-narrowed skills are rejected consistently on execution.
- [x] 2.3 Add regression tests for nested skill discovery, same-name shadowing, path mismatch, and hidden diagnostic reporting.
  Owner modules: `tests/test_discovery.py`, `tests/test_invocation_catalog.py`.
  State contract: test fixtures must exercise nested `.runtime/skills` roots and root-aware diagnostics rather than only flat skill dirs.
  Dependencies: 1.4, 2.1, 2.2.
  Acceptance: tests prove nested discovery, deeper-root precedence, path mismatch, and hidden-reason reporting.
- [x] 2.4 Add resume-path tests ensuring observed-path activation and discovered roots are restored after transcript resume.
  Owner modules: `tests/test_invocation_catalog.py`, `tests/test_agent_skill_runtime.py`.
  State contract: tests must verify session resume uses persisted `skill_dynamic_roots` and `observed_paths`, not an in-memory shortcut.
  Dependencies: 1.1, 2.1.
  Acceptance: a resumed session resolves the same active path-scoped skills before any new prompt is ingressed.

## 3. Request-Shaping Skill Policy

- [x] 3.1 Introduce a dedicated skill request override state for `model` and `effort`.
  Owner modules: `src/runtime/contracts.py`, `src/runtime/skill_runtime.py`, `src/runtime/turn_engine/engine.py`.
  State contract: add an internal `SkillRequestOverrideState` and transport it through the canonical `skill_request_override` private-context key containing `requested_model`, `requested_effort`, and `source_skill`.
  Dependencies: none.
  Acceptance: runtime can carry skill-shaped request data without extending `ExecutionPolicy`.
- [x] 3.2 Apply inline skill overrides to the next request build with consume-once semantics.
  Owner modules: `src/runtime/skill_runtime.py`, `src/runtime/turn_engine/engine.py`.
  State contract: inline execution only writes pending override fields explicitly declared by the skill; request build consumes and clears the override exactly once.
  Dependencies: 3.1.
  Acceptance: the first request after inline skill execution uses the override, while a later request falls back to agent defaults unless another skill rewrites it.
- [x] 3.3 Implement field-level last-write-wins behavior when multiple inline skills shape one pending request.
  Owner modules: `src/runtime/skill_runtime.py`, `src/runtime/turn_engine/engine.py`.
  State contract: `model` and `effort` are merged independently; a later skill only replaces fields it explicitly sets.
  Dependencies: 3.1, 3.2.
  Acceptance: two inline skills can combine into one pending override and the later explicit field wins without wiping the untouched field.
- [x] 3.4 Forward forked skill overrides into child `AgentInvocation` without mutating parent pending request state.
  Owner modules: `src/runtime/skill_runtime.py`, `src/runtime/agent_runtime.py`.
  State contract: add `requested_effort` to `AgentInvocation` beside existing `requested_model`; forked execution may populate child request-shaping fields but must not modify parent `skill_request_override`.
  Dependencies: 3.1.
  Acceptance: child execution receives both requested fields while the parent session keeps its prior pending override state unchanged.

## 4. Prompt Expansion And Shell Execution

- [x] 4.1 Extract a shared skill prompt expander for argument, session, and skill-directory variable substitution.
  Owner modules: `src/runtime/skill_runtime.py` or a sibling expander module under `src/runtime/`.
  State contract: inline and forked execution paths must call the same expander; variable substitution support is fixed to `$ARGUMENTS`, `${ARG1...}`, `${CLAUDE_SESSION_ID}`, and `${CLAUDE_SKILL_DIR}`.
  Dependencies: none.
  Acceptance: both inline and forked skill content render the same expanded prompt for identical inputs.
- [x] 4.2 Add reference-compatible shell block parsing for local file-backed skills.
  Owner modules: `src/runtime/skill_runtime.py` or the extracted expander module.
  State contract: shell parsing is enabled only for file-backed local skills; unsupported sources do not get a permissive fallback path.
  Dependencies: 4.1.
  Acceptance: local skills with reference-compatible inline or fenced shell blocks are parsed for execution, while non-local sources surface an expansion error.
- [x] 4.3 Execute skill shell blocks through the existing shell tool path, honoring `shell` frontmatter and current permission constraints.
  Owner modules: `src/runtime/skill_runtime.py`, existing shell tool execution path, `src/runtime/turn_engine/engine.py`.
  State contract: `shell` frontmatter chooses interpreter only; execution must still go through the current shell tool, permission checks, and tool lifecycle hooks.
  Dependencies: 4.2.
  Acceptance: a skill with `shell: powershell` uses the PowerShell-backed shell path and still emits normal permission / lifecycle signals.
- [x] 4.4 Surface shell expansion failures, permissions, telemetry, and observed paths through the existing runtime channels.
  Owner modules: `src/runtime/skill_runtime.py`, `src/runtime/tool_orchestration.py`.
  State contract: shell expansion is fail-closed; partial output is never injected, and telemetry / observed paths continue to flow through the existing shell-tool channels.
  Dependencies: 4.3.
  Acceptance: permission denials, timeouts, and non-zero exits fail the skill expansion and are visible through normal tool/skill diagnostics.

## 5. End-To-End Verification

- [x] 5.1 Add end-to-end tests for inline skill model / effort overrides and forked child override propagation.
  Owner modules: `tests/test_agent_skill_runtime.py`.
  State contract: tests must cover consume-once inline override, field-level merge, and child-only fork propagation including the new `requested_effort` path.
  Dependencies: 3.2, 3.3, 3.4.
  Acceptance: test assertions prove request shaping on the next parent request and on the child invocation separately.
- [x] 5.2 Add end-to-end tests for non-user-invocable skills, path-ineligible user invocations, and policy-narrowed skill execution.
  Owner modules: `tests/test_invocation_catalog.py`, `tests/test_agent_skill_runtime.py`.
  State contract: tests must validate both visibility surfaces and execution rejection behavior, not only catalog listing output.
  Dependencies: 2.1, 2.2.
  Acceptance: non-user-invocable, path-ineligible, and policy-narrowed cases fail with diagnostic-backed rejection behavior.
- [x] 5.3 Add end-to-end tests for successful shell expansion and fail-closed shell error paths.
  Owner modules: `tests/test_agent_skill_runtime.py`.
  State contract: tests must cover success, permission denied, timeout/non-zero exit, and unsupported-source behavior.
  Dependencies: 4.2, 4.3, 4.4.
  Acceptance: successful shell expansion injects command output, while every failure mode aborts expansion without partial prompt injection.
- [x] 5.4 Verify the full change with targeted `pytest` coverage for discovery, invocation catalog, and skill runtime behavior.
  Owner modules: `tests/test_discovery.py`, `tests/test_invocation_catalog.py`, `tests/test_agent_skill_runtime.py`.
  State contract: verification remains limited to targeted skill-runtime suites; this change does not require unrelated integration suites.
  Dependencies: 2.3, 2.4, 5.1, 5.2, 5.3.
  Acceptance: `pytest tests/test_discovery.py tests/test_invocation_catalog.py tests/test_agent_skill_runtime.py` passes with the new scenarios in place.
