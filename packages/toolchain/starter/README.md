# Starter Toolchain Package

Canonical import root: `weavert_starter`

## What this package owns

- the developer-facing adoption-path starter scaffold catalog
- the `weavert-starter` CLI entrypoint

## Canonical names

- install name: `weavert-starter`
- import root: `weavert_starter`
- runtime activation: none

This package stays outside runtime package selection and is reached through the `weavert-starter` CLI or direct imports.

## Published quick install

```bash
python -m pip install weavert-starter weavert-testing
```

`weavert-starter` depends on `weavert-full`, so the published starter path already installs the documented ordinary-workflow runtime baseline used by the official starter scaffolds.

## See also

- `../README.md`
- `../../../docs/getting-started/starter-scaffolds.md`
- `../../../docs/getting-started/quickstart.md`
