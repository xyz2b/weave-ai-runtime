# Integrate OpenAI

## Who is this for?

Users who already have an offline or deterministic WeaveRT workflow and now want to exercise the bundled live route.

## Prerequisites

- a working runtime baseline
- `packages/framework-packs/integrations/openai` installed in the environment
- `OPENAI_API_KEY` available

Recommended install path:

```bash
python -m pip install -e packages/framework-packs/integrations/openai
```

## The recommended live posture

Start with the live preset instead of assembling ad hoc route state yourself.
The usual entrypoint is:

- `RuntimeConfig.for_headless_live(project_root)`

That keeps the route choice explicit and makes `preflight_default_model_route()` the first diagnostic step.

## Steps

1. Export credentials:

```bash
export OPENAI_API_KEY=your-key
export OPENAI_MODEL=gpt-4.1-mini
```

2. Assemble the runtime with the live preset:

```python
import asyncio
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig.for_headless_live(Path.cwd()))
preflight = asyncio.run(runtime.preflight_default_model_route())
print(preflight.to_dict())
```

3. Only run real prompts after preflight is ready.

## What the bundled OpenAI path does for you

The bundled route is more than a plain text adapter.
It supports:

- live provider-backed prompts
- tool-capable execution via strict function tools
- structured failure classes such as `auth_error`, `context_limit`, `output_limit`, or `tool_schema_error`
- runtime-owned continuation instead of provider-owned state authority

## Tool schema rules to keep in mind

If a tool should run through the bundled OpenAI route, prefer:

- explicit object schemas
- explicit array item schemas
- small, closed shapes where possible

Avoid relying on schema-valued `additionalProperties` for the bundled strict export path.

## Expected result

- preflight reports `ready: true`
- the runtime keeps route failures explicit instead of silently falling back
- tool-capable live execution uses the bundled OpenAI path

## Practical validation path

Use one of these next:

- `python3 -B -m examples.projects.coding_workflow_demo --live`
- `python3 packages/toolchain/scripts/openai_responses_live_smoke.py`

## Common failure interpretation

- missing `OPENAI_API_KEY` -> preflight or first run reports `missing_env` or `auth_error`
- tool schema too dynamic -> `tool_schema_error`
- provider overload or rate limit -> structured provider overload diagnostics

## Next step

- Run `python3 -B -m examples.projects.coding_workflow_demo --live` after preflight succeeds.
- Read `testing-and-observability.md` if you want a cleaner checklist for route diagnostics and failure interpretation.

## See also

- `../deep-dives/weavert-openai-responses-adapter.md`
- `../../examples/README.md`
- `../reference/runtime-config.md`
