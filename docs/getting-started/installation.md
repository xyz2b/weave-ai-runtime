# Installation

This guide covers the default published-package install path.
Use it when you want the shortest supported first run and you are not editing first-party WeaveRT packages from a repository checkout.

## Who is this for?

- New WeaveRT users who want the official starter-first adoption path.
- Teams writing onboarding steps against the published package set.

## Prerequisites

- Python 3.11+
- a shell that can create and activate a virtual environment
- access to a package index that serves the published WeaveRT packages

## Base install

Create a virtual environment and install the starter-first baseline in one command:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install weavert-starter weavert-testing
```

`weavert-starter` depends on `weavert-full`, so this one command already pulls the documented ordinary-workflow runtime baseline used by the official starter scaffolds.

If you are working from a local source checkout of this repository or you need editable first-party packages, use `install-from-source.md` instead.

If you need help choosing between `weavert`, `weavert-full`, scenario kits, or shared kits, read:

- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`

## Optional first-party packages

Add scenario or product-kit packages only when you need them:

- product kits: `weavert-kit-*`

Example:

```bash
python -m pip install weavert-kit-coding
```

## Verify the toolchain

```bash
weavert-starter list
```

You should see the official scaffold catalog, including `minimal-project`, `headless-workflow`, and `live-smoke`.

Next reading:

- `quickstart.md`
- `starter-scaffolds.md`
- `install-from-source.md`
- `../reference/runtime-config.md`

## Next step

- Run `quickstart.md` to prove the published install works end to end.
- Use `install-from-source.md` if you need editable first-party packages from this repository.

## See also

- `quickstart.md`
- `starter-scaffolds.md`
- `install-from-source.md`
- `../reference/public-package-catalog.md`
- `../guides/choose-package-combinations.md`
- `../guides/build-your-first-project.md`
- `../../examples/README.md`
