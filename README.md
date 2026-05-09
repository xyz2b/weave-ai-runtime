<p align="center">
  <img src="docs/logo.png" alt="WeaveRT logo" width="160">
</p>

# WeaveRT

Composable AI runtime framework for building agent systems with tools, agents, skills, hosts, memory, workflow packages, and scenario packs.

## What is WeaveRT?

WeaveRT is a runtime framework for building and operating agent systems.
It gives you a stable runtime core plus clear extension surfaces for tools, agents, skills, hosts, permissions, memory, workflow packages, and scenario packs.

It is not a single preset assistant app.
You can start with a small project-local workflow, then grow into coding, chat, or local-assistant products without rewriting the runtime model.

## Why WeaveRT?

- Build on a runtime, not a single prompt.
- Compose tools, agents, skills, and packages without hiding ownership boundaries.
- Keep host integration, permissions, and durable state explicit.
- Start with a minimal scaffold, then grow into richer workflows and apps.

## Quickstart

The default first run is the starter, not `examples/`.
Starter is the adoption path. Examples are the validation path.

From a local checkout, the shortest path is:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
weavert-starter generate minimal-project ./my-weavert-app
cd my-weavert-app
python -m pip install -e .
python app.py
```

Expected first-run anchors:

- `preset: ordinary-workflow`
- `assistant: The scaffold is ready...`
- `status: ok`

## Start Here

- Docs home: [docs/README.md](docs/README.md)
- First run: [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)
- Official starter path: [docs/getting-started/starter-scaffolds.md](docs/getting-started/starter-scaffolds.md)
- Runnable validation path: [examples/README.md](examples/README.md)

## Choose Your Path

- I want the smallest successful project -> [docs/getting-started/starter-scaffolds.md](docs/getting-started/starter-scaffolds.md)
- I want the first real project path -> [docs/guides/build-your-first-project.md](docs/guides/build-your-first-project.md)
- I want to understand the runtime model: read [docs/introduction/what-is-weavert.md](docs/introduction/what-is-weavert.md) and [docs/concepts/runtime-model.md](docs/concepts/runtime-model.md)
- I want to extend tools, agents, or skills: go to [docs/guides/add-a-tool.md](docs/guides/add-a-tool.md), [docs/guides/add-an-agent.md](docs/guides/add-an-agent.md), and [docs/guides/add-a-skill.md](docs/guides/add-a-skill.md)
- I want host, hook, or control-plane integration: go to [docs/guides/bind-a-host.md](docs/guides/bind-a-host.md), [docs/guides/extend-the-control-plane.md](docs/guides/extend-the-control-plane.md), and [docs/guides/register-hooks.md](docs/guides/register-hooks.md)
- I want to validate real workflows: use [examples/README.md](examples/README.md)
- I maintain the repository: use [docs/maintainers/repository-layout.md](docs/maintainers/repository-layout.md) and [docs/maintainers/migration-notes.md](docs/maintainers/migration-notes.md)

## Examples

- Seam basics and validation path: [examples/README.md](examples/README.md)
- Ordinary coding workflow validation: [examples/README.md](examples/README.md)
- Advanced host-bound integration sample: [examples/apps/code_assistant/README.md](examples/apps/code_assistant/README.md)

Generate a starter first unless you are specifically evaluating framework seams or validation evidence.

## Architecture and Reference

- Architecture overview: [docs/architecture/overview.md](docs/architecture/overview.md)
- Request lifecycle: [docs/architecture/request-lifecycle.md](docs/architecture/request-lifecycle.md)
- RuntimeConfig reference: [docs/reference/runtime-config.md](docs/reference/runtime-config.md)
- Full docs index: [docs/README.md](docs/README.md)

## Status

WeaveRT is under active development.
The documentation is organized as a layered journey:
landing page -> getting started -> concepts -> guides -> architecture/reference/maintainers.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, workflow, and documentation conventions.
Community expectations live in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and vulnerability reporting guidance lives in [SECURITY.md](SECURITY.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
