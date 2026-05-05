## 1. Shared coding package surfaces

- [x] 1.1 Add a shared git package manifest with read-mostly git inspection tools and package metadata.
- [x] 1.2 Add a shared workspace-intelligence package manifest with symbol, reference, and test-target discovery surfaces.
- [x] 1.3 Add validation that proves both shared packages can be admitted and selected through the runtime package contract.

## 2. Coding scenario workflows

- [x] 2.1 Add official coding scenario-pack agents for planning, review, and verification while keeping generic first-party planning agents distinct.
- [x] 2.2 Add official coding scenario-pack skills for the coding loop, review, verification, task discipline, and repo onboarding.
- [x] 2.3 Update the coding scenario-pack contract to publish its shared-package dependencies and flat expected tool, agent, and skill inventories.

## 3. Demo and validation alignment

- [x] 3.1 Rewire the code-assistant demo to consume the official coding package stack while preserving app-owned shell behavior.
- [x] 3.2 Add tests that verify the coding scenario-pack surfaces are visible without relying on demo-local fallback definitions and that coding-specific agents remain distinguishable from generic first-party agents.
- [x] 3.3 Update user-facing guidance so coding adopters know which roles live in the scenario pack, which generic agents remain first-party, which tools live in shared packages, and which behaviors remain app-owned.
- [x] 3.4 Add tests or guidance that prove the coding workflow and shared-tool packages are not part of default distribution baselines and must be admitted explicitly through external or optional package-selection paths.
