# 从源码安装

这篇指南覆盖本地仓库 checkout 的 editable 安装路径。
当你正在这个仓库里开发、需要直接调试 first-party package 源码，或者需要基于 checkout 做同级 package 发现时，就用这页。

## 适合谁？

- 在本地 checkout 里工作的仓库维护者。
- 需要直接修改 WeaveRT first-party package 源码的使用者。

## 前置条件

- Python 3.11+
- 此仓库的本地副本
- 能创建并激活虚拟环境的 shell

## 基础安装

创建虚拟环境，并从本地 editable roots 安装完整 ordinary-workflow baseline、starter 与 testing：

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

如果你只是想走默认的已发布包首轮路径，而且并不打算编辑 first-party packages，请改看 `installation.md`。

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

- `installation.md`
- `quickstart.md`
- `starter-scaffolds.md`
- `../reference/runtime-config.md`

## 下一步

- 运行 `quickstart.md`，验证源码安装能否端到端跑通
- 如果你想生成一个项目，而不是直接在仓库内阅读，请继续看 `starter-scaffolds.md`

## 另见

- `installation.md`
- `quickstart.md`
- `starter-scaffolds.md`
- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`
- `../guides/build-your-first-project.md`
- `../../../examples/README.zh-CN.md`
