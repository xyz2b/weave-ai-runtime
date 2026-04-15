## 1. Stream Contract

- [ ] 1.1 Extend `ModelRequest` and `ModelStreamEvent` to carry abort handles, block-level stream data, and terminal metadata
- [ ] 1.2 Define a host-facing turn event model that can carry request-start, stream-progress, finalized message, and terminal events

## 2. Turn Engine Streaming

- [ ] 2.1 Implement `run_turn_stream()` as the primary async generator for turn execution
- [ ] 2.2 Keep `run_turn()` as a compatibility wrapper that aggregates the streamed events into a turn result

## 3. Abort And Partial Output Handling

- [ ] 3.1 Propagate session interrupt signals into in-flight model requests so slow streams terminate promptly
- [ ] 3.2 Add discard or tombstone handling for incomplete streamed blocks so partial output does not pollute continuation history

## 4. Terminal Metadata And Smoke Coverage

- [ ] 4.1 Surface stop reason, usage, request identifiers, and TTFT-style metadata from the model adapter through the turn result contract
- [ ] 4.2 Update fake model fixtures and focused stream tests to validate abort behavior and terminal metadata emission
