# 集成 OpenAI

## 适合谁？

已经拥有离线或确定性 WeaveRT 工作流、现在想走内置 live route 的用户。

## 前置条件

- 一个可运行的 runtime baseline
- 环境中已安装 `packages/framework-packs/integrations/openai`
- 可用的 `OPENAI_API_KEY`

推荐安装路径：

```bash
python -m pip install -e packages/framework-packs/integrations/openai
```

## 推荐的 live posture

先用 live preset，不要自己拼接 route 状态。
常用入口是：

- `RuntimeConfig.for_headless_live(project_root)`

这样会让 route 选择保持显式，并把 `preflight_default_model_route()` 变成第一步诊断。

## 步骤

1. 导出凭据：

```bash
export OPENAI_API_KEY=your-key
export OPENAI_MODEL=gpt-4.1-mini
```

2. 用 live preset 组装 runtime：

```python
import asyncio
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig.for_headless_live(Path.cwd()))
preflight = asyncio.run(runtime.preflight_default_model_route())
print(preflight.to_dict())
```

3. 只有在 preflight 就绪后，再运行真实 prompts。

## 内置 OpenAI 路线会帮你做什么

这条内置 route 不只是纯文本适配器。
它支持：

- live provider-backed prompts
- 通过 strict function tools 的 tool-capable execution
- `auth_error`、`context_limit`、`output_limit`、`tool_schema_error` 等结构化失败类型
- runtime 拥有 continuation，而不是 provider 拥有状态权威

## 需要记住的 tool schema 规则

如果 tool 会通过内置 OpenAI route 运行，优先遵守：

- 显式 object schema
- 显式 array item schema
- 尽量使用小且闭合的结构

不要依赖 schema-valued `additionalProperties`。

## 预期结果

- preflight 报告 `ready: true`
- runtime 会显式暴露 route failures，而不是静默 fallback
- tool-capable live execution 走的是内置 OpenAI 路线

## 务实的验证路径

接下来可以运行：

- `python3 -B -m examples.projects.coding_workflow_demo --live`
- `python3 packages/toolchain/scripts/openai_responses_live_smoke.py`

## 常见失败解释

- 缺少 `OPENAI_API_KEY` -> preflight 或首次运行会报 `missing_env` 或 `auth_error`
- tool schema 过于动态 -> `tool_schema_error`
- provider 过载或速率限制 -> 结构化的 provider overload diagnostics

## 下一步

- preflight 成功后，运行 `python3 -B -m examples.projects.coding_workflow_demo --live`
- 如果你想要更明确的 route diagnostics 与失败解释清单，继续看 `testing-and-observability.md`

## 另见

- `../deep-dives/weavert-openai-responses-adapter.md`
- `../../../examples/README.zh-CN.md`
- `../reference/runtime-config.md`
