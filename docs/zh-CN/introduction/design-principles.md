# 设计原则

这些原则同时塑造公开文档路径和运行时本身。

## 适合谁？

- 正在判断 WeaveRT 是什么，以及它是否适合自己产品或工作流的仓库访问者。

## 前置条件

- 无。这个层级设计成在读完根目录 `../../../README.zh-CN.md` 后就能直接阅读。

## 运行时优先于 prompt

WeaveRT 把 prompt 视为更大执行模型中的一个组成部分。
Session、turn、tools、agents、skills、permissions 和 memory 都仍是一级运行时关注点。

## 清晰的所有权边界

运行时负责 orchestration。
Host 负责产品 UX、审批和呈现。
Packages 可以贡献能力和指导，但不会悄悄接管 host。

## 组合优先于单体

工具、智能体、技能、包和宿主承担不同职责。
保持这些 seam 分离，才能更容易从小规模起步，并安全扩展。

## 先依赖稳定表面

推荐路径是：

1. starter scaffold
2. 项目内 `.weavert/` 定义
3. 针对任务的 guide
4. 用于验证的 examples
5. host 绑定与 package 组合

## 可见性优先于魔法

权限、route 失败、package 激活、诊断和持久状态都应保持可检查。
框架使用者不应该靠猜测来判断是谁在做决定。

下一步阅读：

- `../concepts/runtime-model.md`
- `../architecture/overview.md`

## 下一步

- 读 `../concepts/runtime-model.md`，把这些原则连接到稳定的运行时表面
- 当你想看实现导向的层级地图时，进入 `../architecture/overview.md`

## 另见

- `what-is-weavert.md`
- `use-cases.md`
- `../concepts/runtime-model.md`
- `../architecture/overview.md`
