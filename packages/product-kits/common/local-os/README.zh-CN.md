# Local OS Common Kit

规范 import root：`weavert_kit_common_local_os`

## 这个 package 拥有什么

- 可复用的 local-OS bridge surfaces
- 被 local-assistant product-kit composition 使用的共享本地设备工具

## 规范名称

- 安装名：`weavert-kit-common-local-os`
- import root：`weavert_kit_common_local_os`

## 不要把它和这些包混在一起

- 当你需要 files、clipboard、notifications、processes 这类通用本地机器表面时，选这个包。
- 如果你要的是结构化的 calendar、contacts、reminders 或 tasks，不要选它；那属于 `weavert-kit-common-pim`。
- 如果目标表面是浏览器 tab 或 page，也不要选它；那属于 `weavert-kit-common-browser`。

## 另见

- `../README.zh-CN.md`
- `../../local-assistant/README.zh-CN.md`
- `../../../../docs/zh-CN/concepts/hosts-permissions-memory.md`
