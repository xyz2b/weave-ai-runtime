# PIM Common Kit

规范 import root：`weavert_kit_common_pim`

## 这个 package 拥有什么

- 可复用的日历、联系人、提醒与任务桥接表面
- 被 local-assistant product-kit composition 使用的共享 PIM tooling

## 规范名称

- 安装名：`weavert-kit-common-pim`
- import root：`weavert_kit_common_pim`

## 不要把它和这些包混在一起

- 当你需要 calendars、contacts、reminders、tasks 这类结构化个人信息表面时，选这个包。
- 如果你要的是通用的 file、clipboard、notification 或 process access，不要选它；那属于 `weavert-kit-common-local-os`。
- 如果你要的是浏览器 tab 或页面交互，也不要选它；那属于 `weavert-kit-common-browser`。

## 另见

- `../README.zh-CN.md`
- `../../local-assistant/README.zh-CN.md`
- `../../../../docs/zh-CN/concepts/packages-and-scenario-packs.md`
