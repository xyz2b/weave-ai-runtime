# Coding Workflow Fixture

This workspace is intentionally tiny and intentionally broken.

## What this fixture is for

- give the ordinary coding workflow demo a small workspace-local target
- keep the task on the ordinary extension path through local `.weavert/` definitions
- share one fixture between offline validation and live smoke

## Task this fixture supports

The coding workflow demo asks the runtime to:

- inspect the greeting bug through workspace-local `.weavert/` definitions
- update the default greeting so the tests pass
- run `python3 -m unittest discover -s tests`
- run a review pass through the local `review-change` skill

## Validation note

The same task, fixture, and success criteria are used by both the default offline demo and the optional `--live` smoke path.

## See also

- `../../../README.md`
- `../../../../docs/guides/build-your-first-project.md`
- `../../../../docs/guides/testing-and-observability.md`
