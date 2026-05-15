# Choose Package Combinations

This guide recommends package combinations for common WeaveRT adoption paths.
Use it after reading the public package catalog when you know the package names but still need a practical install choice.

## Who is this for?

- users deciding what to install from the published package set
- teams trying to standardize one or two supported package baselines
- maintainers writing onboarding docs or product-specific setup instructions

## Default recommendation order

Prefer these in order unless you have a reason to stay narrower:

1. `weavert-starter` + `weavert-testing`
2. `weavert-full`
3. `weavert` plus selective framework packs

The narrower you go, the more package-selection work you own directly.

## Recommended combinations

### 1. Starter-first project onboarding

Install:

```bash
python -m pip install weavert-starter weavert-testing
```

Use when:

- you are new to WeaveRT
- you want the official scaffold path
- you want deterministic validation immediately after project generation

Why this combination:

- `weavert-starter` depends on `weavert-full`
- `weavert-testing` gives you the validation path that matches the generated scaffold
- this is the lowest-friction path for most new apps

### 2. Full runtime baseline without the starter CLI

Install:

```bash
python -m pip install weavert-full
```

Optional companion:

```bash
python -m pip install weavert-testing
```

Use when:

- you already have your own app shell
- you want the documented ordinary-workflow baseline
- you do not need scaffold generation

Why this combination:

- `weavert-full` installs the same first-party baseline that backs `RuntimeConfig.for_ordinary_workflow(...)`
- it is the simplest runtime-only published baseline

### 3. Narrow custom runtime

Install example:

```bash
python -m pip install \
  weavert \
  weavert-openai \
  weavert-stores-file \
  weavert-builtin-workflows
```

Add companions only when needed:

- `weavert-memory`
- `weavert-team`
- `weavert-planning`
- `weavert-devtools`
- `weavert-compaction`
- `weavert-isolation`

Use when:

- you want tighter control than `weavert-full`
- you are building a custom host or provider posture
- you want to keep the public surface intentionally small

Why this combination:

- `weavert` keeps you on the core kernel only
- framework packs let you add only the runtime seams you actually use

### 4. Coding assistant or repository copilot

Install:

```bash
python -m pip install weavert-full weavert-kit-coding weavert-testing
```

Use when:

- you want coding-oriented product defaults
- you need shared git and workspace-intelligence surfaces
- you plan to validate behavior deterministically in CI

Why this combination:

- `weavert-full` gives the standard first-party runtime baseline
- `weavert-kit-coding` layers the coding scenario profile on top
- `weavert-testing` is the natural companion for regression checks

Activation note:

- after installation, admit the manifests from `weavert_kit_coding`
- request `weavert-scenario-coding`

### 5. Chat or research assistant

Install:

```bash
python -m pip install weavert-full weavert-kit-chat
```

Optional companions:

```bash
python -m pip install weavert-testing
```

Use when:

- you want retrieval plus web grounding
- you are building a chat or research-oriented product profile
- you want a higher-layer starting point without surrendering host ownership

Why this combination:

- `weavert-kit-chat` composes the retrieval and web common kits
- you keep app ownership of final routes, stores, permissions, and host UX

Activation note:

- admit the manifests from `weavert_kit_chat`
- request `weavert-scenario-chat`

### 6. Local host-centric assistant

Install:

```bash
python -m pip install weavert-full weavert-kit-local-assistant
```

Optional companions:

```bash
python -m pip install weavert-testing
```

Use when:

- your app is host-centric
- you need browser, local-OS, or PIM bridges
- you want a product profile closer to a desktop or personal assistant

Why this combination:

- `weavert-kit-local-assistant` composes retrieval, browser, local-OS, and PIM bridge kits
- the app still owns the final host shell and approval posture

Activation note:

- admit the manifests from `weavert_kit_local_assistant`
- request `weavert-scenario-local-assistant`

### 7. Shared bridge only, without a full scenario profile

Install examples:

```bash
python -m pip install weavert-full weavert-kit-common-git
python -m pip install weavert-full weavert-kit-common-web
python -m pip install weavert-full weavert-kit-common-browser
```

Use when:

- you want one lower-layer bridge
- a full scenario profile would be too opinionated
- you are composing your own product profile manually

Recommended shared-kit choices:

- repository inspection only -> `weavert-kit-common-git`
- retrieval only -> `weavert-kit-common-retrieval`
- web grounding only -> `weavert-kit-common-web`
- browser bridge only -> `weavert-kit-common-browser`
- local machine bridge only -> `weavert-kit-common-local-os`
- PIM bridge only -> `weavert-kit-common-pim`
- workspace-aware coding support only -> `weavert-kit-common-workspace-intelligence`

## How to choose between framework packs and product kits

Choose framework packs when:

- you are extending runtime mechanics directly
- you want first-party add-ons such as memory, planning, OpenAI routes, or file stores
- you are shaping a custom baseline rather than taking a product profile

Choose shared or scenario kits when:

- the capability belongs to a product layer
- you want reusable bridges or product-profile defaults
- you need explicit package-manifest admission and `requested_packages`

## Typical pairing rules

- If you install `weavert-starter`, add `weavert-testing` unless you have a strong reason not to.
- If you install a scenario kit, keep `weavert-full` underneath unless you are deliberately rebuilding the baseline from selective framework packs.
- If you only need one product bridge, prefer a common kit over a full scenario kit.
- If you need the smallest supported public runtime, start with `weavert` and add framework packs one at a time.

## See also

- public inventory and canonical names: `../reference/public-package-catalog.md`
- scenario-pack activation workflow: `use-scenario-packs.md`
- install path overview: `../getting-started/installation.md`
