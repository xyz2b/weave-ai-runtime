# WeaveRT OpenAI Responses Adapter

> Documentation note: This file remains the deep-dive reference for OpenAI integration details. Start with `docs/guides/integrate-openai.md`, then come back here when you need transport, schema, or failure-mode specifics.

This reference keeps the bundled OpenAI-adapter ledger: transport mapping, strict schema normalization, streaming edge cases, and structured failure modes.

Primary docs path:

- OpenAI integration guide -> `docs/guides/integrate-openai.md`
- Runtime integration path -> `docs/getting-started/quickstart.md`

Use this page when you already know how to connect an OpenAI route and now need request shaping, tool-schema round-trip, streaming fallback, or auth/schema failure semantics.

## 1. Stable surface

The stable public surface remains:

- package: `weavert-openai`
- provider binding: `openai-prod`
- default route: `openai_default`
- env vars:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`

If `OPENAI_API_KEY` is missing, the route does not disappear from runtime discovery; the first call returns a structured `auth_error`.

## 2. Transport model

The bundled adapter now sends requests through the OpenAI Responses API instead of the older minimal text-completion shim.

Current request-shaping rules:

- `system_prompt` maps to Responses `instructions`
- the runtime transcript maps to Responses `input` items
- historical assistant tool calls map to `function_call`
- local runtime tool results map to `function_call_output`
- the bundled `openai_default` route drives Responses `parallel_tool_calls` through route-level `provider_request_policy.parallel_tool_calls=true`

This means `openai_default` can participate directly in the runtime's shared tool loop instead of only returning text.

## 3. Runtime-owned continuation

Continuation authority still lives in the runtime, not in provider-managed thread state:

- the runtime can rebuild requests from its own transcript every time
- provider response ids are stored only as observability metadata
- correctness does not depend on `previous_response_id`
- tool replay still follows the shared `ToolUseBlock` / `ToolResultBlock` contract

This boundary is more stable for compaction, memory, permission, and recovery because authority never leaves the runtime.

## 4. Tool schema normalization rules

Responses function tools use strict schemas, so the bundled adapter explicitly normalizes runtime `ToolDefinition.input_schema`.

Current authoring recommendations:

- top-level schemas should declare `type: object`
- object properties are exported with `additionalProperties: false`
- optional fields are rewritten as required + nullable
  - for example, `note: {"type": "string"}` may originally stay out of `required`
  - after export, `required` includes `note` and the type becomes `{"type": ["string", "null"]}`
- this strict shape belongs only to provider transport; if the provider returns `null`, the adapter restores it to field omission before entering the runtime tool loop
- open object fields are exported as JSON-string surrogates; on the way back, the adapter decodes them into objects before runtime validation and execution
- array item schemas receive the same strict normalization recursively
  - the same round-trip restoration also covers nested object fields and object fields inside array items
- schema-valued `additionalProperties` is not supported yet; the adapter returns `tool_schema_error` before the call

If you want a tool to behave reliably on the default OpenAI route, prefer explicit fields and explicit array-item schemas over dynamic key maps.
In other words, the Responses strict function schema is transport shape, not the runtime's canonical tool-input contract.

## 5. Streaming behavior

`openai_default` supports both buffered completion and streaming.

Current streaming-mapping points:

- assistant text delta -> runtime `CONTENT_DELTA`
- function call start/delta/stop -> runtime `CONTENT_BLOCK_START` / `CONTENT_BLOCK_DELTA` / `CONTENT_BLOCK_STOP`
- final usage / request id / stop reason -> runtime terminal metadata
- provider-side error details -> runtime `ERROR` event metadata
- final function-call inputs go through the same round-trip restoration on both the done path and the completed-only path, so buffered and streaming modes receive the same canonical tool input
- if streaming has already finalized one or more `ToolUseBlock`s but a later `response.completed.output` is empty, the adapter falls back only in that contradictory case to the observed finalized tool blocks and corrects the terminal stop reason to `tool_use`
- this empty-completed-output fallback only fixes streaming `response.completed` compatibility; buffered completion, `response.incomplete`, and normal completed payloads with output items keep the existing parse path
- when the fallback triggers, terminal metadata may include the adapter-local diagnostic marker `stream_completed_output_fallback=finalized_stream_tool_blocks` for later gateway debugging

The default bundled route explicitly enables provider-side parallel tool calls, but the switch comes from route policy rather than an adapter constant.
If a custom OpenAI route does not provide `provider_request_policy.parallel_tool_calls`, the adapter conservatively falls back to `parallel_tool_calls=false`.
Real local concurrency and ordered continuation are still mainly decided by the runtime through `ToolTraits(read_only=True, concurrency_safe=True)`.

## 6. Structured failure modes

The current adapter tries to normalize common failures into runtime-consumable diagnostics:

- missing credential -> `auth_error`
- provider auth / permission failure -> `auth_error`
- context limit -> `context_limit`
- max output token limit -> `output_limit`
- rate limit / overload -> `provider_overload`
- strict tool schema export failure -> `tool_schema_error`
- other provider or transport problems -> `internal_error`

Terminal metadata tries to preserve these fields:

- `provider_name`
- `provider_response_id`
- `provider_error_code`
- `provider_error_type`
- `http_status`
- `retryable`
- `incomplete_reason`

## 7. Practical checklist

If you are wiring the runtime to a live OpenAI route, check these first:

1. run `await runtime.preflight_default_model_route()` once and inspect `ready`, `failure_class`, and `diagnostics` in the structured report
2. verify that `OPENAI_API_KEY` exists
3. confirm the tool `input_schema` is an explicit object schema
4. confirm you are not using schema-valued `additionalProperties`
5. confirm you are not expecting the provider to parallelize write tools on its own
6. confirm you are not treating the provider response id as runtime state authority

If those conditions hold, `openai_default` should be able to participate directly in the full query stack as the default bundled live adapter.

A minimal preflight example:

```python
import asyncio
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig.for_headless_live(Path.cwd()))
report = asyncio.run(runtime.preflight_default_model_route())
print(report.to_dict())
```

## 8. Live smoke script

The repository now also ships a real Responses live smoke:

```bash
python3 packages/toolchain/scripts/openai_responses_live_smoke.py
```

It runs once with the default full toolset:

- prompt: `Summarize this repository and use tools when needed.`
- route: `openai_default`
- transport: bundled Responses streaming path

The script output checks these signals most closely:

- whether the request really carries `parallel_tool_calls=true`
- whether the model emits multiple sibling `tool_use` calls in a single turn
- whether the runtime continues those tool calls into later `function_call_output` continuation
- whether the adapter-local fallback triggers if some gateway still returns an empty `response.completed.output`

The script runs the runtime-owned preflight first. If preflight fails, it prints the structured `preflight` report and exits directly.
If the script returns `ok: true`, that usually means the default bundled live OpenAI path works in the current environment. If it fails, the `checks`, `attempts`, and `requests` fields in the output help determine whether the problem is credentials, gateway compatibility, or runtime continuation.
