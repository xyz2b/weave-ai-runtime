# PIM Common Kit

Canonical import root: `weavert_kit_common_pim`

## What this package owns

- reusable calendar, contacts, reminder, and task bridge surfaces
- shared PIM tooling used by local-assistant product-kit composition

## Canonical names

- install name: `weavert-kit-common-pim`
- import root: `weavert_kit_common_pim`
- runtime activation: `weavert-bridge-pim`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package for structured personal-information surfaces such as calendars, contacts, reminders, and tasks.
- Do not choose it for generic file, clipboard, notification, or process access. That belongs to `weavert-kit-common-local-os`.
- Do not choose it for browser tabs or page interaction. That belongs to `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../local-assistant/README.md`
- `../../../../docs/concepts/packages-and-scenario-packs.md`
