# Retrieval Common Kit

规范 import root：`weavert_kit_common_retrieval`

## 这个 package 拥有什么

- 可复用的 retrieval 与 citation surfaces
- 被 chat 与 local-assistant product-kit composition 使用的共享 grounding tooling

## 规范名称

- 安装名：`weavert-kit-common-retrieval`
- import root：`weavert_kit_common_retrieval`

## 不要把它和这些包混在一起

- 当你已经有 notes、memory 或 fetched passages 这类 grounding candidates，只需要排序与 citation 准备时，选这个包。
- 如果你还需要先做公网 web 搜索、远程抓取、页面内查找或 profile-driven research，再搭配 `weavert-kit-common-web-research`。
- 如果你需要浏览器导航或交互，不要选它；那属于 `weavert-kit-common-browser`。

## 另见

- `../README.zh-CN.md`
- `../../chat/README.zh-CN.md`
- `../../local-assistant/README.zh-CN.md`
- `../../../../docs/zh-CN/concepts/memory-model.md`
