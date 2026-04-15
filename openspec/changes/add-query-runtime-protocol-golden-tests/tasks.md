## 1. Fixture Harness

- [ ] 1.1 Build provider-request capture fixtures and turn-event capture helpers for protocol-level assertions
- [ ] 1.2 Build transcript and assembled-runtime test helpers that can replay resume and orchestration scenarios deterministically

## 2. Protocol Golden Coverage

- [ ] 2.1 Add request-level golden tests for `tool_use` / `tool_result` continuation structure
- [ ] 2.2 Add regression fixtures for flattened tool results and orphaned tool/result pairing cases

## 3. Stream And Resume Regression Coverage

- [ ] 3.1 Add regression tests for interrupting slow model streams and discarding incomplete partial output
- [ ] 3.2 Add resume and transcript pairing-repair tests that validate post-recovery provider requests

## 4. Assembly And Host Integration Coverage

- [ ] 4.1 Add end-to-end tests for model-generated built-in `agent` and `skill` tool execution through the assembled runtime
- [ ] 4.2 Add host-level tests that verify a headless or minimal interactive host can consume the runtime turn event stream without reimplementing orchestration
