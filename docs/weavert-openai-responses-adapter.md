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
- bundled `openai_default` 会通过 route-level `provider_request_policy.parallel_tool_calls=true` 驱动 Responses `parallel_tool_calls`

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
- 这个 strict shape 只属于 provider transport；provider 如果回传 `null`，adapter 会在进入 runtime tool loop 前把它恢复成“字段省略”
- open object field 会被导出成 JSON-string surrogate；provider 回传后 adapter 会在进入 runtime 校验和执行前解码回 object
- array item schema 也会递归做同样的 strict normalization
  - 同样的 round-trip restoration 也会覆盖嵌套 object field 和 array item 里的 object field
- schema-valued `additionalProperties` 当前不支持；adapter 会在调用前返回 `tool_schema_error`

如果你想让 tool 在默认 OpenAI route 上稳定工作，最好优先写显式字段、显式数组 item schema，而不是依赖动态 key map。
换句话说，Responses strict function schema 是 transport shape，不是 runtime canonical tool-input contract。

## 5. Streaming behavior

`openai_default` 同时支持 buffered completion 和 streaming。

当前 streaming 映射要点：

- assistant text delta -> runtime `CONTENT_DELTA`
- function call start/delta/stop -> runtime `CONTENT_BLOCK_START` / `CONTENT_BLOCK_DELTA` / `CONTENT_BLOCK_STOP`
- final usage / request id / stop reason -> runtime terminal metadata
- provider-side error details -> runtime `ERROR` event metadata
- function call 最终输入会在 done/completed-only 两条路径上走同一套 round-trip restoration，因此 buffered 与 streaming 会收到相同的 canonical tool input
- 如果 streaming 已经 finalize 出一个或多个 `ToolUseBlock`，但随后的 `response.completed.output` 却是空数组，adapter 会仅在这个矛盾场景下回退到已观测到的 finalized tool blocks，并把 terminal stop reason 校正为 `tool_use`
- 这个 empty-completed-output fallback 只作用于 streaming `response.completed` 的兼容性修正；buffered completion、`response.incomplete` 和正常带有 output items 的 completed payload 仍保持现有解析路径不变
- fallback 触发时，terminal metadata 可能额外带上 adapter-local 诊断标记 `stream_completed_output_fallback=finalized_stream_tool_blocks`，方便后续排查网关兼容性问题

默认 bundled route 会显式开启 provider-side parallel tool calls，但这个开关来自 route policy，而不是 adapter 内部常量。
如果某个自定义 OpenAI route 没有提供 `provider_request_policy.parallel_tool_calls`，adapter 会保守回落到 `parallel_tool_calls=false`。
真正的本地并发和 ordered continuation 仍主要由 runtime 自己根据 `ToolTraits(read_only=True, concurrency_safe=True)` 决定。

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

1. 先跑一次 `await runtime.preflight_default_model_route()`，看结构化 report 里的 `ready`、`failure_class`、`diagnostics`
2. `OPENAI_API_KEY` 是否存在
3. tool `input_schema` 是否是显式 object schema
4. 是否误用了 schema-valued `additionalProperties`
5. 是否期望 provider 自己并行执行写工具
6. 是否把 provider response id 误当成 runtime state authority

如果这些条件都满足，`openai_default` 就应当能作为默认 bundled live adapter 直接参与完整 query stack。

一个最小 preflight 例子：

```python
import asyncio
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig.for_headless_live(Path.cwd()))
report = asyncio.run(runtime.preflight_default_model_route())
print(report.to_dict())
```

## 8. Live smoke script

仓库现在还附带了一个真实 Responses live smoke：

```bash
python3 scripts/openai_responses_live_smoke.py
```

它会直接用默认完整工具集跑一次：

- prompt: `Summarize this repository and use tools when needed.`
- route: `openai_default`
- transport: bundled Responses streaming path

脚本输出会重点检查这些信号：

- 请求是否真的带了 `parallel_tool_calls=true`
- 模型是否在单轮里产出了多个 sibling `tool_use`
- runtime 是否把这些 tool call 继续承接成后续 `function_call_output` continuation
- 如果某个网关仍然返回空的 `response.completed.output`，adapter-local fallback 是否命中

脚本现在会先跑 runtime-owned preflight；如果 preflight 没过，会直接打印结构化 `preflight` report 并退出。
如果脚本返回 `ok: true`，通常就说明默认 bundled live OpenAI path 在当前环境里是通的；如果失败，输出里的 `checks`、`attempts` 和 `requests` 字段会帮助定位是凭证、网关兼容性还是 runtime continuation 问题。
