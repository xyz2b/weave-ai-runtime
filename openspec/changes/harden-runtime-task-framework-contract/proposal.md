## Why

The runtime has already established `task/todo` as a runtime-owned planning primitive, but its public framework contract is still uneven. Tool schemas, host bridge surfaces, task-retirement semantics, and persistence guarantees do not yet line up cleanly enough for embedders to treat task control as a stable product-facing capability.

## What Changes

- Narrow the public `task_update` contract so built-in schemas, runtime validation, and documentation expose the same allowed mutation set.
- Add a runtime-owned task framework contract that defines stable lifecycle operations for task mutation, retirement, and visibility instead of leaving those behaviors implicit in service internals.
- Extend the host bridge with task mutation APIs that mirror the public task control plane, so hosts do not need to route user actions back through agent tool calls or private service access.
- Add explicit public task-retirement semantics, including a host- and tool-visible distinction between reversible archival and destructive deletion.
- Define the default task-list durability and concurrency boundary, including crash-safe persistence expectations and the limits of the file-backed single-runtime store.
- **BREAKING** Remove unsupported orchestration fields from the public `task_update` schema and require dedicated task orchestration operations for ownership and dependency mutations.

## Capabilities

### New Capabilities

- `task-framework-contract`: stable framework-facing contract for task mutation, retirement, visibility, and persistence guarantees across tools, host APIs, and runtime services.

### Modified Capabilities

- `builtin-runtime-pack`: narrow the public `task_update` schema, add first-class task retirement tools, and keep built-in task surfaces aligned with the runtime-owned task contract.
- `host-runtime-bridge`: add task mutation and retirement APIs alongside the existing task query/watch surfaces so hosts can drive the shared task plane directly.

## Impact

- Affected code: `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/task_lists.py`, `src/runtime/runtime_kernel/kernel.py`, `src/runtime/hosts/base.py`, and task-control-plane tests.
- Public APIs: built-in `task_*` schemas, bound host runtime task APIs, and task snapshot visibility semantics.
- Persistence: default file-backed task-list storage needs explicit atomic-write behavior and documented single-writer limitations.
- Documentation: runtime integration, extension, and architecture guides need to describe task archival/deletion semantics, host mutation entrypoints, and the supported persistence boundary.
