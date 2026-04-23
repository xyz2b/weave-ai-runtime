## 1. Delegation Policy Plumbing

- [ ] 1.1 Add runtime-level delegation policy defaults and parsing under the existing runtime metadata policy surface.
- [ ] 1.2 Thread child delegation depth through child execution context, execution metadata, and any shared private runtime state used by child spawn paths.
- [ ] 1.3 Add focused unit coverage for delegation policy parsing and child-depth bookkeeping.

## 2. Enforce Child Delegation Boundaries

- [ ] 2.1 Enforce the configured child delegation ceiling in the shared child execution path used by direct `agent` tool delegation.
- [ ] 2.2 Apply the same child delegation ceiling to forked skill execution so skill forks cannot bypass nested delegation bans.
- [ ] 2.3 Return a structured `delegation_depth_exceeded`-style policy error without allocating a deeper child run when nested delegation is rejected.
- [ ] 2.4 Add regression tests covering default depth rejection, explicit higher ceilings, and consistent rejection behavior across `agent` and forked `skill` paths.

## 3. Project Child Results for Parent Context

- [ ] 3.1 Implement a summary-first parent-facing child result projector that preserves stable identity, status, and terminal metadata while omitting full child `messages[]` by default.
- [ ] 3.2 Add normalized, length-bounded terminal assistant summary extraction plus runtime fallback summaries for denied, failed, or otherwise unsummarized child runs.
- [ ] 3.3 Update `agent` tool and nested forked-skill `agent_result` serialization to use the shared child result projection contract, with summary always present and detailed projection available only as an explicit compatibility mode.

## 4. Align Continuations, Observability, and Docs

- [ ] 4.1 Extend child-run continuation payloads and admitted ingress context to carry summary-aware child completion data.
- [ ] 4.2 Verify that sidechain child-run storage and `CHILD_RUN` observability still retain full child history when parent-facing results are summary-only, and document those surfaces as the migration path for full child history consumers.
- [ ] 4.3 Update runtime docs, golden fixtures, and end-to-end tests to reflect summary-first child results, metadata-backed delegation policy, sidechain truth retention, and the explicit migration-only compatibility mode.
