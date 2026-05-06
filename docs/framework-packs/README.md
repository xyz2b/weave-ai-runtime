# Framework Packs

First-party add-on packages now assemble from concrete framework-pack projects instead of relying on co-located implementation under `packages/core/src/weavert`.

Role map:

- capabilities: `weavert-memory`, `weavert-team`
- mechanisms: `weavert-compaction`, `weavert-isolation`
- integrations: `weavert-openai`, `weavert-hosts-reference`, `weavert-stores-file`
- workflows: `weavert-planning`, `weavert-devtools`, `weavert-builtin-workflows`

Canonical workspace roots:

- `packages/framework-packs/capabilities`
- `packages/framework-packs/mechanisms`
- `packages/framework-packs/integrations`
- `packages/framework-packs/workflows`

Canonical import roots:

- `weavert_memory`
- `weavert_team`
- `weavert_compaction`
- `weavert_isolation`
- `weavert_openai`
- `weavert_hosts_reference`
- `weavert_stores_file`
- `weavert_planning`
- `weavert_devtools`
- `weavert_builtin_workflows`
