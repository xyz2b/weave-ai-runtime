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

创建虚拟环境，并用一条命令安装完整 ordinary-workflow baseline、starter 与 testing：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  -e packages/framework-core \
  -e packages/framework-packs/capabilities/memory \
  -e packages/framework-packs/capabilities/team \
  -e packages/framework-packs/mechanisms/compaction \
  -e packages/framework-packs/mechanisms/isolation \
  -e packages/framework-packs/integrations/openai \
  -e packages/framework-packs/integrations/hosts-reference \
  -e packages/framework-packs/integrations/stores-file \
  -e packages/framework-packs/workflows/builtin-workflows \
  -e packages/framework-packs/workflows/planning \
  -e packages/framework-packs/workflows/devtools \
  -e packages/distributions/full \
  -e packages/toolchain/starter \
  -e packages/toolchain/testing
```

如果你不是从本地 editable roots 安装，而是直接从已发布包安装，对应的一条命令基线是：

```bash
python -m pip install weavert-starter weavert-testing
```

`weavert-starter` 现在依赖 `weavert-full`，所以公开 starter 路径会自动拉起文档里的 ordinary-workflow runtime baseline。

如果你需要判断该选 `weavert`、`weavert-full`、scenario kits 还是 shared kits，请继续看：

- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`

## 可选 first-party packages

只有在需要时再安装额外的 scenario 或 product-kit packages：

- product kits：`packages/product-kits/*`

示例：

```bash
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
- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`
- `../guides/build-your-first-project.md`
- `../../../examples/README.zh-CN.md`
