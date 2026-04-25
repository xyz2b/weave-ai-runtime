## Implementation Landing Order

- `runtime-core` first: freeze contracts, supported distributions, core built-ins, hook surface, and compatibility boundaries before moving package-owned implementations.
- `runtime-memory` and `runtime-team` second: move first-party capability implementations behind the new assembly seams while keeping `runtime-default` runnable.
- `runtime-devtools` third: move workspace-oriented tools and specialized agents out of the kernel path without changing core boot semantics.
- Secondary first-party packages fourth: extract compaction, isolation, provider integrations, reference hosts, file stores, and reusable workflow packs in documented waves.
- Cross-package migration hardening throughout: keep docs, diagnostics, tests, and rollout notes aligned with the converged package story.

## Distribution Rollout View

| Stage | Packages landing | `runtime-default` after this stage | `runtime-full` after this stage |
| --- | --- | --- | --- |
| 1 | `runtime-core` | not complete yet | not complete yet |
| 2 | `runtime-memory`, `runtime-team` | supported baseline complete | inherits the supported baseline |
| 3 | `runtime-devtools` | unchanged | partial full distribution; devtools layer lands |
| 4 | `runtime-compaction`, `runtime-isolation` | unchanged | partial full distribution; mechanism layer lands |
| 5 | `runtime-openai`, `runtime-hosts-reference`, `runtime-stores-file` | unchanged | partial full distribution; provider and adapter layer lands |
| 6 | `runtime-builtin-workflows` | unchanged | supported full distribution complete |

## 1. `runtime-core`

- [x] 1.1 Introduce the package-role and distribution-profile model for `runtime-core`, official first-party packages, and the supported `runtime-default` / `runtime-full` distributions.
- [x] 1.2 Publish the first-party package taxonomy and dependency rules covering capability, mechanism, adapter, provider, and profile/workflow packages.
- [x] 1.3 Update public exports and runtime initialization paths so `runtime-core` remains directly runnable without breaking `runtime-default` or `runtime-full`.
- [x] 1.4 Split built-in definitions into core versus official optional packs, keeping runtime-generic tools and the default root-agent boot path in `runtime-core`.
- [x] 1.5 Keep `main-router` on the default core boot path and preserve built-in replacement behavior for `main-router` and other bundled core definitions.
- [x] 1.6 Reduce the stable public hook catalog to the approved v1 phases and mark remaining lifecycle points as advanced or internal in code and docs.
- [x] 1.7 Narrow the stable hook registration story to runtime config, host integrations, skill-owned hooks, and session-facing APIs; keep turn-scoped programmatic APIs advanced-only.
- [x] 1.8 Make `callback` the only required public hook handler kind and gate or demote `http`, `command`, `agent`, and `prompt` handlers as advanced or package-specific surfaces.
- [ ] 1.9 Freeze `TaskManager` and shared `runtime_context` as bounded compatibility surfaces and remove any new authoritative dependencies on them from runtime-owned code.
- [x] 1.10 Add regression coverage that assembles `runtime-core` alone and verifies root boot, stable hook behavior, built-in replacement, and compatibility diagnostics.

## 2. `runtime-memory`

- [ ] 2.1 Move first-party memory implementation wiring behind explicit runtime service, provider, manager, and assembly contracts while preserving current memory behavior.
- [ ] 2.2 Re-home memory-owned workflows and skills, especially `remember`, into `runtime-memory` rather than `runtime-core`.
- [ ] 2.3 Ensure `runtime-default` wires the first-party memory capability automatically without private kernel imports or third-party discovery steps.
- [ ] 2.4 Add regression coverage that retrieval, post-turn extraction, memory scope behavior, and session availability remain unchanged after the package move.

## 3. `runtime-team`

- [ ] 3.1 Move first-party team control and teammate orchestration wiring behind explicit runtime service and assembly contracts while preserving current behavior.
- [ ] 3.2 Re-home team-owned tools such as `team_create`, `team_spawn`, `team_send`, `team_respond`, and `team_delete` into `runtime-team`.
- [ ] 3.3 Preserve shared execution reuse, host-facing behavior, observability, and lifecycle projection contracts when teammate orchestration lives outside `runtime-core`.
- [ ] 3.4 Add regression coverage that `runtime-default` still includes team control and teammate orchestration out of the box.

## 4. `runtime-devtools`

- [ ] 4.1 Move workspace-, file-, shell-, and web-oriented built-ins such as `read`, `glob`, `grep`, `edit`, `write`, `bash`, `web_fetch`, and `web_search` into `runtime-devtools`.
- [ ] 4.2 Move specialized coding-oriented agents such as `explore`, `plan`, and `verification` into `runtime-devtools` while preserving the same built-in discovery and replacement rules.
- [ ] 4.3 Update built-in discovery, visibility, and packaging tests to cover `runtime-core`, `runtime-default`, and `runtime-full` compositions after the devtools split.
- [ ] 4.4 Add migration notes and diagnostics for users who relied on the old default workspace-oriented tool pools now moving behind `runtime-full`.

## 5. Secondary First-Party Packages

- [ ] 5.1 Define the `runtime-compaction` package boundary and move compaction strategies or manager wiring behind the core compaction slot, prompt/private carriers, and context-window contracts.
- [ ] 5.2 Define the `runtime-isolation` package boundary and move environment-specific isolation adapters behind the core isolation mode, lease contracts, and execution assembly seams.
- [ ] 5.3 Define provider integration packages such as `runtime-openai` behind the core model/provider contracts so provider selection stays outside `runtime-core`.
- [ ] 5.4 Extract reference host implementations into `runtime-hosts-reference` while keeping host protocols and bound-host semantics in `runtime-core`.
- [ ] 5.5 Extract file-backed transcript, job, task-list, team, workflow, and teammate mailbox stores into `runtime-stores-file` while keeping store protocols and injection seams in `runtime-core`.
- [ ] 5.6 Group reusable first-party workflow skills such as `verify`, `debug`, `stuck`, `batch`, and `simplify` into `runtime-builtin-workflows`, while keeping memory-owned workflows such as `remember` in `runtime-memory`.
- [ ] 5.7 Execute the secondary package extraction in documented waves: mechanisms first, providers/adapters next, workflow/profile packaging last.

## 6. Cross-Package Docs, Diagnostics, and Validation

- [x] 6.1 Update runtime architecture, integration, extension, and hook documentation to present the converged v1 boundary story: `tool`, `agent`, `skill`, `host`, and approved hooks.
- [ ] 6.2 Update packaging and positioning docs to state that the project is a general AI runtime framework rather than a Claude Code parity effort.
- [x] 6.3 Document the first-party package layering diagram, supported distribution composition semantics, and canonical built-in ownership matrix for `runtime-core`, `runtime-default`, and `runtime-full`.
- [ ] 6.4 Add migration notes or structured diagnostics for users relying on moved built-ins, demoted hook phases, advanced-only hook handlers, or package relocation of first-party capabilities.
- [ ] 6.5 Run the affected regression suites for built-ins, hooks, memory, teammate orchestration, runtime assembly, and supported distribution packaging after the convergence changes land.
