# Toolchain Scripts

This package root owns repository support scripts that are intentionally developer-side utilities rather than runtime-selected packages.

## What this package owns

- repository support scripts used by maintainers and validation workflows
- developer-side utilities that should not appear as runtime-selected packages

## Canonical names

- install name: `weavert-toolchain-scripts`
- public import root: none; use the script paths directly

## Canonical script paths

- `packages/toolchain/scripts/check_workspace_layout.py`
- `packages/toolchain/scripts/openai_responses_live_smoke.py`

## See also

- `../README.md`
- `../../../docs/maintainers/repository-layout.md`
- `../../../docs/guides/integrate-openai.md`
