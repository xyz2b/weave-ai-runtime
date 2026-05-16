# Web Common Kit

规范 import root：`weavert_kit_common_web`

## 这个 package 拥有什么

- 可复用的只读 web grounding surfaces
- 被 chat 与 local-assistant product-kit composition 使用的共享 web tooling

## 规范名称

- 安装名：`weavert-kit-common-web`
- import root：`weavert_kit_common_web`

## 不要把它和这些包混在一起

- 当你需要只读的公网 web 搜索或受限远程页面抓取来做 grounding 时，选这个包。
- 如果还要对抓回来的材料做排序或 citation 准备，再搭配 `weavert-kit-common-retrieval`。
- 如果 assistant 需要在 app-owned browser 里导航、点击或填表，不要选它；那属于 `weavert-kit-common-browser`。

## 另见

- `../README.zh-CN.md`
- `../../chat/README.zh-CN.md`
- `../../../../docs/zh-CN/introduction/use-cases.md`
