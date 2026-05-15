# Runtime Distributions

This family root indexes installable distribution bundles that compose multiple first-party runtime packages into one documented baseline.

## What this family owns

- install-time bundle packages such as `weavert-full`
- published distribution identities that match the documented runtime distribution names

## Public release scope

- Concrete packages under this family are public PyPI projects.
- These packages do not add a new import root; they install dependency bundles for documented runtime baselines.
- This family root remains an index only; it is not itself published.

## Concrete packages

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `full/` | `weavert-full` | none | none | Installable full first-party baseline |

## See also

- `../README.md`
- `../../docs/maintainers/pypi-release-readiness.md`
- `../../docs/getting-started/quickstart.md`
