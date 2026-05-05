# Mini Repo Fixture

This repository is intentionally small and intentionally imperfect.

The default live demo task asks the code assistant to:

- fix the default greeting so the tests pass
- add a one-line note under `notes/live_demo.md`
- run the unit tests
- request reviewer and verifier child-agent passes

The fixture's `.weavert/` directory now keeps only the app-owned shell layer.
The official coding scenario pack supplies the reusable `coding-planner`, `reviewer`, `verifier`,
`coding-loop`, `review-change`, `verify-change`, `task-discipline`, and `repo-onboard` workflow surfaces.
