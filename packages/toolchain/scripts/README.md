# Toolchain Scripts

This package root owns repository support scripts. It is a workspace-owned maintainer utility root, not a public PyPI release target.

## What this package owns

- repository support scripts used by maintainers and validation workflows
- developer-side utilities that should not appear as runtime-selected packages
- maintainer-only support utilities that stay repository-bound even though they keep package-local metadata

## Publication boundary

- local install name: `weavert-toolchain-scripts`
- public PyPI scope: outside the public release train
- runtime activation: none

## Canonical script and module surfaces

- `packages/toolchain/scripts/check_workspace_layout.py`
- `packages/toolchain/scripts/openai_responses_live_smoke.py`
- `packages/toolchain/scripts/publish_workspace_packages.py`
- `python -m check_workspace_layout`
- `python -m openai_responses_live_smoke`
- `python -m publish_workspace_packages`

## Documented usage paths

From a repository checkout:

```bash
python3 packages/toolchain/scripts/check_workspace_layout.py
OPENAI_API_KEY=... python3 packages/toolchain/scripts/openai_responses_live_smoke.py
python3 packages/toolchain/scripts/publish_workspace_packages.py list
```

From a local maintainer install rooted in this repository checkout:

```bash
python -m pip install -e packages/framework-core \
  -e packages/framework-packs/integrations/openai \
  -e packages/toolchain/scripts
python -m check_workspace_layout
python -c "import check_workspace_layout, openai_responses_live_smoke"
python -m publish_workspace_packages build-check --wave 1
```

Use `OPENAI_API_KEY=... python -m openai_responses_live_smoke` only when you want the live OpenAI validation through that local install path.
Use `python -m publish_workspace_packages` when you want the documented public package wave orchestration for TestPyPI or PyPI uploads from a maintainer environment.
The matching GitHub Actions workflow lives at `.github/workflows/publish-public-packages.yml` and is the workflow filename maintainers must register with PyPI and TestPyPI Trusted Publishers.

## See also

- `../README.md`
- `../../../docs/maintainers/repository-layout.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/guides/integrate-openai.md`
