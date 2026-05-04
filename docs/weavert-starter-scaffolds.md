# WeaveRT Official Starter Scaffolds

如果你的目标是“新建一个自己的 WeaveRT 项目”，先从这里开始，而不是先拷 demo internals。

这些 starter scaffold 的定位是：

- 给出一个官方、最小、可运行的起点
- 直接使用 canonical `weavert` public imports
- 直接采用 canonical `.weavert/` workspace layout
- 把 demo 留给 validation / comparison，而不是当作 primary copy-paste path

## One official generation path

安装了 `weavert` 之后，使用同一条官方命令生成 starter：

```bash
weavert-starter list
weavert-starter generate minimal-project ./my-weavert-app
weavert-starter generate headless-workflow ./my-headless-runner
weavert-starter generate live-smoke ./my-live-smoke
```

如果目标目录已存在且非空，显式加 `--force`：

```bash
weavert-starter generate minimal-project ./my-weavert-app --force
```

## Official catalog

### `minimal-project`

适合：

- 第一次启动一个普通 WeaveRT 项目
- 想先看 project-local agent/tool discovery 的最小闭环
- 想要一个不依赖 provider credential 的 deterministic baseline

生成结果重点：

- `RuntimeConfig.for_ordinary_workflow(...)`
- `.weavert/agents/` + `.weavert/tools/`
- `weavert.testing.ScriptedModelClient`
- 一个很小的 `app.py` entrypoint

### `headless-workflow`

适合：

- CI / smoke / scripted workflow
- 想围绕 canonical workflow report 做后处理
- 不想自己写 session lifecycle glue

生成结果重点：

- `RuntimeConfig.for_ordinary_workflow(...)`
- `run_workflow_test(...)`
- `final_assistant_text(...)`
- `latest_tool_outcome(...)`
- `terminal_failure(...)`

### `live-smoke`

适合：

- provider-backed live readiness check
- 在进入更重的 host integration 之前先确认 live route
- 希望 credential / route failure 先通过 preflight 暴露出来

生成结果重点：

- `RuntimeConfig.for_headless_live(...)`
- `preflight_default_model_route()`
- 不内置 scripted fallback
- 缺 credential 时直接返回结构化 preflight report

## How to use the generated projects

每个 scaffold 都会生成：

- `README.md`
- `pyproject.toml`
- canonical `.weavert/` workspace root
- 一个对应 shape 的 runnable entrypoint

推荐顺序：

1. 先直接跑生成出来的 entrypoint，确认 baseline 成立
2. 再把你自己的 agent / tool / skill 放到 `.weavert/`
3. 最后再决定是否进入更高级的 host-bound integration

## Relationship to demos

starter scaffold 和 `demos/README.md` 的职责不同：

- starter scaffold = adoption path
- demos = validation story

建议这样理解：

- 想新建项目：先用 starter scaffold
- 想验证 framework seam：跑 demos
- 想验证同一个 workflow 的 offline/live layering：继续用 demos
- 想看 host binding、builtin replacement、durable state：看 advanced app demos
