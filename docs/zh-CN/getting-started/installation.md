# 安装

这篇指南覆盖默认的已发布包安装路径。
当你想走最短的官方首轮成功路径，而且并不打算在仓库 checkout 里直接编辑 WeaveRT 一方包时，就用这页。

## 适合谁？

- 想走官方 starter-first 采纳路径的新 WeaveRT 用户。
- 正在编写面向已发布包集 onboarding 文档的团队。

## 前置条件

- Python 3.11+
- 能创建并激活虚拟环境的 shell
- 能访问承载 WeaveRT 已发布包的包索引

## 基础安装

创建虚拟环境，并用一条命令安装 starter-first 基线：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install weavert-starter weavert-testing
```

`weavert-starter` 依赖 `weavert-full`，所以这一条命令已经会拉起官方 starter scaffolds 使用的 ordinary-workflow runtime baseline。

如果你是在本地 source checkout 里工作，或者需要 editable 的 first-party packages，请改看 `install-from-source.md`。

如果你需要判断该选 `weavert`、`weavert-full`、scenario kits 还是 shared kits，请继续看：

- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`

## 可选 first-party packages

只有在需要时再补装 scenario 或 product-kit packages：

- product kits：`weavert-kit-*`

示例：

```bash
python -m pip install weavert-kit-coding
```

## 验证工具链

```bash
weavert-starter list
```

你应能看到官方 scaffold 目录，包括 `minimal-project`、`headless-workflow` 和 `live-smoke`。

下一步阅读：

- `quickstart.md`
- `starter-scaffolds.md`
- `install-from-source.md`
- `../reference/runtime-config.md`

## 下一步

- 运行 `quickstart.md`，验证已发布包安装能否端到端跑通
- 如果你需要 editable 的 first-party packages，请继续看 `install-from-source.md`

## 另见

- `quickstart.md`
- `starter-scaffolds.md`
- `install-from-source.md`
- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`
- `../guides/build-your-first-project.md`
- `../../../examples/README.zh-CN.md`
