# Framework Packs

This family root is a placeholder for first-party add-on packages that extend the runtime without belonging to the `weavert` core package.

Planned population:

- `extract-framework-packs-from-core`
- follow-on package-local extraction work that creates concrete packages under `packages/framework-packs/`

Do not add a family-level `pyproject.toml` here. Each real pack should own its own package-local metadata when it is introduced.
