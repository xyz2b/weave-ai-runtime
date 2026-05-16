# Install From Source

This guide covers the local-checkout editable install path.
Use it when you are developing inside this repository, debugging first-party packages from source, or you need sibling package discovery against a checkout.

## Who is this for?

- Repository maintainers working inside a local checkout.
- Users modifying first-party WeaveRT packages from source.

## Prerequisites

- Python 3.11+
- a local checkout of this repository
- a shell that can create and activate a virtual environment

## Base install

Create a virtual environment and install the full ordinary-workflow baseline plus starter and testing from editable local roots:

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

If you only want the default published first run and you are not editing first-party packages, use `installation.md` instead.

If you need help choosing between `weavert`, `weavert-full`, scenario kits, or shared kits, read:

- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`

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

- `installation.md`
- `quickstart.md`
- `starter-scaffolds.md`
- `../reference/runtime-config.md`

## Next step

- Run `quickstart.md` to prove the source install works end to end.
- Use `starter-scaffolds.md` if you want to generate a project instead of reading the repo in place.

## See also

- `installation.md`
- `quickstart.md`
- `starter-scaffolds.md`
- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`
- `../guides/build-your-first-project.md`
- `../../examples/README.md`
