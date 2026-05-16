## 1. Change Sequencing

- [ ] 1.1 Keep `expand-web-capability-profiles` as the baseline change for `web-research-capability-profiles` and archive that baseline before archiving this follow-up delta.

## 2. Shared Core Policy Hardening

- [x] 2.1 Update `packages/framework-packs/capabilities/web-research/src/weavert_web_research/core.py` so redirect handling validates redirect targets against caller allowed-domain and blocked-domain policy rather than only public-host safety.
- [x] 2.2 Revalidate the final resolved fetch URL against caller domain policy before constructing inspected-page results, handles, and browser handoff metadata.
- [x] 2.3 Add an additive top-level `freshness_scope` payload for web research results, omit it when no freshness constraint was requested, and have the current backend return `{"requested_days": <n>, "status": "unsupported"}` when `freshness_days` is requested.
- [x] 2.4 Introduce shared validation helpers or equivalent centralized checks for deterministic fetch and page-local find failures such as missing usable URLs, policy-invalid URLs, and structurally incomplete inspected-page payloads.

## 3. Adapter And Compatibility Alignment

- [x] 3.1 Update chat web adapter validation and execution in `packages/product-kits/common/web/` to consume the hardened shared-core redirect, top-level `freshness_scope`, and deterministic validation behavior.
- [x] 3.2 Update coding web adapter validation and execution in `packages/product-kits/common/web-research/` to preserve domain-scope, explicit top-level `freshness_scope`, and validator or executor parity.
- [x] 3.3 Update built-in devtools compatibility wrappers in `packages/framework-packs/workflows/devtools/` so `web_fetch` validation honors caller domain constraints and built-in web results project additive top-level `freshness_scope` metadata without diverging from the shared core.

## 4. Regression Coverage

- [x] 4.1 Add shared-core or adapter-level tests that prove allowed-domain requests are rejected when redirects land outside the caller scope or on blocked domains.
- [x] 4.2 Add tests that prove `freshness_days` no longer behaves as a silent no-op and instead surfaces the explicit top-level `freshness_scope={"requested_days": <n>, "status": "unsupported"}` outcome expected for the current backend.
- [x] 4.3 Add validator or executor parity tests for chat, coding, and built-in web surfaces so deterministically invalid fetch and page-local find inputs are rejected during validation rather than failing later at execution time.
