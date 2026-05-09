# WeaveRT Runtime Validation Review

> Documentation note: This file remains a maintainer-facing deep-dive review. Start with `docs/maintainers/validation-findings.md` for the index entrypoint.

This maintainer reference keeps the longer runtime review: what the runnable demos have already validated, which adoption or usability gaps appeared historically, and which of those gaps are now closed.

Primary docs path:

- Examples index -> `examples/README.md`
- Docs home -> `docs/README.md`
- Maintainer validation index -> `docs/maintainers/validation-findings.md`

Use this page when you already know the main reading path and want one long-form review of what the demos proved, which gaps once existed, and which ones are now closed.

This file still intentionally does not try to cover user-specific business workflow design, product UX/UI, domain-specific definitions, or one app's product strategy.

> 2026-05-04 review update:
> This file originally tracked runtime usability gaps and roadmap follow-up. The related changes listed there are now complete, so sections 3-7 are framed as review conclusions instead of currently missing capabilities.

## 1. Scope

### 1.1 What counts as runtime-layer capability

This file treats the following as runtime-framework capability:

- definition discovery and runtime assembly
- tool / agent / skill execution and composition
- hook registration and lifecycle injection
- package protocol attachment
- model route / provider switching
- session / turn lifecycle management
- control-plane boundaries such as permission, elicitation, and host integration
- outputs, errors, state, observability, and testing support

### 1.2 What does not count as a runtime-layer gap

The following should not be treated as runtime defects:

- whether a user wants to build an AI coding app, support assistant, operations assistant, or another product
- business workflow details that belong to the product team
- the interaction shell or product form chosen by the adopter
- domain knowledge embedded in the adopter's own tool / agent / skill layer

These are responsibilities the product team using the framework should own, not work the runtime is supposed to replace.

## 2. Runtime capabilities already validated by the current demos

## 2.1 Layered conclusion

| Demo layer | Representative demos | Main runtime capability under validation | Conclusion |
| --- | --- | --- | --- |
| Seam basics | `examples.tools.file_backed_tool_demo`, `examples.agents.file_backed_agent_demo`, `examples.skills.file_backed_skill_demo` | `.weavert/` discovery, definition assembly, single tool / agent / skill execution | Validated |
| Hook demos | `examples.hooks.session_register_hook_demo`, `examples.hooks.runtime_config_hook_demo`, `examples.skills.inline_skill_hook_demo` | public hook registration, skill hooks, runtime-default hooks | Validated |
| Package demos | `examples.packages.provider_only_package_demo`, `examples.packages.general_package_demo`, `examples.packages.package_activation_demo` | manifest admission, requested activation, capability binding, context contributors, invocation providers | Validated |
| Project demos | `examples.projects.release_workflow_demo`, `examples.projects.coding_workflow_demo` | composition across multiple public seams and whether the ordinary extension path is enough for a real workflow | Validated |
| Workflow-level live smoke | `examples.projects.coding_workflow_demo --live` | switching the same workflow onto a real provider without host or built-in replacement, plus formal preflight before execution | Validated via live run |
| Advanced integration sample | `examples.apps.code_assistant` | host binding, durable state, approvals, built-in replacement, task / job integration | Validated, but on the advanced path |

## 2.2 Runtime capabilities proven in practice

### A. User definition discovery and assembly are established

Current demos show:

- users can place capability definitions in `.weavert/tools/`, `.weavert/agents/`, and `.weavert/skills/`
- the runtime can discover and assemble those definitions without kernel edits
- for ordinary users, the main extension story is no longer "rewrite the runtime loop" but "author your own tool / agent / skill"

This directly supports the core framework goal: move adopters out of runtime internals and let them spend energy on business capability definitions.

### B. The tool / agent / skill execution plane composes cleanly

`coding_workflow_demo` proves not a one-off invocation but a full composition:

- `skill` constrains workflow order first
- `grep` performs inspection
- `edit` makes real file changes
- `bash` runs real local validation
- the `review-change` skill triggers a reviewer child agent
- the workflow returns a final summary

This shows the core execution plane is already strong enough for small real workflows, not just isolated examples.

### C. Skills are already a first-class workflow abstraction

Current demos validate all of the following:

- `inline` skill: injects workflow discipline inside the current turn
- `fork` skill: triggers child-agent or child-flow execution
- skill hooks: a skill is not just a prompt fragment; it can also carry lifecycle behavior

This means skills already function as reusable workflow packaging, not merely text templates.

### D. The hook system is a usable public extension surface

The demos prove all three paths in practice:

- `session.hooks.on_pre_tool_use(...)`
- `RuntimeConfig(hooks=...)`
- skill frontmatter `hooks`

In other words, the runtime already exposes lifecycle instrumentation as a public extension capability instead of asking adopters to patch the main loop.

### E. The package protocol is established

The package demos prove that all of the following are real, not just conceptual:

- external manifest admission
- explicit activation through `requested_packages`
- package-owned capability
- package-owned context contributor
- invocation provider attachment

This shows the package boundary is already a usable runtime protocol-attachment surface, not merely an internal repository mechanism.

### F. Workflow and provider are mostly decoupled

The offline/live split in `coding_workflow_demo` proves that:

- the same fixture
- the same workflow
- the same success criteria

you can switch only the model route without rewriting the workflow definition.

For ordinary users, this means "make the workflow work first, then switch to a real provider" is already a valid runtime adoption path.

### G. Host is a real boundary, but not a required path for every user

The current demos also prove one more important point:

- ordinary workflows do not need `bind_host()`
- the advanced path begins only when a user needs host-owned UX, approvals, durable state, or built-in replacement

That matches the posture of a general AI runtime framework very well: host is a formal extension boundary, but it does not force every user to start with host integration.

## 3. Review of the original usability gaps

The following sections revisit the runtime-layer gaps originally listed in this file. The point is not that the original diagnosis was wrong, but that most of those gaps are now closed and should no longer be treated as current blockers.

### 3.1 First-class official workflow test kit: closed

Original concern:

- deterministic workflow validation depended on `examples/_shared/*`
- users had to copy scripted models, temporary workspaces, and fixture runners themselves

Current status:

- the runtime now provides an official `weavert_testing` namespace
- it includes `ScriptedModelClient`
- it includes `copied_fixture_workspace(...)` / `temporary_workspace(...)`
- it includes `run_workflow_test(...)`
- it includes tool / skill / child-run assertions
- `WorkflowTestReport` wraps the canonical `WorkflowRunReport` directly

As a result, "how do I test a runtime workflow?" has moved from demo-private technique into a formal public capability.
`examples/_shared/scripted_model.py` is now mostly a compatibility re-export rather than a primary user path.

### 3.2 Higher-level session / workflow lifecycle helpers: largely closed

Original concern:

- headless project demos still required hand-written session lifecycle glue
- ordinary users should not have to manage `create_session -> enqueue -> stream -> close` manually

Current status:

- the runtime now provides `run_prompt_report()`
- it also provides `run_prompt_report_in_session()`
- it now provides `stream_prompt_report()` / `stream_prompt_report_in_session()` as well
- the host-bound path now also provides `bound.run_prompt_report()` / `bound.run_prompt_report_in_session()`
- `WorkflowRunReport` already includes terminal, final status, and finalization diagnostics
- ordinary headless callers no longer need to assemble terminal collection, helper-owned close, or "stream while also producing a canonical report" lifecycle glue manually
- host adopters no longer need to mix `bound.*` and `RuntimeAssembly` just to get the canonical report

Review conclusion:

- for ordinary headless workflow runners, this gap is now fully closed
- that includes raw streaming, one-shot reports, helper-owned streaming reports, and caller-owned streaming reports
- so it no longer belongs in the active runtime findings ledger as an open gap

### 3.3 Non-interactive permission presets: closed

Original concern:

- headless / CI / smoke scenarios lacked official presets
- users should not keep rewriting allow-all stubs

Current status:

- there is now an official `AllowAllPermissionService`
- there is now a `DenyAllPermissionService`
- there is now a `ReadOnlyPermissionService`
- there is now a `SelectiveAutoApprovePermissionService`
- and the stack now supports upgrading from presets into composed-policy paths

So this item has moved from "gap" to "formal control-plane capability."

### 3.4 Typed result projection and query helpers: closed

Original concern:

- `coding_workflow_demo` required manual transcript / block scanning
- workflow acceptance logic should not keep rewriting message scanning

Current status:

- `latest_tool_outcome(...)` now exists
- `latest_skill_outcome(...)` now exists
- `final_assistant_text(...)` now exists
- `terminal_failure(...)` now exists
- `child_summary(...)` now exists
- these helpers work with both raw messages and `WorkflowRunReport`

So this item is not only closed, but already documented in user and integration guides instead of remaining an internal-only tool.

### 3.5 Lightweight hook authoring helpers: closed

Original concern:

- simple hook scenarios still had too much ceremony
- matcher shortcuts and common effect helpers were missing

Current status:

- callback-oriented hook helpers now exist
- `match_tool(...)` / `match_tool_pattern(...)` now exist
- `rewrite_input(...)` / `block_execution(...)` / `respond_to_elicitation(...)` now exist
- helper-generated requests still go through the same validation path rather than a helper-only bypass

So this item has improved from "the low-level protocol exists but is heavy to write" into "simple cases now have an official lightweight entrypoint."

### 3.6 Lightweight package builders / helpers: closed

Original concern:

- the package protocol existed, but ordinary authoring still had too much ceremony
- capability-only, context-only, and provider-only patterns should have lightweight builders

Current status:

- `build_capability_only_package_manifest()` now exists
- `build_context_contributor_only_package_manifest()` now exists
- `build_provider_only_invocation_package_manifest()` now exists
- the output is still an ordinary manifest-backed package, not a second protocol

So this item is also closed.

### 3.7 Assembly ergonomics: mainline closed

Original concern:

- users had to understand distribution, built-ins, discovery, routes, and package activation all at once
- there was no clear default starting point for ordinary adopters

Current status:

- `RuntimeConfig.for_ordinary_workflow(...)` now exists
- `RuntimeConfig.for_headless_live(...)` now exists
- `RuntimeConfig.for_host_bound(...)` now exists
- preset provenance is published into runtime metadata
- an official starter-scaffold generation path now exists as well, lowering adoption cost further

So the main assembly path is no longer "there is no recommended entrypoint" but "there is a recommended entrypoint, and the remaining work is ongoing convergence in docs and examples."

### 3.8 Live/provider preflight: closed

Original concern:

- the live path should surface env / auth / route problems before a full run
- preflight should be a first-class runtime capability

Current status:

- `preflight_model_route(...)` now exists
- `preflight_default_model_route()` now exists
- both return structured readiness reports
- starter-scaffold and live-smoke docs already treat preflight as the primary path

So this gap is closed.

## 4. Remaining runtime-level items still worth tracking

After this implementation round, most of the originally listed "missing capabilities" no longer hold. What remains is better treated as finish-up or ongoing optimization work.

### 4.1 Report-oriented streaming companion: closed

The repository now has:

- `stream_prompt()`: the raw streaming surface
- `run_prompt_report()`: the report-oriented one-shot surface
- `run_prompt_report_in_session()`: the report helper for caller-owned sessions
- `stream_prompt_report()`: helper-owned streaming plus canonical report finalization
- `stream_prompt_report_in_session()`: caller-owned streaming plus canonical report finalization

This means the earlier gap around "stream while preserving canonical run-report and finalization semantics" is now closed.
If more work happens here later, it is more likely to be docs and adoption-path convergence than a new runtime public surface.

### 4.2 Internal demo/private wrappers still leave cleanup room

The repository still keeps a small amount of `examples/_shared/*` wrapper code, for example:

- `run_async(...)`
- `demo_workspace(...)`
- compatibility exports for some demos

This looks more like repository cleanup work than a missing runtime capability for end users.
From a user perspective, the public replacement surfaces already exist, and future work can keep reducing the visibility of demo-private compatibility wrappers.

### 4.3 This document should stop acting like the current-gap backlog

Because most of the large roadmap items are now complete, keeping Sections 3-7 framed as a pending-implementation list would mislead readers.
If a new runtime gap appears later, the better pattern is to:

- open a fresh findings or review document
- or record it directly in a new change proposal

rather than continuing to reuse this document as an outdated backlog.

## 5. What should not be pushed back into the runtime

To avoid scope drift, the following should stay out of the runtime layer:

- the AI-coding business workflow itself
- a user's product shell, web UI, or IDE UX
- domain-specific reviewer, planner, or verifier prompts
- a user's business-specific tool, agent, or skill semantics
- product-specific workflow ledgers, task panels, or business approval rules

These all belong to the product layer that users should build on top of the runtime.

The runtime should instead keep owning:

- low-level execution and orchestration
- formal extension boundaries
- testing and observability support
- general capabilities around providers, sessions, permissions, hooks, and packages

## 6. Overall conclusion

Based on the current demos, user docs, public surfaces, and targeted regression coverage, the more accurate runtime-level conclusion is:

- **What now holds**: WeaveRT has not only proven that seams such as tools, agents, skills, hooks, packages, and hosts work; it has also turned workflow testing, headless lifecycle helpers, permission presets, result projection, assembly presets, preflight, starter scaffolds, and workflow observability into formal public capabilities.
- **What no longer holds**: This document originally treated the test kit, lifecycle helpers, permission presets, result-query helpers, hook or package helpers, assembly presets, and preflight as current missing items. As of the repository state on May 4, 2026, that framing is no longer accurate.
- **What is more accurate now**: The main runtime work has shifted from filling basic gaps to converging the adoption path, reducing repository-internal compatibility wrappers, and adding targeted improvements only when real demand appears.

## 7. Completed roadmap recap

The runtime infrastructure items that this document originally listed on the roadmap now mostly have concrete implementations.

### 7.1 Infrastructure that has been filled in

- official workflow test kit
- high-level headless workflow runner and report helpers
- non-interactive permission presets
- live provider preflight
- typed result projection / query helpers
- lightweight hook authoring helpers
- lightweight package builder family
- runtime assembly presets
- unified workflow observability model
- runtime starter scaffolds
- composable permission policy framework

### 7.2 What is more worth focusing on next

If runtime work continues, the better focus areas are:

- whether to keep cleaning up the remaining demo-private compatibility wrappers in the repository
- whether to keep converging adoption docs, demos, and starter scaffolds toward fewer, more stable recommended paths

In other words, the next phase looks more like convergence and polish than another round of filling obvious foundational capability gaps.
