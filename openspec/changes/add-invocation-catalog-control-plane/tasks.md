## 1. Invocation Catalog Core Types

- [ ] 1.1 Add `InvocationDefinition` and source-kind typing for catalog entries in the runtime core.
- [ ] 1.2 Add explicit visibility-policy fields for invocation entries, including internal normalization of `model_invocable`.
- [ ] 1.3 Add explicit execution-policy fields for invocation entries so exposure concerns remain separate from execution concerns.
- [ ] 1.4 Add `InvocationProvider` and `InvocationRegistry` interfaces for multi-source capability collection.
- [ ] 1.5 Add `InvocationResolutionContext`, `ResolvedInvocationCatalog`, and `InvocationDiagnostics` data shapes for session-scoped resolution and host consumption.

## 2. Skill Projection into the Catalog

- [ ] 2.1 Implement a skill-to-invocation adapter so `SkillDefinition` instances can project into the invocation catalog without changing `SkillExecutor`.
- [ ] 2.2 Map skill visibility metadata such as `display_name`, `description`, `argument_hint`, `user-invocable`, and `disable-model-invocation` into invocation fields.
- [ ] 2.3 Map skill execution metadata such as `context`, `allowed-tools`, `agent`, `model`, `effort`, and `hooks` into invocation execution policy.
- [ ] 2.4 Register the skill-backed provider in runtime assembly so skill entries participate in the unified catalog.

## 3. Session-Scoped Resolution Pipeline

- [ ] 3.1 Collect resolution-context inputs for each session and turn, including prompt-derived paths, attachments, workspace roots, observed paths, and host-provided working sets.
- [ ] 3.2 Implement normalized path activation matching over the resolution context rather than relying on registry-only filtering.
- [ ] 3.3 Distinguish `matched`, `not_matched`, and `indeterminate` path states during resolution.
- [ ] 3.4 Compute visible versus hidden invocation sets from path activation results, keeping path-scoped entries hidden by default when no match can be established.
- [ ] 3.5 Compute `user_invocable` and `model_invocable` independently during resolution instead of collapsing them into a single enabled flag.
- [ ] 3.6 Emit diagnostics that distinguish explicit path mismatch from indeterminate context and preserve any policy-based narrowing information.

## 4. Root Capability Exposure and Host Surfaces

- [ ] 4.1 Update root capability exposure so the main thread consumes resolved visible invocations rather than raw registry contents.
- [ ] 4.2 Define the root-facing capability view that `main-router` and other host surfaces receive from the resolved catalog.
- [ ] 4.3 Add a host-facing query surface for retrieving visible invocation entries for the current session context.
- [ ] 4.4 Add a host-facing diagnostics query surface for hidden, user-disabled, model-disabled, or policy-narrowed invocation entries.
- [ ] 4.5 Clarify runtime naming and docs so `SessionCommand` remains distinct from invocation/catalog concepts.

## 5. Regression Coverage and Provider Extensibility

- [ ] 5.1 Add regression tests covering visible path-scoped invocations when the runtime can prove a context match.
- [ ] 5.2 Add regression tests covering hidden invocations caused by explicit path mismatch.
- [ ] 5.3 Add regression tests covering hidden-by-default behavior when path activation is indeterminate.
- [ ] 5.4 Add regression tests covering separate user-versus-model invocability decisions.
- [ ] 5.5 Add regression tests covering diagnostics output and non-escalation preservation when invocation entries wrap restricted skills.
- [ ] 5.6 Define placeholder provider contracts for slash command, plugin command, and MCP prompt sources without requiring full product implementations in this change.
