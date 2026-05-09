# Framework-Pack Integrations

由 integration 拥有的 first-party add-ons 现在位于这个工作区家族下。

## 这个角色家族拥有什么

- 面向 providers、hosts 和 runtime stores 的 first-party integrations
- 将 runtime 绑定到具体外部系统、但不直接成为 app-owned host 的 packages

## 具体 packages

- `openai/`：`weavert-openai`，import root 为 `weavert_openai`
- `hosts-reference/`：`weavert-hosts-reference`，import root 为 `weavert_hosts_reference`
- `stores-file/`：`weavert-stores-file`，import root 为 `weavert_stores_file`

## 所有权规则

- 把可复用的 first-party integration packages 放在这里。
- 最终 app-owned host wiring 不应放进这个 family。

## 另见

- `../README.zh-CN.md`
- `openai/README.zh-CN.md`
- `hosts-reference/README.zh-CN.md`
- `stores-file/README.zh-CN.md`
- `../../../docs/zh-CN/guides/integrate-openai.md`
