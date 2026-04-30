# Bundled OpenAI Responses Adapter

本文档说明内置 `weavert-openai` / `openai_default` route 的当前行为。
它现在不再是 text-only baseline，而是 runtime 默认随附的 live OpenAI adapter。

## 1. Stable surface

公开入口保持不变：

- package: `weavert-openai`
- provider binding: `openai-prod`
- default route: `openai_default`
- env vars:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`

如果没有配置 `OPENAI_API_KEY`，route 不会从 runtime discovery 里消失；首次调用时会返回结构化 `auth_error`。

## 2. Transport model

内置 adapter 现在通过 OpenAI Responses API 发请求，而不是旧的最小 text completion shim。

当前 request shaping 规则：

- `system_prompt` 映射到 Responses `instructions`
- runtime transcript 映射到 Responses `input` items
- assistant 历史 tool call 映射到 `function_call`
- runtime 本地 tool result 映射到 `function_call_output`
- route 默认设置 `parallel_tool_calls=false`

这意味着 `openai_default` 可以直接参与 runtime 的 shared tool loop，而不是只返回一段文本。

## 3. Runtime-owned continuation

当前 continuation authority 仍然在 runtime，而不是 provider-managed thread state：

- runtime 每次都可从自己的 transcript 重建请求
- provider response id 只作为 observability metadata 记录
- correctness 不依赖 `previous_response_id`
- tool replay 继续走 shared `ToolUseBlock` / `ToolResultBlock` contract

这条边界对 compaction、memory、permission、recovery 都更稳定，因为 authority 没有离开 runtime。

## 4. Tool schema normalization rules

Responses function tools 使用 strict schema；因此 bundled adapter 会对 runtime `ToolDefinition.input_schema` 做显式归一化。

当前 authoring 约束建议：

- top-level schema 应声明为 `type: object`
- object property 会被导出为 `additionalProperties: false`
- optional field 会被改写成“required + nullable”
  - 例如原来未列入 `required` 的 `note: {"type": "string"}`
  - 导出后会变成 `required` 中包含 `note`，并把类型改成 `{"type": ["string", "null"]}`
- array item schema 也会递归做同样的 strict normalization
- schema-valued `additionalProperties` 当前不支持；adapter 会在调用前返回 `tool_schema_error`

如果你想让 tool 在默认 OpenAI route 上稳定工作，最好优先写显式字段、显式数组 item schema，而不是依赖动态 key map。

## 5. Streaming behavior

`openai_default` 同时支持 buffered completion 和 streaming。

当前 streaming 映射要点：

- assistant text delta -> runtime `CONTENT_DELTA`
- function call start/delta/stop -> runtime `CONTENT_BLOCK_START` / `CONTENT_BLOCK_DELTA` / `CONTENT_BLOCK_STOP`
- final usage / request id / stop reason -> runtime terminal metadata
- provider-side error details -> runtime `ERROR` event metadata

默认 route 还会保守地关闭 provider-side parallel tool calls。
原因不是 runtime 不支持并发，而是 coding workflow 更看重 deterministic ordered continuation。
真正的并发仍主要由 runtime 自己根据 `ToolTraits(read_only=True, concurrency_safe=True)` 决定。

## 6. Structured failure modes

当前 adapter 会尽量把常见失败归一化成 runtime 可消费的诊断：

- missing credential -> `auth_error`
- provider auth / permission failure -> `auth_error`
- context limit -> `context_limit`
- max output token limit -> `output_limit`
- rate limit / overload -> `provider_overload`
- strict tool schema export failure -> `tool_schema_error`
- 其他 provider / transport 问题 -> `internal_error`

终端 metadata 会尽量保留这些字段：

- `provider_name`
- `provider_response_id`
- `provider_error_code`
- `provider_error_type`
- `http_status`
- `retryable`
- `incomplete_reason`

## 7. Practical checklist

如果你要把 runtime 接到 live OpenAI route，优先检查：

1. `OPENAI_API_KEY` 是否存在
2. tool `input_schema` 是否是显式 object schema
3. 是否误用了 schema-valued `additionalProperties`
4. 是否期望 provider 自己并行执行写工具
5. 是否把 provider response id 误当成 runtime state authority

如果这些条件都满足，`openai_default` 就应当能作为默认 bundled live adapter 直接参与完整 query stack。
