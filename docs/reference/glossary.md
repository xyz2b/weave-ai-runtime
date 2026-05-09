# Glossary

## Who is this for?

- Readers who already know the workflow and now need a stable lookup page.

## Prerequisites

- Read the matching guide or concept page first.
- Treat this page as a reference sheet, not the first-stop tutorial.

- runtime
  - the assembled execution framework that owns sessions, turns, and runtime services
- host
  - the app-facing integration surface that owns lifecycle and UX concerns
- tool
  - a structured executable capability
- agent
  - a named prompt-owned role
- skill
  - a reusable named workflow step
- package
  - a manifest-backed unit of runtime capability composition
- scenario pack
  - a product-profile package that groups workflow surfaces and guidance
- session
  - the continuity container for transcript and ingress handling
- turn
  - one execution cycle from admitted input to terminal result
- hook bus
  - the runtime phase-dispatch system for lifecycle hook registrations
- context contributor
  - a package-owned sidecar that contributes prompt, private, or diagnostics context before request assembly
- workflow observability
  - the shared runtime-owned model for workflow identity, lifecycle status, outcome, and diagnostics
- long-term memory
  - shared durable memory for preferences, conventions, topics, and other persistent notes
- agent namespace memory
  - durable memory scoped to one agent namespace
- session memory
  - continuity artifacts and summaries scoped to one session
- consolidation memory
  - slower background memory layer that merges useful session outcomes back into longer-lived memory
- transcript truth
  - the durable record of what happened in a session
- active context
  - the model-visible view projected for one turn

## Next step

- Go back to `../concepts/runtime-model.md` if you need the terms in the context of the main runtime story.
- Read `../concepts/tools-agents-skills.md` or `../concepts/packages-and-scenario-packs.md` when the vocabulary question is seam-specific.

## See also

- `../concepts/runtime-model.md`
- `../concepts/tools-agents-skills.md`
- `../concepts/packages-and-scenario-packs.md`
- `../README.md`
