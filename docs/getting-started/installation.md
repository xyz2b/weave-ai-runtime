# Installation

This guide covers the local-checkout install path.
It is the safest way to understand the repo because examples and starter scaffolds can discover sibling packages directly.

## Who is this for?

- Developers setting up a local checkout of the repository for the first time.

## Prerequisites

- Python 3.11+
- a local checkout of this repository
- a shell that can create and activate a virtual environment

## Base install

Create a virtual environment and install the runtime core plus starter toolchain:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
```

## Optional first-party packages

Install additional packages only when you need them:

- OpenAI integration: `packages/framework-packs/integrations/openai`
- reference hosts: `packages/framework-packs/integrations/hosts-reference`
- file stores: `packages/framework-packs/integrations/stores-file`
- product kits: `packages/product-kits/*`

Example:

```bash
python -m pip install -e packages/framework-packs/integrations/openai
python -m pip install -e packages/product-kits/coding
```

## Verify the toolchain

```bash
weavert-starter list
```

You should see the official scaffold catalog, including `minimal-project`, `headless-workflow`, and `live-smoke`.

Next reading:

- `quickstart.md`
- `starter-scaffolds.md`
- `../reference/runtime-config.md`

## Next step

- Run `quickstart.md` to prove the local install works end to end.
- Use `starter-scaffolds.md` if you want to generate a project instead of reading the repo in place.

## See also

- `quickstart.md`
- `starter-scaffolds.md`
- `../guides/build-your-first-project.md`
- `../../examples/README.md`
