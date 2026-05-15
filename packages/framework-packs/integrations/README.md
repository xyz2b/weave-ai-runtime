# Framework-Pack Integrations

Integration-owned first-party add-ons now live under this workspace family.

## What this role family owns

- first-party integrations for providers, hosts, and runtime stores
- packages that bind the runtime to concrete external systems without becoming the app-owned host

## Concrete packages

- `openai/`: install `weavert-openai`, import `weavert_openai`, runtime activation `weavert-openai`
- `hosts-reference/`: install `weavert-hosts-reference`, import `weavert_hosts_reference`, runtime activation `weavert-hosts-reference`
- `stores-file/`: install `weavert-stores-file`, import `weavert_stores_file`, runtime activation `weavert-stores-file`

## Exposure tier

- These are direct public integration add-ons rather than scenario-pack entrypoints.

## Ownership rule

- Put reusable first-party integration packages here.
- Keep final app-owned host wiring outside this family.

## See also

- `../README.md`
- `openai/README.md`
- `hosts-reference/README.md`
- `stores-file/README.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/guides/integrate-openai.md`
