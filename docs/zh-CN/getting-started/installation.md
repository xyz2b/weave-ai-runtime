# 安装

这篇指南覆盖本地仓库副本的安装路径。
这是理解仓库最稳妥的方式，因为 examples 和 starter scaffolds 都可以直接发现同级 package。

## 适合谁？

- 第一次在本地检出这个仓库并准备环境的开发者。

## 前置条件

- Python 3.11+
- 此仓库的本地副本
- 能创建并激活虚拟环境的 shell

## 基础安装

创建虚拟环境，并安装 runtime core 与 starter toolchain：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
```

## 可选 first-party packages

只有在需要时再安装其他包：

- OpenAI 集成：`packages/framework-packs/integrations/openai`
- reference hosts：`packages/framework-packs/integrations/hosts-reference`
- file stores：`packages/framework-packs/integrations/stores-file`
- product kits：`packages/product-kits/*`

示例：

```bash
python -m pip install -e packages/framework-packs/integrations/openai
python -m pip install -e packages/product-kits/coding
```

## 验证工具链

```bash
weavert-starter list
```

你应能看到官方 scaffold 目录，包括 `minimal-project`、`headless-workflow` 和 `live-smoke`。

下一步阅读：

- `quickstart.md`
- `starter-scaffolds.md`
- `../reference/runtime-config.md`

## 下一步

- 运行 `quickstart.md`，验证本地安装能否端到端跑通
- 如果你想生成一个项目，而不是直接在仓库内阅读，请继续看 `starter-scaffolds.md`

## 另见

- `quickstart.md`
- `starter-scaffolds.md`
- `../guides/build-your-first-project.md`
- `../../../examples/README.zh-CN.md`
