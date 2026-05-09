# Migration Notes

This page collects the highest-level migration concerns for maintainers.

## Who is this for?

- Maintainers and contributors working on this repository rather than first-time framework adopters.

## Prerequisites

- Read `../README.md` first so the public docs flow stays intact.
- Use `../../examples/README.md` as the runnable validation path while changing the repo.

## Runtime boundary migration

The detailed runtime migration ledger remains in `runtime-boundary-migration-ledger.md`.
Start there when you need package-boundary, hook-surface, or distribution migration details.

## Documentation information-architecture migration

The docs now present a layered journey:

1. root landing page
2. getting started
3. concepts
4. guides
5. architecture, reference, maintainers

Use the new structure for new links and new docs.
Keep the long-form historical material under `../deep-dives/` instead of the `docs/` root.
Treat deep dives as secondary contract ledgers, not as the main user journey.

## Deep-dive to primary-doc mapping

- `../deep-dives/current-system-architecture.md` -> `../architecture/overview.md`, `../architecture/request-lifecycle.md`
- `../deep-dives/weavert-integration-guide.md` -> `../getting-started/quickstart.md`, `../guides/bind-a-host.md`, `../guides/integrate-openai.md`
- `../deep-dives/weavert-user-extension-guide.md` -> `../concepts/tools-agents-skills.md`, `../guides/add-a-tool.md`, `../guides/add-an-agent.md`, `../guides/add-a-skill.md`
- `../deep-dives/weavert-definition-authoring-guide.md` -> `../concepts/tools-agents-skills.md`, `../guides/add-a-tool.md`, `../guides/add-an-agent.md`, `../guides/add-a-skill.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md` -> `../concepts/packages-and-scenario-packs.md`, `../architecture/package-system.md`
- `../deep-dives/weavert-scenario-runtime-pack-quickstart.md` -> `../guides/use-scenario-packs.md`
- retired root `weavert-starter-scaffolds.md` -> `../getting-started/starter-scaffolds.md`
- `../deep-dives/weavert-control-plane-extension-guide.md` -> `../guides/extend-the-control-plane.md`, `../guides/register-hooks.md`, `../guides/bind-a-host.md`
- `../deep-dives/weavert-hook-configuration-platform.md` -> `../guides/register-hooks.md`, `../reference/hook-registration.md`
- `../deep-dives/weavert-workflow-observability.md` -> `../guides/testing-and-observability.md`, `../reference/workflow-observability.md`
- `../deep-dives/weavert-openai-responses-adapter.md` -> `../guides/integrate-openai.md`
- `../deep-dives/layered-memory-weavert-v2.md` -> `../concepts/memory-model.md`, `../reference/memory-configuration.md`, `../architecture/persistence-and-state.md`

## Maintainer advice

- do not let `README.md` turn back into a full manual
- keep guides task-oriented and short
- keep maintainer material physically separate from end-user docs
- prefer stable, predictable English filenames for new pages

## Next step

- Read the detailed ledger in `runtime-boundary-migration-ledger.md` when you need the source-of-truth migration history.
- Return to `../architecture/package-system.md` if the migration question is really about package activation or ownership.
- Use `validation-findings.md` when a migration still needs validation evidence or follow-up tracking.

## See also

- `runtime-boundary-migration-ledger.md`
- `../deep-dives/README.md`
- `repository-layout.md`
- `validation-findings.md`
