# Local State

Repository-local generated state, scratch work, and durable example artifacts belong under `.local/`.

Examples:

- `.local/examples/code_assistant/` for mutable example state
- `.local/runtime/` for checkout-scoped runtime scratch data
- `.local/tmp/` for ad hoc repository-local experiments

Legacy roots such as `.runtime/`, `.weavert/`, or `tmp-*` may still exist from older runs, but new guidance and new tooling should target `.local/`.
