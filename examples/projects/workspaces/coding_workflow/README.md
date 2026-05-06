# Coding Workflow Fixture

This workspace is intentionally tiny and intentionally broken.

The coding workflow demo asks the runtime to:

- inspect the greeting bug through workspace-local `.weavert/` definitions
- update the default greeting so the tests pass
- run `python3 -m unittest discover -s tests`
- run a review pass through the local `review-change` skill

The same task, fixture, and success criteria are used by both the default offline demo and the optional `--live` smoke path.
