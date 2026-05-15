# Quickstart

This is the default first run for a new WeaveRT user.
Use the starter first, then return to `examples/` for the validation path and deeper evaluation.

## Who is this for?

- Framework users who want the first runnable WeaveRT project path, not a deep architecture tour.

## Prerequisites

- Finish `installation.md` first.
- Skim `../introduction/what-is-weavert.md` if you arrived here before reading the landing-page overview.

## Goal

Generate a minimal project, run it once, and confirm the runtime baseline works before you add custom logic.

## Why this path comes first

WeaveRT recommends a starter-first journey:

1. generate a small project with canonical `weavert` imports
2. confirm `.weavert/` discovery and one runtime turn work locally
3. extend one seam at a time
4. only then move into examples, live routes, host binding, or scenario packs

`examples/` is the validation path for the repository.
It is useful after the starter works, but it is not the default copy-paste adoption path.

## Step 1: Install the local baseline and toolchain

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  -e packages/framework-core \
  -e packages/framework-packs/capabilities/memory \
  -e packages/framework-packs/capabilities/team \
  -e packages/framework-packs/mechanisms/compaction \
  -e packages/framework-packs/mechanisms/isolation \
  -e packages/framework-packs/integrations/openai \
  -e packages/framework-packs/integrations/hosts-reference \
  -e packages/framework-packs/integrations/stores-file \
  -e packages/framework-packs/workflows/builtin-workflows \
  -e packages/framework-packs/workflows/planning \
  -e packages/framework-packs/workflows/devtools \
  -e packages/distributions/full \
  -e packages/toolchain/starter \
  -e packages/toolchain/testing
```

If you are installing from published packages instead of editable local roots, the matching one-command baseline is:

```bash
python -m pip install weavert-starter weavert-testing
```

`weavert-starter` depends on `weavert-full`, so the published starter path already matches the `ordinary-workflow` preset used by the generated project.

Optional scenario kits can be installed later when you need them.
For example, coding-oriented product defaults live under `packages/product-kits/coding`.

## Step 2: Generate the starter project

```bash
weavert-starter generate minimal-project ./my-weavert-app
```

The generated project gives you:

- `RuntimeConfig.for_ordinary_workflow(...)` as the baseline preset
- project-local `.weavert/agents/` and `.weavert/tools/`
- a deterministic `ScriptedModelClient` baseline
- a minimal `app.py` entrypoint you can keep small as the project grows

## Step 3: Inspect the generated shape

```text
my-weavert-app/
|- app.py
|- pyproject.toml
|- README.md
`- .weavert/
   |- agents/
   |- tools/
   `- skills/
```

The starter is intentionally small.
Your first project should grow by adding one tool, agent, or skill at a time under `.weavert/`, not by rewriting the runtime loop.

## Step 4: Run the generated project

```bash
cd my-weavert-app
python -m pip install -e .
python app.py
```

## Expected output

Look for these anchors:

- `preset: ordinary-workflow`
- `workspace root: .weavert`
- `assistant: The scaffold is ready...`
- `status: ok`

## What this proves

- the runtime assembled successfully through `RuntimeConfig.for_ordinary_workflow(...)`
- project-local `.weavert/` discovery is active
- a file-backed tool and agent can participate in one runtime turn
- the deterministic testing path works without live model credentials

## The four stable surfaces you will touch next

Once the starter works, most users build on four surfaces:

- `RuntimeConfig`
  - assembly choices such as discovery sources, model routes, packages, and stores
- `RuntimeAssembly`
  - runtime entrypoints such as prompt helpers, sessions, and inspection
- `DefinitionSourcePaths`
  - how tools, agents, and skills are discovered
- `BoundHostRuntime`
  - only when you need host-owned lifecycle, approvals, or UI integration

## Next step

1. Add your own tool under `.weavert/tools/`
2. Add an agent or skill under `.weavert/agents/` or `.weavert/skills/`
3. Read `../guides/build-your-first-project.md`
4. Use `../../examples/README.md` to validate the exact seam you changed
5. Move to `../guides/integrate-openai.md` only after the offline baseline is stable

## See also

- `installation.md`
- `starter-scaffolds.md`
- `../concepts/runtime-model.md`
- `../../examples/README.md`
