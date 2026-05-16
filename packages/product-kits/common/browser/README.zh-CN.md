# Browser Common Kit

规范 import root：`weavert_kit_common_browser`

## 这个 package 拥有什么

- 可复用的 browser bridge surfaces
- 被 local-assistant product-kit composition 使用的共享 browser-facing tooling

## 规范名称

- 安装名：`weavert-kit-common-browser`
- import root：`weavert_kit_common_browser`

## 不要把它和这些包混在一起

- 当你的 app 自己拥有 browser bridge，而 assistant 需要浏览器状态、导航、点击、填表或提取步骤时，选这个包。
- 如果你要的是公网 web 搜索或远程页面抓取，不要选它；那属于 `weavert-kit-common-web`。
- 如果你要的是 files、clipboard 这类通用本地机器表面，也不要选它；那属于 `weavert-kit-common-local-os`。

## 另见

- `../README.zh-CN.md`
- `../../local-assistant/README.zh-CN.md`
- `../../../../docs/zh-CN/concepts/packages-and-scenario-packs.md`
