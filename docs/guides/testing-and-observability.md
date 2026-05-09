# Testing and Observability

## Who is this for?

Users who want confidence that a runtime extension or workflow works before adding more surface area.

## Prerequisites

- a working project or example run
- willingness to validate one seam at a time

## The recommended validation ladder

Start narrow, then widen the scope only when the previous layer is stable:

1. seam basics
2. user-centric validation
3. semantic demos
4. project workflows
5. live smoke
6. advanced host-bound apps

The runnable index for this ladder lives in `../../examples/README.md`.

## Why deterministic and offline checks come first

Offline validation is usually better at answering framework questions such as:

- was the tool discovered?
- did permission denial behave correctly?
- did helper-owned versus caller-owned session behavior match expectations?
- was a package admitted or actually activated?

Live validation is useful later, but it adds credential, provider, and open-ended model variability.

## Runtime-owned helper surfaces worth using

Prefer runtime-owned helper surfaces over scraping raw transcript content by hand when you are answering common questions.
Useful helpers include:

- `final_assistant_text(...)`
- `latest_tool_outcome(...)`
- `latest_skill_outcome(...)`
- `terminal_failure(...)`
- `child_summary(...)`

These helpers let you ask common post-run questions without turning every workflow check into custom transcript parsing.

## Workflow observability

The shared workflow observability model gives you one runtime-owned view of workflow state across turn streams, child-run results, host events, and workflow reports.
Useful concepts include:

- lifecycle status such as `running`, `completed`, `blocked`, or `failed`
- outcome such as `succeeded`, `degraded`, or `failed`
- diagnostic severity such as `info`, `advisory`, or `blocking`

If you need low-level truth, keep using raw turn streams and durable records.
If you need one stable high-level answer about workflow health, use the shared model.

## Expected result

You can answer questions like:

- did the right tool run?
- who owned the session lifecycle?
- was durable state written?
- was a package merely admitted or actually active?
- was a route failure a credential issue or a runtime issue?

## Practical commands

```bash
.venv/bin/python -m pytest tests/test_runtime_extension_demos.py
python3 -B -m examples.tools.guarded_tool_demo
python3 -B -m examples.runtime.assembly_diagnostics_demo
python3 -B -m examples.projects.coding_workflow_demo
```

## Next step

- Return to the guide that changed your runtime seam and rerun its focused validation path.
- Use `../reference/workflow-observability.md` when you need the stable field-level observability contract.
- Read `../maintainers/validation-findings.md` if you are curating repo-level validation evidence.

## See also

- `../../examples/README.md`
- `register-hooks.md`
- `../deep-dives/weavert-workflow-observability.md`
- `../reference/workflow-observability.md`
- `../maintainers/validation-findings.md`
