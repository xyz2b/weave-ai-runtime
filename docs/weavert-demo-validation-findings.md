# Demo Validation Findings

This ledger keeps the current follow-up items exposed while authoring the user-centric runtime examples.
It is repo-owned validation evidence, not an implied roadmap commitment.

## Entry template

- demo: `<demo module or short demo name>`
- observed issue: `<the framework gap, confusing contract, or missing helper surfaced while building the demo>`
- user impact: `<why an adopter notices this gap while validating the seam>`
- suggested follow-up area: `<the runtime surface, helper, or docs area that likely needs follow-up>`
- status: `<open | documented | follow-up landed>`

## Current entries

### guarded_tool_demo

- demo: `guarded_tool_demo`
- observed issue: The repo exposes all the pieces for schema validation plus permission presets, but there is not yet one small helper pattern that bundles the three most common guarded-tool checks into a starter example.
- user impact: Tool authors still need to combine `ToolExecutionSemantics`, `check_permissions`, and a permission preset by hand before they can answer a simple "what happens when this is denied?" question.
- suggested follow-up area: Tool authoring docs and demo helpers for guarded permission patterns.
- status: documented

### scoped_agent_delegation_demo

- demo: `scoped_agent_delegation_demo`
- observed issue: Child-agent summaries are easy to project after the run, but the most direct proof of tool-pool narrowing still lives in request-time turn context rather than a first-class runtime summary field.
- user impact: Adopters can confirm that delegation worked, yet they still have to inspect request context or tests to prove exactly which tools remained visible to the child.
- suggested follow-up area: Child-run summary payloads and delegation diagnostics surfaces.
- status: follow-up landed

### inline_vs_fork_skill_demo

- demo: `inline_vs_fork_skill_demo`
- observed issue: Inline skills surface their result as injected system messages, while fork skills surface theirs through child summaries; the contrast is stable, but not obvious until both modes are shown side by side.
- user impact: Skill authors can pick the wrong execution mode if they only read one contract surface and miss how differently the outputs are observed.
- suggested follow-up area: Skill authoring docs and execution-mode comparison guidance.
- status: documented

### host_registered_hook_demo

- demo: `host_registered_hook_demo`
- observed issue: Host-side hook registration is stable, but the public docs do not yet foreground that host registrations default to session-template materialization and appear internally as `host_api` inventory entries.
- user impact: Product embedders can register hooks successfully, yet still have to cross-read tests to understand why the hook is pending first and active only after a session exists.
- suggested follow-up area: Host integration docs for hook materialization and inventory terminology.
- status: documented

### minimal_host_bound_demo

- demo: `minimal_host_bound_demo`
- observed issue: The smallest `bind_host()` path is compact, but adopters still need to know when to use `bound.run_prompt(...)`, helper-owned `bound.run_prompt_report(...)`, or caller-owned `bound.create_session(...) + bound.run_prompt_report_in_session(...)`, and when explicit shutdown remains their responsibility.
- user impact: A first integration can appear to work while still leaving host lifecycle or cleanup questions unresolved.
- suggested follow-up area: Host-bound quickstart guidance and lifecycle examples.
- status: documented

### stream_report_session_demo

- demo: `stream_report_session_demo`
- observed issue: Helper-owned and caller-owned report helpers share most behavior, so the ownership difference is easy to miss until a demo proves which path keeps the session open for reuse.
- user impact: Runtime adopters can accidentally choose a helper-owned path when they actually need a reusable caller-owned session.
- suggested follow-up area: Runtime helper docs around report ownership and session reuse.
- status: documented

### assembly_diagnostics_demo

- demo: `assembly_diagnostics_demo`
- observed issue: Assembly preset provenance, visible invocations, and route preflight diagnostics are all stable, but they currently live behind separate queries that users have to assemble mentally.
- user impact: A user validating runtime assembly posture can answer the question, but only after hopping across multiple APIs.
- suggested follow-up area: Higher-level assembly diagnostics helpers or consolidated documentation.
- status: follow-up landed

### durable_resume_demo

- demo: `durable_resume_demo`
- observed issue: Durable resume works on the full distribution, but the minimum proof still requires a re-assembly plus explicit `resume()` call that is more procedural than the lighter-weight examples.
- user impact: Adopters can validate persistence, yet they may not immediately understand which distribution and resume steps are required for the guarantee they want.
- suggested follow-up area: Durable-session docs and preset guidance for persistence expectations.
- status: documented
