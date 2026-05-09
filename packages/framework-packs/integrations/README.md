# Framework-Pack Integrations

Integration-owned first-party add-ons now live under this workspace family.

## What this role family owns

- first-party integrations for providers, hosts, and runtime stores
- packages that bind the runtime to concrete external systems without becoming the app-owned host

## Concrete packages

- `openai/`: `weavert-openai` via the `weavert_openai` import root
- `hosts-reference/`: `weavert-hosts-reference` via the `weavert_hosts_reference` import root
- `stores-file/`: `weavert-stores-file` via the `weavert_stores_file` import root

## Ownership rule

- Put reusable first-party integration packages here.
- Keep final app-owned host wiring outside this family.

## See also

- `../README.md`
- `openai/README.md`
- `hosts-reference/README.md`
- `stores-file/README.md`
- `../../../docs/guides/integrate-openai.md`
