## 1. Extension Event Contract

- [ ] 1.1 Add the generic extension-event host-bridge contract and structured event envelope for package-owned host egress.
- [ ] 1.2 Migrate team event emitters to the generic extension-event contract without changing their logical event semantics.

## 2. Canonical Team Discovery Migration

- [ ] 2.1 Update runtime-owned team paths to resolve team control, message, and workflow behavior only through canonical capability keys and host facets.
- [ ] 2.2 Remove runtime-owned dependence on `RuntimeServices.team_*` and `RuntimeAssembly.team_*` projections.

## 3. Host-Surface Cleanup

- [ ] 3.1 Publish deprecation metadata and a one-to-one replacement matrix, including team-present and team-absent semantics, for `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, `BoundHostRuntime` workflow helpers, and `HostRuntime.emit_team_event()`.
- [ ] 3.2 Remove `BoundHostRuntime` workflow helper wrappers and the team-specific host-bridge method after the generic extension-event and host-facet paths are live.

## 4. Lifecycle and Regression Hardening

- [ ] 4.1 Verify that team recovery and session-open replay remain lifecycle-participant-owned with no controller or kernel special cases.
- [ ] 4.2 Add conformance and regression coverage across team-present and team-absent distributions, and publish structured findings using the shared protocol-only finding schema to prove that team runtime behavior remains available without package-specific owner-layer bridges.

## 5. Documentation and Migration Notes

- [ ] 5.1 Update architecture, migration, and host-integration docs with the protocol-only team path and breaking API replacements.
