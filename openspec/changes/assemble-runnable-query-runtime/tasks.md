## 1. Runtime Assembly Layer

- [ ] 1.1 Introduce a formal runtime assembly object that builds `TurnEngine`, `AgentRuntime`, `SkillExecutor`, session factories, and transcript wiring from kernel configuration
- [ ] 1.2 Update host runtime entrypoints to return the assembled runtime stack instead of only registries and a bound host shell

## 2. Handler Wiring

- [ ] 2.1 Wire `agent_runner`, `skill_runner`, `permission_handler`, and `ask_user_handler` into `TurnEngine` through the assembly layer
- [ ] 2.2 Ensure model-generated built-in `agent` and `skill` tool calls execute through the assembled runtimes without requiring test-only manual injection

## 3. Tool And Session Context

- [ ] 3.1 Expand `ToolContext` with turn-scoped messages, request abort handles, notifications, and tool refresh callbacks needed by query runtime execution
- [ ] 3.2 Refactor `SessionController` to drive turn execution from the streamed turn interface while preserving queue, interrupt, and resume semantics

## 4. Host Surface And Compatibility

- [ ] 4.1 Add minimal shared runtime surfaces for interactive and headless hosts to consume assembled turn execution
- [ ] 4.2 Demote direct `/tool`, `/skill`, and `/agent` string routing helpers to debug or compatibility paths rather than primary runtime wiring
