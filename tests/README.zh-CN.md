# 测试根目录

仓库级回归覆盖位于 `tests/`。

测试应假设规范 import roots 是工作区里的 `packages/**/src/` 目录；面向 examples 的 acceptance coverage 也应把读者指向 `examples/README.zh-CN.md`，而不是历史上的 `demos/` 路径。若是 framework-pack 拥有的 smoke 或 ownership tests，且它们不需要与 core runtime 跨层交叉验证，就应放在 `tests/framework-packs/` 下。
