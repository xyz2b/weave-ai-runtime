# Local OS Common Kit

Canonical import root: `weavert_kit_common_local_os`

## What this package owns

- reusable local-OS bridge surfaces
- shared local-device tooling used by local-assistant product-kit composition

## Canonical names

- install name: `weavert-kit-common-local-os`
- import root: `weavert_kit_common_local_os`
- runtime activation: `weavert-bridge-local-os`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package for generic local-machine surfaces such as files, clipboard, notifications, and processes.
- Do not choose it when you need structured calendar, contacts, reminders, or tasks. That belongs to `weavert-kit-common-pim`.
- Do not choose it when the target surface is a browser tab or page. That belongs to `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../local-assistant/README.md`
- `../../../../docs/concepts/hosts-permissions-memory.md`
