# WeaveRT Documentation

[English](README.md) | [简体中文](zh-CN/README.md)

This page is the docs home after the root [README.md](../README.md).
Treat the documentation as a layered journey, not one landing page plus a pile of long files.

1. GitHub landing page -> what WeaveRT is and why it exists
2. Getting started -> first successful run
3. Concepts -> runtime model and extension boundaries
4. Guides -> how to solve a concrete task
5. Architecture / reference / maintainers -> how the system is built and maintained

Starter is the adoption path.
Examples are the validation path.

## Start Here

- New to WeaveRT: [introduction/what-is-weavert.md](introduction/what-is-weavert.md)
- Need a first run: [getting-started/quickstart.md](getting-started/quickstart.md)
- Want the official starter path: [getting-started/starter-scaffolds.md](getting-started/starter-scaffolds.md)
- Want runnable validation after the starter: [../examples/README.md](../examples/README.md)

## Documentation Journey

### 1. Introduction

- [introduction/what-is-weavert.md](introduction/what-is-weavert.md)
- [introduction/use-cases.md](introduction/use-cases.md)
- [introduction/design-principles.md](introduction/design-principles.md)

### 2. Getting Started

- [getting-started/installation.md](getting-started/installation.md)
- [getting-started/install-from-source.md](getting-started/install-from-source.md)
- [getting-started/quickstart.md](getting-started/quickstart.md)
- [getting-started/starter-scaffolds.md](getting-started/starter-scaffolds.md)

### 3. Concepts

- [concepts/runtime-model.md](concepts/runtime-model.md)
- [concepts/tools-agents-skills.md](concepts/tools-agents-skills.md)
- [concepts/packages-and-scenario-packs.md](concepts/packages-and-scenario-packs.md)
- [concepts/hosts-permissions-memory.md](concepts/hosts-permissions-memory.md)
- [concepts/memory-model.md](concepts/memory-model.md)

### 4. Guides

- [guides/build-your-first-project.md](guides/build-your-first-project.md)
- [guides/choose-package-combinations.md](guides/choose-package-combinations.md)
- [guides/add-a-tool.md](guides/add-a-tool.md)
- [guides/add-an-agent.md](guides/add-an-agent.md)
- [guides/add-a-skill.md](guides/add-a-skill.md)
- [guides/integrate-openai.md](guides/integrate-openai.md)
- [guides/use-scenario-packs.md](guides/use-scenario-packs.md)
- [guides/bind-a-host.md](guides/bind-a-host.md)
- [guides/extend-the-control-plane.md](guides/extend-the-control-plane.md)
- [guides/register-hooks.md](guides/register-hooks.md)
- [guides/testing-and-observability.md](guides/testing-and-observability.md)

### 5. Architecture

- [architecture/overview.md](architecture/overview.md)
- [architecture/request-lifecycle.md](architecture/request-lifecycle.md)
- [architecture/package-system.md](architecture/package-system.md)
- [architecture/persistence-and-state.md](architecture/persistence-and-state.md)

### 6. Reference

- [reference/public-package-catalog.md](reference/public-package-catalog.md)
- [reference/runtime-config.md](reference/runtime-config.md)
- [reference/workspace-layout.md](reference/workspace-layout.md)
- [reference/memory-configuration.md](reference/memory-configuration.md)
- [reference/hook-registration.md](reference/hook-registration.md)
- [reference/workflow-observability.md](reference/workflow-observability.md)
- [reference/glossary.md](reference/glossary.md)

### 7. Maintainers

- [maintainers/repository-layout.md](maintainers/repository-layout.md)
- [maintainers/pypi-release-readiness.md](maintainers/pypi-release-readiness.md)
- [maintainers/migration-notes.md](maintainers/migration-notes.md)
- [maintainers/validation-findings.md](maintainers/validation-findings.md)

## Choose Your Path

- I want the smallest successful project -> [getting-started/starter-scaffolds.md](getting-started/starter-scaffolds.md)
- I want the first real project path -> [guides/build-your-first-project.md](guides/build-your-first-project.md)
- I need the published package catalog -> [reference/public-package-catalog.md](reference/public-package-catalog.md)
- I need package-combination recommendations -> [guides/choose-package-combinations.md](guides/choose-package-combinations.md)
- I am working from a repository checkout -> [getting-started/install-from-source.md](getting-started/install-from-source.md)
- I want to understand the runtime model -> [concepts/runtime-model.md](concepts/runtime-model.md)
- I want to understand memory behavior -> [concepts/memory-model.md](concepts/memory-model.md)
- I want to extend tools, agents, or skills -> [guides/add-a-tool.md](guides/add-a-tool.md), [guides/add-an-agent.md](guides/add-an-agent.md), and [guides/add-a-skill.md](guides/add-a-skill.md)
- I want host, hook, or control-plane behavior -> [guides/bind-a-host.md](guides/bind-a-host.md), [guides/extend-the-control-plane.md](guides/extend-the-control-plane.md), and [guides/register-hooks.md](guides/register-hooks.md)
- I want to validate real workflows -> [../examples/README.md](../examples/README.md)
- I maintain the repository -> [maintainers/repository-layout.md](maintainers/repository-layout.md) and [maintainers/pypi-release-readiness.md](maintainers/pypi-release-readiness.md)

## Deep Dives

The layered structure above is the primary reading path.
Use deep dives only when the primary doc has already answered the public "what" and "how," and you now need the lower-level boundary ledger.

Useful entrypoints:

- runtime and integration boundaries -> [deep-dives/weavert-integration-guide.md](deep-dives/weavert-integration-guide.md)
- definition and extension boundaries -> [deep-dives/weavert-definition-authoring-guide.md](deep-dives/weavert-definition-authoring-guide.md)
- package and scenario-pack boundaries -> [deep-dives/weavert-scenario-runtime-pack-architecture.md](deep-dives/weavert-scenario-runtime-pack-architecture.md)
- host, hook, and control-plane boundaries -> [deep-dives/weavert-control-plane-extension-guide.md](deep-dives/weavert-control-plane-extension-guide.md)
- full index -> [deep-dives/README.md](deep-dives/README.md)
- framework-pack docs index -> [framework-packs/README.md](framework-packs/README.md)

## Maintainer Ledgers

Maintainer-only evidence trails and migration ledgers live under:

- [maintainers/validation-findings.md](maintainers/validation-findings.md)
- [maintainers/migration-notes.md](maintainers/migration-notes.md)
- [maintainers/repository-layout.md](maintainers/repository-layout.md)
- [maintainers/pypi-release-readiness.md](maintainers/pypi-release-readiness.md)
