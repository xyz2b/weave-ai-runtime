# 如何选择包组合

这篇指南给出常见 WeaveRT 采纳路径的推荐包组合。
当你已经知道公开包目录里的包名，但还拿不准“实际该装哪一组”时，就读这页。

## 适合谁？

- 正在决定从公开包集里安装什么的使用者
- 想标准化 1 到 2 套支持安装基线的团队
- 正在写 onboarding 或产品安装文档的维护者

## 默认推荐顺序

除非你有明确理由要保持更窄，否则优先顺序建议是：

1. `weavert-starter` + `weavert-testing`
2. `weavert-full`
3. `weavert` 加 selective framework packs

你走得越窄，自己承担的 package-selection 工作就越多。

## 推荐组合

### 1. Starter-first 项目启动

安装：

```bash
python -m pip install weavert-starter weavert-testing
```

适用场景：

- 你刚接触 WeaveRT
- 你想走官方 scaffold 路径
- 你希望在生成项目之后立刻拥有确定性验证能力

为什么这么配：

- `weavert-starter` 依赖 `weavert-full`
- `weavert-testing` 提供与生成 scaffold 对应的验证路径
- 这是大多数新项目摩擦最小的路径

### 2. 不使用 starter CLI 的完整 runtime baseline

安装：

```bash
python -m pip install weavert-full
```

可选搭配：

```bash
python -m pip install weavert-testing
```

适用场景：

- 你已经有自己的 app shell
- 你想采用文档里的 ordinary-workflow baseline
- 你不需要 scaffold generation

为什么这么配：

- `weavert-full` 安装的就是 `RuntimeConfig.for_ordinary_workflow(...)` 背后的 first-party baseline
- 它是最简单的 runtime-only 公开安装基线

### 3. 窄定制 runtime

安装示例：

```bash
python -m pip install \
  weavert \
  weavert-openai \
  weavert-stores-file \
  weavert-builtin-workflows
```

按需继续增加：

- `weavert-memory`
- `weavert-team`
- `weavert-planning`
- `weavert-devtools`
- `weavert-compaction`
- `weavert-isolation`

适用场景：

- 你想比 `weavert-full` 更严格地控制 surface
- 你在构建自定义 host 或 provider posture
- 你想刻意把公开 surface 保持在较小范围

为什么这么配：

- `weavert` 让你从 core kernel-only 起步
- framework packs 让你只增加真正需要的 runtime seams

### 4. Coding assistant / repository copilot

安装：

```bash
python -m pip install weavert-full weavert-kit-coding weavert-testing
```

适用场景：

- 你想使用 coding-oriented product defaults
- 你需要 shared git 与 workspace-intelligence surfaces
- 你计划在 CI 里做确定性验证

为什么这么配：

- `weavert-full` 提供标准 first-party runtime baseline
- `weavert-kit-coding` 在其之上叠加 coding scenario profile
- `weavert-testing` 是最自然的回归验证搭档

激活提醒：

- 安装后还要 admit `weavert_kit_coding` 的 manifests
- 再 request `weavert-scenario-coding`

### 5. Chat / research assistant

安装：

```bash
python -m pip install weavert-full weavert-kit-chat
```

可选搭配：

```bash
python -m pip install weavert-testing
```

适用场景：

- 你想要 retrieval 加 web grounding
- 你在构建 chat 或 research-oriented product profile
- 你想从 higher-layer starting point 开始，但又不放弃 host ownership

为什么这么配：

- `weavert-kit-chat` 组合了 retrieval 与 web common kits
- 你仍然保有对 routes、stores、permissions 与 host UX 的最终控制权

激活提醒：

- admit `weavert_kit_chat` 的 manifests
- request `weavert-scenario-chat`

### 6. 面向本地主机的 assistant

安装：

```bash
python -m pip install weavert-full weavert-kit-local-assistant
```

可选搭配：

```bash
python -m pip install weavert-testing
```

适用场景：

- 你的 app 以 host 为中心
- 你需要 browser、local-OS 或 PIM bridges
- 你想要更接近桌面助手或个人助手的产品 profile

为什么这么配：

- `weavert-kit-local-assistant` 组合了 retrieval、browser、local-OS 与 PIM bridge kits
- 但最终 host shell 与 approval posture 仍然归 app 所有

激活提醒：

- admit `weavert_kit_local_assistant` 的 manifests
- request `weavert-scenario-local-assistant`

### 7. 只拿 shared bridge，不采用完整 scenario profile

安装示例：

```bash
python -m pip install weavert-full weavert-kit-common-git
python -m pip install weavert-full weavert-kit-common-web-research
python -m pip install weavert-full weavert-kit-common-browser
```

适用场景：

- 你只想拿一个 lower-layer bridge
- 完整 scenario profile 对你来说太重或太有倾向性
- 你想手动组合自己的产品 profile

推荐的 shared-kit 选择：

- 只要 repository inspection -> `weavert-kit-common-git`
- 只要 retrieval -> `weavert-kit-common-retrieval`
- 只要 web research -> `weavert-kit-common-web-research`
- 只要 browser bridge -> `weavert-kit-common-browser`
- 只要 local machine bridge -> `weavert-kit-common-local-os`
- 只要 PIM bridge -> `weavert-kit-common-pim`
- 只要 workspace-aware coding support -> `weavert-kit-common-workspace-intelligence`

## 常见易混选择

- 想把 notes、memory 或已经抓回来的文本排成 grounding 结果并准备 citations -> `weavert-kit-common-retrieval`
- 想在只读姿态下搜索公网网页、抓取页面、页面内查找或做 profile-driven research -> `weavert-kit-common-web-research`
- 想通过 app-owned browser bridge 获取浏览器状态、导航、点击、填表或提取 -> `weavert-kit-common-browser`
- 想接入 files、clipboard、notifications、processes 这类通用本地机器表面 -> `weavert-kit-common-local-os`
- 想接入 calendar、contacts、reminders、tasks 这类结构化个人信息表面 -> `weavert-kit-common-pim`
- 想直接拿一个已经组合好 retrieval 和公网 web grounding 的 higher-layer chat profile -> `weavert-kit-chat`
- 想直接拿一个已经组合好 retrieval、browser、local-OS 和 PIM bridges 的 host-centric assistant profile -> `weavert-kit-local-assistant`

## 如何在 framework packs 和 product kits 之间做选择

在下面这些情况选 framework packs：

- 你是在直接扩展 runtime mechanics
- 你要的是 memory、planning、OpenAI routes 或 file stores 这样的 first-party add-ons
- 你是在塑造自定义 baseline，而不是采用产品 profile

在下面这些情况选 shared kits 或 scenario kits：

- 这个能力本来就属于产品层
- 你想拿的是可复用 bridges 或 product-profile defaults
- 你需要显式的 package-manifest admission 与 `requested_packages`

## 常见搭配规则

- 如果你装了 `weavert-starter`，除非有强理由，否则同时装上 `weavert-testing`。
- 如果你装了 scenario kit，通常底下保留 `weavert-full`，除非你是在刻意用 selective framework packs 重新组 baseline。
- 如果你只需要一个 product bridge，优先选 common kit，而不是完整 scenario kit。
- 如果你要最小支持公开 runtime，从 `weavert` 开始，再按需逐个加 framework packs。

## 另见

- 公开包目录与规范名字：`../reference/public-package-catalog.md`
- scenario-pack 激活流程：`use-scenario-packs.md`
- 默认 starter-first 安装路径：`../getting-started/installation.md`
- source checkout 安装路径：`../getting-started/install-from-source.md`
