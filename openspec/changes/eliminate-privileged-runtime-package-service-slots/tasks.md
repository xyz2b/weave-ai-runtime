## 1. Protocol Binding Scaffolding

- [x] 1.1 Add runtime-owned protocol identifiers and ownership metadata for memory, compaction, and isolation service families.
- [x] 1.2 Add typed resolver helpers on the shared control-plane surface so owner-layer code can resolve canonical protocol bindings without raw capability-string branching.
- [x] 1.3 Publish compatibility metadata that marks privileged dedicated service slots as non-canonical projections over the new protocol bindings.

## 2. Memory Binding Migration

- [x] 2.1 Migrate session-runtime, turn-runtime, and tool/runtime helper memory call sites to the canonical memory protocol resolver.
- [x] 2.2 Demote `RuntimeServices.memory` to a derived compatibility projection once runtime-owned call sites no longer require it as source of truth.

## 3. Compaction Binding Migration

- [x] 3.1 Migrate turn-preparation and compaction-result call sites to the canonical compaction protocol resolver, then demote `RuntimeServices.compaction` to a derived compatibility projection.

## 4. Isolation Binding Migration

- [x] 4.1 Migrate delegated-execution preparation and cleanup paths to the canonical isolation protocol resolver.
- [x] 4.2 Demote `RuntimeServices.isolation` to a derived compatibility projection once runtime-owned call sites no longer require it as source of truth.

## 5. Verification and Documentation

- [x] 5.1 Add regression coverage and structured conformance findings, using the shared protocol-only finding schema, proving the migrated runtime-owned paths work when only canonical protocol bindings are present.
- [x] 5.2 Update architecture and migration docs to describe the new protocol bindings, their canonical metadata keys, and the compatibility-only status of the retired privileged slots.
