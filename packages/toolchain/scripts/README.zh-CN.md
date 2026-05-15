# Toolchain Scripts

这个 package root 拥有仓库支持脚本。它是仓库拥有的维护者 utility root，不是公开 PyPI 发布目标。

## 这个 package 拥有什么

- 供维护者与验证工作流使用的仓库支持脚本
- 不应表现为 runtime-selected packages 的开发者侧 utilities
- 即使保留 package-local metadata，也继续保持为仓库绑定的维护者工具

## 发布边界

- 本地安装名：`weavert-toolchain-scripts`
- 公开 PyPI 范围：不属于公开发布列车
- runtime activation：无

## 规范脚本与模块表面

- `packages/toolchain/scripts/check_workspace_layout.py`
- `packages/toolchain/scripts/openai_responses_live_smoke.py`
- `python -m check_workspace_layout`
- `python -m openai_responses_live_smoke`

## 约定使用路径

从仓库 checkout 直接运行：

```bash
python3 packages/toolchain/scripts/check_workspace_layout.py
OPENAI_API_KEY=... python3 packages/toolchain/scripts/openai_responses_live_smoke.py
```

从当前仓库 checkout 做本地 maintainer install：

```bash
python -m pip install -e packages/framework-core \
  -e packages/framework-packs/integrations/openai \
  -e packages/toolchain/scripts
python -m check_workspace_layout
python -c "import check_workspace_layout, openai_responses_live_smoke"
```

只有在你要通过本地安装路径执行 live OpenAI 验证时，才运行 `OPENAI_API_KEY=... python -m openai_responses_live_smoke`。

## 另见

- `../README.zh-CN.md`
- `../../../docs/zh-CN/maintainers/repository-layout.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/zh-CN/guides/integrate-openai.md`
