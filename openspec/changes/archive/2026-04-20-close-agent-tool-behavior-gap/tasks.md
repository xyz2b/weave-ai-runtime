## 1. Agent Context and Router Prompt

- [x] 1.1 Add `available_agents` to `TurnContext` in `src/claude_agent_runtime/contracts.py` and thread the field through `ContextAssembler` and `TurnEngine` request composition in `src/claude_agent_runtime/turn_engine/composer.py` and `src/claude_agent_runtime/turn_engine/engine.py`.
- [x] 1.2 Implement the v1 `available_agents` filtering rule from the design appendix: use visible registry entries, exclude the current active agent, preserve registration order, and serialize only `name + description` into the main-thread `Agents:` prompt section.
- [x] 1.3 Rewrite the built-in `main-router` definition in `src/claude_agent_runtime/builtins/agents.py` so the prompt explicitly orders direct answer, tool use, skill use, and subagent delegation.
- [x] 1.4 Add regression tests in `tests/test_agent_skill_runtime.py` that assert `ModelRequest.turn_context.available_agents` is populated and the composed system prompt includes the filtered `Agents:` section.

## 2. Agent Tool Delegation Contract

- [x] 2.1 Expand the built-in `agent` tool definition in `src/claude_agent_runtime/builtins/tools.py` to match the frozen v1 input contract from the design appendix, including `spawn_mode`, `cwd`, `model`, `model_route`, `reason`, `permission_mode`, `isolation`, and `max_turns`.
- [x] 2.2 Implement input validation and normalization in `src/claude_agent_runtime/builtins/tool_impls.py` for the expanded `agent` tool contract, including relative `cwd` resolution, `spawn_mode` versus legacy `background` precedence, and rejection of invalid enum or path values.
- [x] 2.3 Extend `AgentRunner` and `AgentInvocation` in `src/claude_agent_runtime/tool_runtime.py` and `src/claude_agent_runtime/agent_runtime.py`, then thread the validated child execution overrides through `AgentDispatcher` and `AgentExecutionSpec`.
- [x] 2.4 Expand `_serialize_agent_run_result()` in `src/claude_agent_runtime/runtime_kernel/kernel.py` so `agent` tool results include `run_id`, `parent_run_id`, `turn_id`, `query_source`, `requested_model`, `requested_model_route`, `resolved_model_route`, and `terminal_metadata` in addition to current fields.
- [x] 2.5 Add regression tests in `tests/test_agent_skill_runtime.py` covering sync/background delegation, explicit `spawn_mode` precedence, invalid `agent` tool inputs, and the full structured result payload returned by `agent` tool execution.

## 3. Child Run Observability

- [x] 3.1 Add a configurable `child_run_store` binding to `RuntimeConfig` and runtime assembly in `src/claude_agent_runtime/runtime_kernel/config.py` and `src/claude_agent_runtime/runtime_kernel/kernel.py` while preserving `InMemoryChildRunStore` as the default fallback.
- [x] 3.2 Ensure `AgentExecutionService` in `src/claude_agent_runtime/agent_execution_service.py` writes structured `AgentRunRecord` entries for sync, background, denied, and early-failed children, including stable linkage, terminal metadata, and stored child messages.
- [x] 3.3 Preserve child message history only in sidechain records and child-run queries, without merging full child internals into the main transcript flow in `src/claude_agent_runtime/session_runtime/controller.py`.
- [x] 3.4 Add `TurnStreamEventType.CHILD_RUN` and `TurnStreamEvent.child_run` in `src/claude_agent_runtime/turn_engine/engine.py`, then emit child lifecycle snapshots from execution service and forward them through `SessionController` and host adapters.
- [x] 3.5 Add regression tests covering running-to-terminal background updates, denied child records, fork linkage, session-level child run listing, and host-visible `CHILD_RUN` event propagation.

## 4. Route-Aware Agent Execution

- [x] 4.1 Add `model_route` to `AgentDefinition` and discovery loading in `src/claude_agent_runtime/definitions.py` and `src/claude_agent_runtime/registries/discovery.py`, then add minimal `ModelRouteBinding` plus `model_routes` and `default_model_route` to `RuntimeConfig`.
- [x] 4.2 Implement route resolution precedence in `src/claude_agent_runtime/agent_execution_service.py`: execution-time route override, then agent `model_route`, then inherited route hint, then runtime default route, while keeping `model` override within the resolved route.
- [x] 4.3 Extend `ModelRequest` in `src/claude_agent_runtime/turn_engine/models.py` and child run metadata in `src/claude_agent_runtime/agent_execution.py` / `src/claude_agent_runtime/agent_execution_service.py` to carry `requested_model_route`, `resolved_model_route`, `provider_name`, `resolved_capabilities`, and `invocation_mode`.
- [x] 4.4 Add request-scoped model client override support in `src/claude_agent_runtime/turn_engine/engine.py` so different agent executions in the same session can call different resolved route clients without replacing the shared runtime default client.
- [x] 4.5 Add regression tests covering same-session multi-route execution, route precedence, model override without reroute, and `resolved_model_route` persistence in `AgentRunRecord`.

## 5. Buffered Tool-Capable Completion Path

- [x] 5.1 Add invocation-mode selection in `src/claude_agent_runtime/turn_engine/engine.py` so turn execution can choose `stream` or `buffered_completion` from resolved route capabilities or bound adapter capabilities.
- [x] 5.2 Implement a buffered attempt path in `src/claude_agent_runtime/turn_engine/engine.py` that consumes `ModelClient.complete()`, requires runtime-native `ToolUseBlock` content for tool-capable responses, and normalizes assistant messages and terminal metadata using the design appendix contract.
- [x] 5.3 Reuse the existing tool executor / orchestrator continuation path so buffered execution preserves ordered tool-result replay and the same terminal metadata shape as streaming execution.
- [x] 5.4 Add regression tests in `tests/test_streaming_tool_runtime.py` for complete-only providers with and without tool calls, plus parity assertions for streaming-vs-buffered terminal metadata and ordered continuation behavior.
