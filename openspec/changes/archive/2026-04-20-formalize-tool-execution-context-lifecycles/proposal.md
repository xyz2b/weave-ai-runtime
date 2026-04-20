## Why

当前 runtime 已经具备较强的 tool capability contract、turn event stream 与 prompt/private context 分层，但工具公开接口、内部装配上下文与状态生命周期边界仍然混在一起。`ToolContext` 同时承担 internal service bag、turn-scoped capability container 和 tool execution ABI，导致 `runtime_services` 继续外泄、`app_state` 生命周期不明确，以及 session/turn/call scope 的 owner 只能靠约定理解。

现在需要把这层边界正式化。一方面，公开给工具的上下文需要收敛成稳定、窄、call-scoped 的 capability view；另一方面，runtime 需要显式声明 `SessionScope`、`TurnScope` 与 call lifecycle 的 owner、创建时机和回收时机，避免后续继续在 `ToolContext` 上叠加更多隐式状态。

## What Changes

- Introduce an explicit split between internal tool assembly context and public tool execution context.
- Define a stable public `ToolExecutionContext` shape for tool authors, based on call-scoped metadata plus shared capability handles.
- Recast the current `ToolContext` as an internal-only runtime object responsible for wiring registries, runners, handlers, and privileged services.
- Replace the ambiguous single `app_state` concept with explicit scoped state handles for session-scoped and turn-scoped runtime state.
- Define explicit `SessionScope`, `TurnScope`, and call-scope ownership and lifecycle boundaries, including who creates, mutates, and disposes each scope.
- Establish an explicit tool trust model separating public tools, privileged built-in tools, and legacy compatibility paths.
- Make runtime-owned registration and assembly data the sole authority for routing tools onto `public`, `privileged`, or `legacy-compat` paths; tool self-description may inform routing but cannot grant elevated execution class by itself.
- Keep any prompt/private execution metadata on the public tool path behind narrow read-only projections or explicit fields rather than exposing the raw private carrier.
- Remove the requirement for public tool execution paths to access raw `runtime_services`, while preserving internal compatibility paths for privileged built-in tools.
- Add a compatibility path so legacy tools can continue to execute while the runtime migrates from the current mixed `ToolContext` ABI to the new public/internal split.
- Define the migration contract for temporary compatibility aliases and bridges, including the requirement that newly added public tools target `ToolExecutionContext` directly and do not depend on compat-only aliases.
- Define terminal lifecycle semantics for session start/resume, turn admission/completion, and call completion, including interruption/failure paths and call disposal after replay commit or equivalent terminal non-executable completion.

## Capabilities

### New Capabilities
- `tool-execution-context-boundaries`: Defines the public/internal tool context split, the public `ToolExecutionContext` contract, scoped state handles, and compatibility requirements for legacy tools.
- `runtime-scope-lifecycles`: Defines explicit `SessionScope`, `TurnScope`, and call-scope ownership, lifecycle transitions, and disposal semantics across session control, turn orchestration, and tool execution.

### Modified Capabilities
- None.

## Impact

- Affected code: `src/runtime/tool_runtime.py`, `src/runtime/tool_lifecycle.py`, `src/runtime/tool_resolution.py`, `src/runtime/tool_orchestration.py`, `src/runtime/turn_engine/engine.py`, `src/runtime/session_runtime/controller.py`, `src/runtime/builtins/tool_impls.py`, and runtime conformance tests.
- Affected APIs: tool execution ABI, internal runtime assembly interfaces, runtime state handles, temporary compatibility aliases during cutover, and lifecycle ownership expectations across session and turn layers.
- Affected systems: tool execution, session control, capability refresh, notification/progress surfaces, tool trust classification and routing authority, and legacy built-in tool compatibility.

## Proposal-Level Clarifications

### Trust Routing Authority

- Runtime-owned registration and assembly data are the authoritative source of truth for `public`, `privileged`, and `legacy-compat` routing.
- Definition frontmatter, plugin metadata, or other tool self-description may act as hints, but they MUST NOT independently grant `privileged` or `legacy-compat` routing.
- Non-runtime-owned tools default to the `public` execution path unless runtime-owned registration explicitly classifies them otherwise.

### Compatibility Contract And Exit Criteria

- During migration, compat-only surface area may remain available for legacy tools that still depend on the mixed `ToolContext` ABI, including temporary aliases such as `app_state`-style turn-state compatibility, raw top-level query identity projections, and metadata/private-carrier bridges needed to preserve existing execution.
- That compat surface is a migration bridge only. Newly added public tools MUST target `ToolExecutionContext` directly and MUST NOT rely on compat-only aliases, raw `runtime_services`, or unrestricted internal registries/runners.
- Runtime-owned built-ins that genuinely need privileged control-plane access should move to the privileged internal path rather than remain indefinitely on the compat path.
- Compat exit criteria are: ordinary tools no longer require the mixed `ToolContext` ABI, runtime-owned built-ins have been reclassified onto `public` or `privileged` paths as appropriate, and conformance coverage proves that newly added non-runtime-owned tools do not default onto the compat route.

### Lifecycle Semantics Across Terminal Paths

- `SessionScope` is created when a session starts or resumes into active execution and remains authoritative across admitted turns in that session.
- `SessionScope` is disposed exactly once when session close semantics complete, including close after success, interruption, or failure.
- `TurnScope` is created when ingress admits a turn for execution and remains authoritative only for that admitted turn.
- When a turn reaches terminal completion, the runtime disposes or replaces that turn scope before any later turn in the same session becomes authoritative.
- `ToolExecutionContext` is call-scoped: it is created after resolution and before execute, remains valid for one tool call, and is disposed after replay commit or equivalent terminal non-executable completion for that call.
- Multiple calls within one turn may share the same turn-scoped handles, but each call receives its own frozen call identity and resolved execution metadata.

## Appendix A: `ToolContext` Field Migration Matrix

This appendix is implementation-oriented. It maps the current mixed `ToolContext` shape to the recommended steady-state owners and indicates which fields should remain visible on the public tool path.

| Current field(s) | Recommended target home | Public path exposure | Migration rule |
| --- | --- | --- | --- |
| `session_id` | `SessionScope.session_id` and `TurnScope.session_id` | not as a raw top-level field; visible through `query.session_id` / call identity | Keep owner identity on scopes; stop passing it as an unstructured public field. |
| `turn_id` | `TurnScope.turn_id` | not as a raw top-level field; visible through `query.turn_id` / call identity | Treat turn identity as turn-owned and call-projected. |
| `agent_name` | `SessionScope.agent_name` and `TurnScope.agent_name` | visible through `query.agent_name` | Keep current duplication only if both owners need it; avoid a standalone public field. |
| `cwd` | `SessionScope.cwd` and `TurnScope.cwd` | visible through `query.cwd` | Same rule as `agent_name`: owner data on scopes, query projection on public path. |
| `messages` | `TurnScope.query` snapshot | visible through `ToolExecutionContext.query` | Remove direct public access to the raw `messages` tuple on the tool context. |
| `tool_pool` | `TurnScope.tool_pool` snapshot | visible only through read-only catalog projection | Convert to turn-owned pool plus public catalog view. |
| `skill_pool` | `TurnScope.skill_pool` snapshot | visible only through read-only catalog projection | Same as `tool_pool`. |
| `tool_registry` | `InternalToolContext` | no | Internal resolution/assembly only. |
| `agent_registry` | `InternalToolContext` | no | Internal lookup and privileged adapter only. |
| `skill_registry` | `InternalToolContext` | no | Internal lookup and privileged adapter only. |
| `progress_sink` | `InternalToolContext` or turn-owned host plumbing | no | Public tools should only see `ProgressHandle`, never the sink. |
| `notification_sink` | `InternalToolContext` or turn-owned host plumbing | no | Public tools should only see `NotificationsHandle`, never the sink. |
| `tool_refresh_callback` | `InternalToolContext` | no | Public tools request refresh through `CapabilityRefreshHandle`. |
| `permission_handler` | `InternalToolContext` | no | Permission mediation remains runtime-internal. |
| `ask_user_handler` | `InternalToolContext` | no | Only privileged adapters should call raw ask-user handlers. |
| `agent_runner` | `InternalToolContext` | no | Runtime control-plane only. |
| `skill_runner` | `InternalToolContext` | no | Runtime control-plane only. |
| `runtime_services` | `InternalToolContext` | no | Never expose on the public tool ABI. |
| `task_manager` | session-owned task registry/service reachable from `SessionScope`, surfaced only on internal path | no | Treat as session control-plane state, not public capability. |
| `abort_signal` | `TurnScope.abort_handle` | yes, via `ToolExecutionContext.abort_handle` | Replace raw signal access with the explicit abort handle. |
| `notifications` | `TurnScope` notification snapshot if still needed | no direct raw exposure | Keep as turn-owned host snapshot or drop if redundant. |
| `permission_context` | runtime-private session/turn state | no raw exposure | Replace with `permission_context_view` on the public path. |
| `private_context` | session/turn private carrier owned by runtime | only through explicit readonly projection such as `private_context_view` | Do not pass the raw private carrier through `ToolExecutionContext`. |
| `pending_hook_effect` | `InternalToolContext` | no | Hook/orchestration-internal only. |
| `metadata` | compat-only bridge during migration | no steady-state public exposure | Replace with typed fields and narrow views; keep only for compat adapter / legacy ingress. |
| `query_context` | `TurnScope.query` | yes | Public execution should receive the query snapshot through `ToolExecutionContext`. |
| `app_state` | split into `SessionStateHandle` and `TurnStateHandle` | yes | Remove the ambiguous single state handle from the public ABI. |
| `file_state` | `TurnScope.file_state` | yes | Keep as turn-scoped handle shared across calls in the same turn. |
| `memory_access` | `SessionScope.memory_access` | yes | Public exposure remains explicit and narrow. |
| `progress` | `TurnScope.progress` | yes | Turn-owned handle reused across calls, projected into `ToolExecutionContext`. |
| `notifications_handle` | `TurnScope.notifications` | yes | Same reuse rule as `progress`. |
| `refresh_capabilities` | `TurnScope.refresh_capabilities` | yes | Same reuse rule as `progress`. |
| `tool_catalog` | turn-owned derived catalog snapshot | yes, read-only | Derive from `tool_pool`; do not keep as mutable service bag state. |
| `agent_catalog_view` | turn-owned derived catalog snapshot | yes if agent discovery remains public; otherwise internal-only | Keep as a read-only catalog, never as a registry handle. |
| `skill_catalog_view` | turn-owned derived catalog snapshot | yes if skill discovery remains public; otherwise internal-only | Keep as a read-only catalog, never as a registry handle. |
| `permission_context_view` | derived public view on turn/call path | yes | This remains the public permission-facing surface. |
| `capability_context` | replaced by `ToolExecutionContext` | no as a separate compat-era wrapper | Phase out once public tools consume `ToolExecutionContext` directly. |
| `tool_use_id` | `ToolExecutionContext.call` | yes | Freeze per call. |
| `replay_index` | `ToolExecutionContext.call` | yes | Freeze per call. |
| `canonical_tool_name` | `ToolExecutionContext.call` | yes | Freeze per call. |
| `selected_executor_tier` | `ToolExecutionContext.query` / call metadata | yes | Preserve as resolved execution metadata, not a mutable context field. |
| `model_capabilities` | `ToolExecutionContext.query` / call metadata | yes | Preserve as resolved execution metadata, not a mutable context field. |
| `progress_callback` | call-orchestration internal plumbing | no | Internal event bridge only. |
| `notification_callback` | call-orchestration internal plumbing | no | Internal event bridge only. |
| `refresh_callback` | call-orchestration internal plumbing | no | Internal event bridge only. |
| `call_updates` | call-orchestration internal accumulator | no | Internal replay/update collection only. |
| `_interrupt_reason` | call-local internal execution state | no | Internal bookkeeping only. |

Implementation note:

- The current `ToolContext.__post_init__()` default construction path should not remain the authoritative lifecycle source for `app_state`, `file_state`, `memory_access`, `query_context`, or turn handles after this migration.
- `metadata` and the raw private carrier remain migration aids, not the long-term public contract.

## Appendix B: Built-in Tool Routing Matrix

This appendix classifies the current bundled built-ins by their recommended steady-state execution class and the suggested migration route during cutover.

| Built-in tool(s) | Steady-state class | Cutover recommendation | Rationale |
| --- | --- | --- | --- |
| `read`, `glob`, `grep` | `public` | If guarded-path capability extraction ships in the same refactor, move directly to `public`; otherwise allow a temporary `legacy-compat` route during cutover only | These are normal workspace read tools by role, but the current implementation still consults raw runtime-owned memory/path guarding helpers. |
| `edit`, `write` | `public` | Same cutover rule as the read tools: preferred direct migration to `public`, temporary `legacy-compat` only if path-guard extraction lags | They are standard filesystem tools and should not stay on a privileged path long-term, even though current path validation still touches runtime internals. |
| `bash` | `public` | Same cutover rule as other filesystem-sensitive tools | `bash` is not a control-plane tool; its current internal coupling comes from path guarding and execution plumbing, not from a privileged runtime role. |
| `web_fetch`, `web_search` | `public` | Move directly to `public` | They do not require raw registries, runners, or runtime service bags. |
| `sleep` | `public` | Move directly to `public` | It only needs bounded interruption and progress/reporting surfaces. |
| `agent` | `privileged` | Route through the internal adapter from the first cutover | It depends on `agent_runner` and runtime-owned subagent orchestration. |
| `skill` | `privileged` | Route through the internal adapter from the first cutover | It depends on `skill_runner` and runtime-owned skill dispatch. |
| `task_create`, `task_get`, `task_update`, `task_list`, `task_stop` | `privileged` | Route through the internal adapter from the first cutover | These operate on runtime-owned task/session control-plane state. |
| `ask_user` | `privileged` | Route through the internal adapter from the first cutover | It depends on host elicitation / ask-user plumbing and should not widen the public ABI. |

Implementation note:

- No bundled built-in should have `legacy-compat` as its steady-state target class.
- `legacy-compat` exists to carry existing implementations across the boundary while their explicit capabilities are extracted; it is not the desired final routing for any built-in listed above.
- If future public tooling needs agent/task/ask-user-like behavior, prefer new public capability wrappers rather than promoting the current privileged built-ins onto the public path.
