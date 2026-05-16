# Starter Scaffolds

If your goal is to create your own WeaveRT project, start here before copying from `examples/`.

The starter catalog exists to provide:

- an official, minimal, runnable starting point
- canonical `weavert` public imports
- the canonical `.weavert/` workspace layout
- a clear separation between the adoption path and the validation path

## Who is this for?

- Users choosing the official starter scaffold that best matches their adoption path.

## Prerequisites

- Finish `installation.md` first.
- If you are working from a repository checkout, use `install-from-source.md` instead.
- Read `quickstart.md` if you want the smallest runnable path before comparing scaffold shapes.

## Official generation path

```bash
weavert-starter list
weavert-starter generate minimal-project ./my-weavert-app
weavert-starter generate headless-workflow ./my-headless-runner
weavert-starter generate live-smoke ./my-live-smoke
```

If the destination already exists and you want to regenerate the scaffold, add `--force`.

## Which scaffold should I choose?

### `minimal-project`

Use this when:

- you are starting a normal WeaveRT project
- you want the smallest loop for project-local tool and agent discovery
- you want an offline baseline with no provider credentials

What it gives you:

- `RuntimeConfig.for_ordinary_workflow(...)`
- `.weavert/agents/` and `.weavert/tools/`
- `weavert_testing.ScriptedModelClient`
- a tiny `app.py` entrypoint

### `headless-workflow`

Use this when:

- you want a CI or scripted workflow runner
- you prefer report-oriented helpers over app-shell UX
- you want a deterministic workflow contract before live integration

What it gives you:

- `run_workflow_test(...)`
- `final_assistant_text(...)`
- `latest_tool_outcome(...)`
- `terminal_failure(...)`

### `live-smoke`

Use this when:

- you want a provider-backed readiness check
- you need route preflight before a richer integration
- you want live failures to stay explicit instead of falling back to scripted behavior

What it gives you:

- `RuntimeConfig.for_headless_live(...)`
- `preflight_default_model_route()`
- an explicit live-only entrypoint

## Starter vs examples

- starter scaffolds = adoption path
- examples = validation path

Use the starter when you want to begin your own project.
Use the examples when you want to prove a specific runtime seam or workflow boundary.

## Next step

1. Run the generated entrypoint once.
2. Add your own project-local definitions under `.weavert/`.
3. Validate the extension seam in `../../examples/README.md`.
4. Move into host binding or scenario packs only when you need them.

## See also

- `quickstart.md`
- `../guides/build-your-first-project.md`
- `../../examples/README.md`
