## 1. Package-Only Provider Contract

- [x] 1.1 Define the lightweight provider-only runtime package pattern, including the ordinary minimal manifest shape, baseline dependency expectations, and ordering behavior.
- [x] 1.2 Update package protocol and registration docs to treat package contributions as the only normative custom invocation-provider path.
- [x] 1.3 Provide a provider-only package example or template that embedders, docs, and tests can share.

## 2. Runtime Assembly Migration

- [x] 2.1 Remove `RuntimeConfig.extra_invocation_providers` from canonical runtime assembly logic.
- [x] 2.2 Keep the built-in skill invocation-provider baseline and register only package-contributed providers after it.
- [x] 2.3 Update invocation-provider provenance metadata to remove the config-owned tier entirely.

## 3. Registry and Metadata Hardening

- [x] 3.1 Update invocation-registry diagnostics and registration metadata to reflect the package-only provider model.
- [x] 3.2 Update runtime assembly metadata, protocol catalog metadata, and structured conformance findings, using the shared protocol-only finding schema, to remove the config-bypass path.

## 4. Verification and Migration Guidance

- [x] 4.1 Add conformance and regression coverage for provider ordering, provenance, and package-only registration.
- [x] 4.2 Update migration docs with a direct conversion path from config-supplied providers to provider-only runtime packages.
- [x] 4.3 Add distribution-matrix coverage proving that provider-only packages assemble consistently across `runtime-core`, `runtime-default`, and `runtime-full`.
