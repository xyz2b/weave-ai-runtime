---
description: 为这个 demo 强制执行轻量 coding workflow 顺序。
context: inline
user-invocable: false
---
在当前 turn 中遵循如下顺序：

1. 编辑前先检查相关源码或测试。
2. 做出能修复 bug 的最小编辑。
3. 编辑后运行单元测试命令。
4. 总结前先运行 `review-change` skill。
5. 最终简洁总结改动文件、verification 结果与 review 结果。
