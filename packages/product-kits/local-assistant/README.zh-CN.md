# Local Assistant Product Kit

规范 import root：`weavert_kit_local_assistant`

## 这个 package 拥有什么

- `weavert-scenario-local-assistant` scenario pack
- 叠加在共享 bridge packages 之上的 host-centric local-assistant 产品画像默认值

## 规范名称

- 安装名：`weavert-kit-local-assistant`
- import root：`weavert_kit_local_assistant`
- scenario pack：`weavert-scenario-local-assistant`

## 它组合了哪些共享 packages

- `weavert_kit_common_retrieval`
- `weavert_kit_common_browser`
- `weavert_kit_common_local_os`
- `weavert_kit_common_pim`

## 什么时候选它，而不是旁边那些包

- 当你的 app 自己拥有 host approvals，而且需要 browser、local-machine 或 PIM bridges 组成一个 higher-layer profile 时，选 `weavert-kit-local-assistant`。
- 如果你只需要 retrieval 加公网 web 的 grounded answers，不要选它；更轻的是 `weavert-kit-chat`。
- 如果你只想拿一个 lower-layer bridge，而不是整个 profile，就直接装对应的 common kit。

## 另见

- `../README.zh-CN.md`
- `../common/README.zh-CN.md`
- `../../../docs/zh-CN/guides/use-scenario-packs.md`
- `../../../docs/zh-CN/concepts/hosts-permissions-memory.md`
