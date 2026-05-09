# WeaveRT OpenAI Responses 适配器

> 文档说明：这是 OpenAI 集成细节的 deep-dive 参考。普通路径请先读 `docs/zh-CN/guides/integrate-openai.md`。精确字段名与 failure code 保持英文写法。

## 对应主文档

- OpenAI integration guide -> `docs/zh-CN/guides/integrate-openai.md`
- Runtime integration path -> `docs/zh-CN/getting-started/quickstart.md`

## 1. 稳定表面

- package：`weavert-openai`
- provider binding：`openai-prod`
- default route：`openai_default`
- 环境变量：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`

## 2. Transport 模型

- `system_prompt` 会映射到 Responses `instructions`
- runtime transcript 会映射到 Responses `input` items
- 历史 assistant tool calls 会映射到 `function_call`
- 本地 runtime tool results 会映射到 `function_call_output`
- 内置 `openai_default` route 会通过 `provider_request_policy.parallel_tool_calls=true` 驱动 Responses `parallel_tool_calls`

## 3. Runtime-owned continuation

- runtime 可以每次都从自己的 transcript 重建请求
- provider response ids 只作为 observability metadata 存储
- 正确性不依赖 `previous_response_id`
- tool replay 仍遵循共享的 `ToolUseBlock` / `ToolResultBlock` 契约

## 4. Tool schema 规范化规则

- 顶层 schema 应声明 `type: object`
- object properties 导出时会变成 `additionalProperties: false`
- optional fields 会被重写为 required + nullable
- 这种 strict shape 只属于 provider transport；返回后 adapter 会恢复为 runtime 需要的输入形态
- open object fields 会以 JSON-string surrogate 导出，回程时再解码回 objects
- array item schemas 也会递归应用同样的 strict normalization
- schema-valued `additionalProperties` 目前不支持，会直接返回 `tool_schema_error`

## 5. Streaming 行为

- assistant text delta -> runtime `CONTENT_DELTA`
- function call start/delta/stop -> runtime `CONTENT_BLOCK_START` / `CONTENT_BLOCK_DELTA` / `CONTENT_BLOCK_STOP`
- final usage / request id / stop reason -> runtime terminal metadata
- provider-side error details -> runtime `ERROR` event metadata

还要记住两点：

- 最终 function-call inputs 在 buffered 与 streaming 模式下都会走同一套 round-trip restoration
- 当 streaming 已经 finalize 了一个或多个 `ToolUseBlock`，但后续 `response.completed.output` 为空时，adapter 会在这种矛盾情况下降级为使用已 finalize 的 tool blocks，并把 stop reason 修正为 `tool_use`

## 6. 结构化 failure modes

- 缺少凭据 -> `auth_error`
- provider auth / permission failure -> `auth_error`
- context limit -> `context_limit`
- max output token limit -> `output_limit`
- rate limit / overload -> `provider_overload`
- strict tool schema export failure -> `tool_schema_error`
- 其他 provider 或 transport 问题 -> `internal_error`

常见 metadata 字段：

- `provider_name`
- `provider_response_id`
- `provider_error_code`
- `provider_error_type`
- `http_status`
- `retryable`
- `incomplete_reason`

## 7. 实用检查表

1. 先确认 `OPENAI_API_KEY` 已设置
2. 先运行 preflight，再发真实 prompts
3. 确保 tools 使用显式、闭合的 schema
4. 如果走 streaming，注意是否出现 adapter fallback 标记

## 8. Live smoke script

官方 live smoke 的目标是验证：

- prompt：`Summarize this repository and use tools when needed.`
- route：`openai_default`
- transport：内置 Responses streaming path
- 请求是否真的带上 `parallel_tool_calls=true`
- 模型是否会在一个 turn 里发出多个 sibling `tool_use` calls
- runtime 是否会把这些 tool calls 继续接成后续 `function_call_output`
- 某些 gateway 若仍返回空的 `response.completed.output`，adapter fallback 是否会触发
