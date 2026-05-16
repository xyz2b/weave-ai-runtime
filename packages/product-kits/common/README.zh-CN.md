# 共享 Product-Kit Packages

这个 family 汇总会被多个 scenario packs 复用的 product-kit packages。

## 这个 family 拥有什么

- 可复用桥接能力，如 retrieval、web-research、git、browser、local-OS、PIM 与 workspace intelligence
- 位于 scenario-pack 所有权之下的共享 product-kit packages

## 具体 packages

- `retrieval/` -> `weavert_kit_common_retrieval`
- `web-research/` -> `weavert_kit_common_web_research`
- `git/` -> `weavert_kit_common_git`
- `workspace-intelligence/` -> `weavert_kit_common_workspace_intelligence`
- `browser/` -> `weavert_kit_common_browser`
- `local-os/` -> `weavert_kit_common_local_os`
- `pim/` -> `weavert_kit_common_pim`

## 所有权规则

- 当某个可复用 product-kit bridge 应被多个 scenario packs 组合时，把它放在这里。
- 产品画像默认值则保留在这一层之上的 scenario-pack packages 中。

## 快速边界检查

- `retrieval` 负责对你已经拿到的 grounding 做排序和 citation 准备。
- `web-research` 负责只读地搜索公网网站、抓取远程文本、页面内查找，并通过 `web_research` 支持 profile-driven research。
- `browser` 负责通过 host-mediated browser bridge 提供状态、导航与交互。
- `local-os` 负责暴露 files、clipboard、notifications、processes 这类通用本地机器表面。
- `pim` 负责暴露 calendars、contacts、reminders、tasks 这类结构化个人数据表面。

## 另见

- `../README.zh-CN.md`
- `retrieval/README.zh-CN.md`
- `git/README.zh-CN.md`
- `browser/README.zh-CN.md`
- `../../../docs/zh-CN/concepts/packages-and-scenario-packs.md`
