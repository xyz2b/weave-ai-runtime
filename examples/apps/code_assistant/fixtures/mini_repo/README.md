# Mini Repo Fixture

This repository is intentionally small and intentionally imperfect.

## What this fixture is for

- give the advanced code-assistant sample a tiny mutable workspace
- keep the task small enough that validation output stays legible
- separate the app-owned shell layer from scenario-pack-owned workflow surfaces

## Task this fixture supports

The default live demo task asks the code assistant to:

- fix the default greeting so the tests pass
- add a one-line note under `notes/live_demo.md`
- run the unit tests
- request reviewer and verifier child-agent passes

## Ownership note

The fixture's `.weavert/` directory now keeps only the app-owned shell layer.
The official coding scenario pack supplies the reusable `coding-planner`, `reviewer`, `verifier`,
`coding-loop`, `review-change`, `verify-change`, `task-discipline`, and `repo-onboard` workflow surfaces.

## See also

- `../../README.md`
- `../../../../README.md`
- `../../../../../packages/product-kits/coding/README.md`
- `../../../../../docs/guides/use-scenario-packs.md`
