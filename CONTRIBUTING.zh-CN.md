# 参与 WeaveRT 贡献

[English](CONTRIBUTING.md) | 简体中文

感谢贡献。
这个仓库按运行时框架工作区组织，因此小而聚焦的改动更容易审查，也更安全地验证。

## 开始之前

- 先读 `README.zh-CN.md`，理解项目定位
- 再读 `docs/zh-CN/README.md`，理解文档阅读路径
- 用 `examples/README.zh-CN.md` 了解验证路径
- 参与前阅读 `CODE_OF_CONDUCT.zh-CN.md`

## 本地环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
python -m pip install -e .[dev]
```

只有在改动需要时再安装其他包族。

## 开发工作流

- 优先提交聚焦改动，避免无关的大范围重构
- 保持 runtime、docs、examples 和 tests 一致
- 当公开行为或推荐路径变化时，同步更新文档
- 继续保持 landing page、终端用户文档与维护者说明三者分离

## 文档约定

- `README.md` / `README.zh-CN.md` 是 landing page，不是完整手册
- `docs/README.md` / `docs/zh-CN/README.md` 是文档首页
- guide 应回答：适合谁、前置条件、步骤、预期结果、下一步
- examples 是验证路径，不是默认入门路径
- 新的公开文档优先使用英文文件名和稳定、可预测的标题

## 验证

先运行最小相关验证。
常用入口包括：

```bash
pytest tests/test_runtime_extension_demos.py
python3 -B -m examples.tools.file_backed_tool_demo
python3 -B -m examples.projects.coding_workflow_demo
```

如果你的改动影响某个特定 example，也应直接运行该 example。

## Pull Request

PR 描述中请包含：

- 改了什么
- 为什么改
- 如何验证
- 哪些后续工作仍然明确留在范围外

## 安全问题

若是漏洞或敏感报告，请先遵循 `SECURITY.zh-CN.md`，不要直接公开提 issue。
