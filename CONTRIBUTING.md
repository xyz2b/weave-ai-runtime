# Contributing to WeaveRT

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

Thanks for contributing.
This repository is organized as a runtime framework workspace, so small, well-scoped changes are easier to review and safer to validate.

## Before You Start

- read `README.md` for the project position
- read `docs/README.md` for the documentation journey
- use `examples/README.md` to understand the validation path
- read `CODE_OF_CONDUCT.md` before participating

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
python -m pip install -e .[dev]
```

Install additional package families only when your change needs them.

## Development Workflow

- prefer focused changes over broad unrelated refactors
- keep runtime, docs, examples, and tests aligned
- update docs when public behavior or the recommended path changes
- preserve the separation between landing-page docs, end-user docs, and maintainer notes

## Documentation Conventions

- `README.md` is the landing page, not the full manual
- `docs/README.md` is the docs home
- guides should answer: who it is for, prerequisites, steps, expected result, and next step
- examples are the validation path, not the default getting-started path
- prefer English filenames and stable predictable titles for new public docs

## Validation

Run the smallest relevant validation first.
Useful entry points include:

```bash
pytest tests/test_runtime_extension_demos.py
python3 -B -m examples.tools.file_backed_tool_demo
python3 -B -m examples.projects.coding_workflow_demo
```

If your change affects a specific example, run that example directly as well.

## Pull Requests

In your PR description, include:

- what changed
- why it changed
- how you validated it
- any follow-up work that remains out of scope

## Security

For vulnerabilities or sensitive reports, follow `SECURITY.md` instead of opening a public issue first.
