## 1. Block Message Model

- [ ] 1.1 Define provider-agnostic content block models for `text`, `tool_use`, `tool_result`, and reserved thinking blocks
- [ ] 1.2 Update `RuntimeMessage` and related contracts to support structured API-bound content instead of flat strings

## 2. Transcript Persistence

- [ ] 2.1 Upgrade transcript serialization and deserialization to store structured blocks without information loss
- [ ] 2.2 Add legacy transcript read compatibility that preserves flat text content without fabricating tool/result structure

## 3. Normalization And Pairing Repair

- [ ] 3.1 Implement a message normalization module that merges adjacent compatible messages and normalizes tool payloads before provider invocation
- [ ] 3.2 Implement `tool_use` / `tool_result` pairing repair for continuation and transcript-resume paths

## 4. Turn Continuation Integration

- [ ] 4.1 Refactor turn execution to append assistant `tool_use` messages and user `tool_result` messages using the new block protocol
- [ ] 4.2 Remove the current JSON-string tool result continuation path from the API-bound turn loop

## 5. Protocol Smoke Coverage

- [ ] 5.1 Add focused unit coverage for block transcript round-tripping and pairing repair
- [ ] 5.2 Add a regression check that the second provider request contains structured `tool_result` content instead of flattened JSON
