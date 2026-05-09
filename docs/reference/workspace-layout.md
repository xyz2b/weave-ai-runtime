# Workspace Layout

A typical WeaveRT project keeps its local runtime definitions under `.weavert/`.

```text
your-project/
|- app.py
|- pyproject.toml
`- .weavert/
   |- agents/
   |- tools/
   `- skills/
```

## Who is this for?

- Readers who already know the workflow and now need a stable lookup page.

## Prerequisites

- Read the matching guide or concept page first.
- Treat this page as a reference sheet, not the first-stop tutorial.

## Common discovery roots

Ordinary workflow presets usually include:

- user scope: `~/.weavert`
- project scope: `<project>/.weavert`

## File-backed discovery rules

- tools: `tools/*.py`
- agents: `agents/*.md`
- skills: `skills/**/SKILL.md`

## Source precedence reminder

The effective precedence is not "project overrides everything".
In practice, bundled surfaces still win over user and project-local definitions with the same name.
Prefer new names or explicit bundled replacement in Python assembly code when you need a real override.

## Repository-level directories in this repository

- `docs/`
- `examples/`
- `packages/`
- `tests/`

For repository maintainer layout rules, see `../maintainers/repository-layout.md`.

## Next step

- Return to `../guides/build-your-first-project.md` to apply this layout to a real project.
- Add capability through `../guides/add-a-tool.md`, `../guides/add-an-agent.md`, or `../guides/add-a-skill.md` once the layout is in place.
- Use `../maintainers/repository-layout.md` only when the question is about this repository rather than a user project.

## See also

- `../getting-started/starter-scaffolds.md`
- `../guides/build-your-first-project.md`
- `../maintainers/repository-layout.md`
