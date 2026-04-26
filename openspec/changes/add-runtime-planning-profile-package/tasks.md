## 1. Package Taxonomy And Distribution Composition

- [ ] 1.1 Add `runtime-planning` to the first-party package taxonomy as a profile/workflow package.
- [ ] 1.2 Update supported distribution composition so `runtime-full` includes `runtime-planning` while `runtime-default` remains unchanged.
- [ ] 1.3 Publish `runtime-planning` through first-party package catalog metadata surfaces.
- [ ] 1.4 Add or update diagnostics and explanatory metadata so embedders can discover planning-profile package selection state.

## 2. Planning Profile Package Surface

- [ ] 2.1 Create the `runtime-planning` package module surface and built-in loading entrypoints for package-owned planning definitions.
- [ ] 2.2 Add the `planner` built-in agent definition with the canonical `task_*`-centered profile boundary.
- [ ] 2.3 Add the `coordinator` built-in agent definition with the canonical `task_* + job_*` profile boundary.
- [ ] 2.4 Add the `worker` built-in agent definition with the canonical execution-focused profile boundary.
- [ ] 2.5 Register `runtime-planning` built-ins through the ordinary built-in pack loader so ownership metadata, visibility rules, and replacement behavior match other first-party packages.
- [ ] 2.6 Keep the existing `plan` helper in `runtime-devtools` unchanged for the first landing and encode the distinct canonical ownership boundary in code.

## 3. Runtime Wiring

- [ ] 3.1 Wire `runtime-planning` into first-party package selection paths.
- [ ] 3.2 Wire `runtime-planning` into runtime assembly and package-catalog publication paths.
- [ ] 3.3 Ensure planning profiles do not change the core ownership of `task_*`, `job_*`, or task/job host bridge surfaces.

## 4. Regression Coverage

- [ ] 4.1 Add regression tests covering `runtime-core`, `runtime-default`, and `runtime-full` package selection so planning profiles only appear when `runtime-planning` is selected.
- [ ] 4.2 Add regression tests covering explicit enablement and disablement of `runtime-planning`.
- [ ] 4.3 Add regression tests that builtin ownership metadata reports `runtime-planning` for `planner`, `coordinator`, and `worker`.
- [ ] 4.4 Add regression tests that `plan` remains owned by `runtime-devtools`.
- [ ] 4.5 Add regression tests proving that `task_*` and `job_*` remain available through `runtime-core` even when `runtime-planning` is not installed.

## 5. Docs, Migration Notes, And Positioning

- [x] 5.1 Update runtime architecture and integration docs to describe the split between planning control-plane primitives in `runtime-core` and planning profile UX in `runtime-planning`.
- [x] 5.2 Update built-in ownership and package-composition docs to include `runtime-planning`, `planner`, `coordinator`, and `worker`.
- [x] 5.3 Add migration notes that distinguish the existing `plan` helper from the new first-party planning profiles and explain when embedders should choose each.
- [x] 5.4 Document that task-discipline and other runtime-owned planning policies remain in core for this landing, with any later policy extraction treated as follow-up work.
