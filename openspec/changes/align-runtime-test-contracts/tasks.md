## 1. Align terminal metadata regressions

- [ ] 1.1 Update the shared turn/runtime protocol fixtures to preserve additive terminal metadata while still asserting the required stable fields.
- [ ] 1.2 Refresh the failing `agent` tool and assembled-runtime tests so child `terminal_metadata` expectations stay aligned with the structured child run record.

## 2. Align compaction contract coverage

- [ ] 2.1 Update session-memory compaction coverage so `last_compaction_at` is asserted only for material compaction effects, and add a negative path for transcript rewrites without compaction metadata.
- [ ] 2.2 Replace `collect()`-only compaction test doubles in request-assembly coverage with `prepare_turn()`-capable stubs that exercise the real turn-preparation path.

## 3. Re-verify the runtime suite

- [ ] 3.1 Run the five currently failing pytest cases and resolve any remaining contract mismatches.
- [ ] 3.2 Run the full pytest suite to confirm the updated regressions pass under the current runtime contract.

## 4. Protect implementation boundaries

- [ ] 4.1 Keep the change scoped to `tests/` and test-only fixtures/helpers; do not modify runtime/application code under `src/`.
