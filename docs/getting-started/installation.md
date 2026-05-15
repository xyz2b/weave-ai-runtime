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

Create a virtual environment and install the full ordinary-workflow baseline plus starter and testing in one command:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  -e packages/framework-core \
  -e packages/framework-packs/capabilities/memory \
  -e packages/framework-packs/capabilities/team \
  -e packages/framework-packs/mechanisms/compaction \
  -e packages/framework-packs/mechanisms/isolation \
  -e packages/framework-packs/integrations/openai \
  -e packages/framework-packs/integrations/hosts-reference \
  -e packages/framework-packs/integrations/stores-file \
  -e packages/framework-packs/workflows/builtin-workflows \
  -e packages/framework-packs/workflows/planning \
  -e packages/framework-packs/workflows/devtools \
  -e packages/distributions/full \
  -e packages/toolchain/starter \
  -e packages/toolchain/testing
```

If you are installing from published packages instead of editable local roots, the matching one-command baseline is:

```bash
python -m pip install weavert-starter weavert-testing
```

`weavert-starter` now depends on `weavert-full`, so the published starter path pulls the documented ordinary-workflow runtime baseline automatically.

## Optional first-party packages

Install additional scenario or product-kit packages only when you need them:

- product kits: `packages/product-kits/*`

Example:

```bash
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
