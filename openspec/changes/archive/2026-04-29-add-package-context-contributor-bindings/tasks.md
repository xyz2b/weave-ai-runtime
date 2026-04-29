## 1. Contribution Model

- [x] 1.1 Add a package contribution binding for collect-style context contributors, including owner metadata, named stage, and deterministic order fields.
- [x] 1.2 Add a runtime-owned context-contributor registry and registration helpers to shared runtime services.
- [x] 1.3 Define the runtime-owned stage catalog and contributor execution metadata that context assembly will consume.

## 2. Runtime Assembly Integration

- [x] 2.1 Apply package-contributed context-contributor bindings during runtime assembly without widening `RuntimeServices` with new package-specific slots.
- [x] 2.2 Update turn-engine context assembly to execute package-contributed contributors through the published runtime-owned stages with bounded failure handling and owner/stage-aware diagnostics.
- [x] 2.3 Preserve the canonical prompt/private carrier contract when merging package-contributed prompt fragments and private updates.

## 3. First-Party Migration

- [x] 3.1 Migrate current collect-style first-party contributors such as memory, hooks, and task-discipline sidecars onto the new package contribution path or explicit adapters.
- [x] 3.2 Keep `CompactionManager` on its dedicated control-plane path and document why it is not collapsed into the generic contributor abstraction.
- [x] 3.3 Mark any retained legacy service-slot access as compatibility-only in runtime metadata and docs.

## 4. Coverage And Docs

- [x] 4.1 Add regression tests for package-contributed context registration, deterministic stage ordering, bounded failure degradation, and prompt/private merge behavior.
- [x] 4.2 Add regression tests proving package contributors can emit private-only diagnostics without leaking them into prompt-visible context.
- [x] 4.3 Update architecture and extension docs to describe package-contributed context contributors as the canonical collect-style request-time attachment path.
