# 工作区布局

一个典型的 WeaveRT 项目会把本地 runtime 定义放在 `.weavert/` 下。

```text
your-project/
|- app.py
|- pyproject.toml
`- .weavert/
   |- agents/
   |- tools/
   `- skills/
```

## 适合谁？

- 已理解整体工作流、现在需要稳定查询页的读者。

## 前置条件

- 先读对应的 guide 或 concept 页面
- 把这页当成 reference sheet，而不是第一站教程

## 常见 discovery roots

Ordinary workflow presets 通常包含：

- user scope：`~/.weavert`
- project scope：`<project>/.weavert`

## 文件型 discovery 规则

- tools：`tools/*.py`
- agents：`agents/*.md`
- skills：`skills/**/SKILL.md`

## Source precedence 提醒

实际优先级并不是 “project 覆盖一切”。
在实践中，如果同名，bundled surfaces 仍会压过 user 与 project-local definitions。
当你需要真正覆盖时，优先用新名字，或者在 Python assembly 代码里显式替换 bundled built-ins。

## 本仓库中的仓库级目录

- `docs/`
- `examples/`
- `packages/`
- `tests/`

关于本仓库的维护者布局规则，见 `../maintainers/repository-layout.md`。

## 下一步

- 回到 `../guides/build-your-first-project.md`，把这套布局应用到真实项目里
- 布局就位后，继续通过 `../guides/add-a-tool.md`、`../guides/add-an-agent.md` 或 `../guides/add-a-skill.md` 增加能力
- 只有当问题是关于本仓库本身，而不是用户项目时，才看 `../maintainers/repository-layout.md`

## 另见

- `../getting-started/starter-scaffolds.md`
- `../guides/build-your-first-project.md`
- `../maintainers/repository-layout.md`
