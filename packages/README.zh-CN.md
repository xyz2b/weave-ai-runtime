# Package 工作区

这个页面索引 `packages/` 下可发布的实现代码。

## 这里有什么

- `framework-core/` 拥有具体的 `weavert` runtime package。
- `framework-packs/` 拥有脱离 core import root 的 first-party add-on packages。
- `product-kits/` 拥有 scenario packs 与共享 product-kit packages。
- `toolchain/` 拥有开发者工具，例如采纳路径的 starter generator 和验证路径的 testing kit。

## 所有权规则

- 只有具体 package 才拥有自己的 `pyproject.toml`。
- 家族根目录保持为文档索引，而具体 package 拥有自己的 package-local metadata。
- 新代码应进入拥有它的 family，而不是默认漂回 core package。

## 如何阅读这棵树

- 当问题是 runtime kernel 或公开 `weavert` 表面时，从 `framework-core/` 开始。
- 当问题是 first-party add-on capabilities、mechanisms、integrations 或 workflows 时，用 `framework-packs/`。
- 当问题是 scenario packs 或共享 product-kit 组合时，用 `product-kits/`。
- 当问题是采纳或验证工具，而不是 runtime assembly 时，用 `toolchain/`。

## 另见

- `../README.zh-CN.md`
- `../docs/zh-CN/README.md`
- `framework-core/README.zh-CN.md`
- `product-kits/README.zh-CN.md`
- `toolchain/README.zh-CN.md`
