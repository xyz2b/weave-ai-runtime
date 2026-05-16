# Build Your First Project

## Who is this for?

Framework users who want their first real WeaveRT project, not just a demo run.

## Prerequisites

- Python 3.11+
- the install from `../getting-started/installation.md` or `../getting-started/install-from-source.md`
- a successful starter quickstart from `../getting-started/quickstart.md`

## Recommended baseline

Start from `minimal-project` unless you already know you need a headless workflow runner or a live-only smoke path.

```bash
weavert-starter generate minimal-project ./my-weavert-app
cd my-weavert-app
python -m pip install -e .
python app.py
```

## A good first project shape

```text
my-weavert-app/
|- app.py
|- pyproject.toml
`- .weavert/
   |- tools/
   |- agents/
   `- skills/
```

## Steps

1. Keep `app.py` small and assemble through `RuntimeConfig.for_ordinary_workflow(...)`
2. Add one project-local capability under `.weavert/`
3. Prefer a tool when you are adding execution logic
4. Add an agent only when you need a named role
5. Add a skill when you need a reusable workflow step
6. Validate the exact seam you changed with `../../examples/README.md`

## Expected result

You have a runnable project that:

- assembles through stable runtime surfaces
- discovers project-local definitions under `.weavert/`
- grows one tool, agent, or skill at a time
- does not need you to rewrite the runtime loop

## A practical growth path

- first: one local tool plus one local agent
- next: one reusable skill
- then: deterministic validation through `examples/README.md`
- later: live routing, package composition, or host binding when your needs justify them

## Next step

- Add a tool: `add-a-tool.md`
- Add an agent: `add-an-agent.md`
- Add a skill: `add-a-skill.md`
- Move to live routing: `integrate-openai.md`

## See also

- `../getting-started/starter-scaffolds.md`
- `../concepts/runtime-model.md`
- `../concepts/tools-agents-skills.md`
