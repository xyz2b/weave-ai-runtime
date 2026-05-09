# 快速开始

这是新 WeaveRT 用户的默认首轮运行路径。
先使用 starter，再回到 `examples/` 进行验证路径和更深入的评估。

## 适合谁？

- 想走第一条可运行 WeaveRT 项目路径，而不是先看深度架构导览的框架使用者。

## 前置条件

- 先完成 `installation.md`
- 如果你还没看过落地页概览，可先快速浏览 `../introduction/what-is-weavert.md`

## 目标

生成一个最小项目，运行一次，并在加入自定义逻辑之前先确认 runtime baseline 正常。

## 为什么这条路径应该放在最前面

WeaveRT 推荐 starter-first 的旅程：

1. 用 canonical `weavert` imports 生成一个小项目
2. 确认 `.weavert/` 发现机制和一个 runtime turn 可以本地运行
3. 一次只扩展一个 seam
4. 之后再进入 examples、live routes、host binding 或 scenario packs

`examples/` 是仓库的验证路径。
它适合在 starter 成功之后使用，但不是默认的 copy-paste 采纳路径。

## 第 1 步：安装本地工具链

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
```

可选的 first-party packages 以后再按需安装。
例如 live OpenAI 集成位于 `packages/framework-packs/integrations/openai`。

## 第 2 步：生成 starter 项目

```bash
weavert-starter generate minimal-project ./my-weavert-app
```

生成后的项目会给你：

- `RuntimeConfig.for_ordinary_workflow(...)` 作为基础 preset
- 项目本地 `.weavert/agents/` 和 `.weavert/tools/`
- 一个确定性的 `ScriptedModelClient` baseline
- 一个可随着项目增长仍保持精简的 `app.py` 入口

## 第 3 步：查看生成后的结构

```text
my-weavert-app/
|- app.py
|- pyproject.toml
|- README.md
`- .weavert/
   |- agents/
   |- tools/
   `- skills/
```

Starter 是故意保持很小的。
你的第一个项目应该通过在 `.weavert/` 下逐步添加一个 tool、agent 或 skill 来生长，而不是重写 runtime loop。

## 第 4 步：运行生成的项目

```bash
cd my-weavert-app
python -m pip install -e .
python app.py
```

## 预期输出

请关注这些锚点：

- `preset: ordinary-workflow`
- `workspace root: .weavert`
- `assistant: The scaffold is ready...`
- `status: ok`

## 这证明了什么

- runtime 已通过 `RuntimeConfig.for_ordinary_workflow(...)` 成功组装
- 项目本地 `.weavert/` 发现机制处于激活状态
- 一个文件型 tool 和 agent 能参与一次 runtime turn
- 确定性测试路径在没有 live model 凭据时也能工作

## 接下来最常碰到的四个稳定表面

Starter 跑通后，大多数用户会基于这四个表面继续扩展：

- `RuntimeConfig`
  - assembly 选择，如 discovery sources、model routes、packages 和 stores
- `RuntimeAssembly`
  - 运行时入口，如 prompt helpers、sessions 和 inspection
- `DefinitionSourcePaths`
  - tools、agents 和 skills 的发现方式
- `BoundHostRuntime`
  - 只有在需要 host 拥有生命周期、审批或 UI 集成时才用

## 下一步

1. 在 `.weavert/tools/` 下添加自己的 tool
2. 在 `.weavert/agents/` 或 `.weavert/skills/` 下添加 agent 或 skill
3. 阅读 `../guides/build-your-first-project.md`
4. 用 `../../../examples/README.zh-CN.md` 验证你修改的具体 seam
5. 只有当离线 baseline 稳定后，再进入 `../guides/integrate-openai.md`

## 另见

- `installation.md`
- `starter-scaffolds.md`
- `../concepts/runtime-model.md`
- `../../../examples/README.zh-CN.md`
