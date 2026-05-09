# 构建你的第一个项目

## 适合谁？

想开始自己的第一个真实 WeaveRT 项目，而不只是跑一个 demo 的框架使用者。

## 前置条件

- Python 3.11+
- 已完成 `../getting-started/installation.md` 的本地安装
- 已成功跑通 `../getting-started/quickstart.md`

## 推荐基线

除非你已经明确知道自己需要 headless workflow runner 或 live-only smoke 路径，否则都从 `minimal-project` 开始。

```bash
weavert-starter generate minimal-project ./my-weavert-app
cd my-weavert-app
python -m pip install -e .
python app.py
```

## 一个好的首个项目结构

```text
my-weavert-app/
|- app.py
|- pyproject.toml
`- .weavert/
   |- tools/
   |- agents/
   `- skills/
```

## 步骤

1. 保持 `app.py` 精简，并通过 `RuntimeConfig.for_ordinary_workflow(...)` 组装
2. 在 `.weavert/` 下添加一个项目本地能力
3. 如果你要增加执行逻辑，优先用 tool
4. 只有在需要具名角色时，才加 agent
5. 只有在需要可复用工作流步骤时，才加 skill
6. 去 `../../../examples/README.zh-CN.md` 验证你修改的具体 seam

## 预期结果

你会得到一个可运行项目，它：

- 通过稳定运行时表面完成组装
- 能从 `.weavert/` 发现项目本地定义
- 以一次一个 tool、agent 或 skill 的方式生长
- 不需要你重写 runtime loop

## 一个务实的成长路径

- 第一阶段：一个本地 tool + 一个本地 agent
- 第二阶段：一个可复用 skill
- 第三阶段：通过 `examples/README.zh-CN.md` 做确定性验证
- 后续阶段：当需求足够明确时，再加入 live routing、package composition 或 host binding

## 下一步

- 添加工具：`add-a-tool.md`
- 添加智能体：`add-an-agent.md`
- 添加技能：`add-a-skill.md`
- 进入 live routing：`integrate-openai.md`

## 另见

- `../getting-started/starter-scaffolds.md`
- `../concepts/runtime-model.md`
- `../concepts/tools-agents-skills.md`
