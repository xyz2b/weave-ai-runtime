# Chat Product Kit

规范 import root：`weavert_kit_chat`

## 这个 package 拥有什么

- `weavert-scenario-chat` scenario pack
- 叠加在共享 grounding packages 之上的 chat-oriented 产品画像默认值

## 规范名称

- 安装名：`weavert-kit-chat`
- import root：`weavert_kit_chat`
- scenario pack：`weavert-scenario-chat`

## 它组合了哪些共享 packages

- `weavert_kit_common_retrieval`
- `weavert_kit_common_web_research`

## 什么时候选它，而不是旁边那些包

- 当你想直接拿一个已经组合好 retrieval 和公网 web grounding 的 higher-layer profile 时，选 `weavert-kit-chat`。
- 如果你的 app 主要需要 host-mediated browser、local-machine 或 PIM bridges，不要选它；那是 `weavert-kit-local-assistant` 的职责。
- 如果你只想拿一个 lower-layer capability，而不是完整 chat profile，就直接装 `weavert-kit-common-retrieval` 或 `weavert-kit-common-web-research`。

## 另见

- `../README.zh-CN.md`
- `../common/README.zh-CN.md`
- `../../../docs/zh-CN/guides/use-scenario-packs.md`
- `../../../docs/zh-CN/introduction/use-cases.md`
