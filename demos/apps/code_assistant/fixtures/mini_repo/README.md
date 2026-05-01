# Mini Repo Fixture

This repository is intentionally small and intentionally imperfect.

The default live demo task asks the code assistant to:

- fix the default greeting so the tests pass
- add a one-line note under `notes/live_demo.md`
- run the unit tests
- request reviewer and verifier child-agent passes

The fixture's `.weavert/` directory defines the app-local agents and skill used by the live demo.
