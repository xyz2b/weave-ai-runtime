from __future__ import annotations

import os
from pathlib import Path

from demos._shared.common import run_async, temporary_workspace

from weavert import SkillDefinition
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime


SKILL_NAME = "diagnostic-note"


def main() -> None:
    with temporary_workspace() as workspace:
        config = RuntimeConfig.for_headless_live(Path(workspace))
        config.builtins = BuiltinPackConfig(
            extra_skills=[
                SkillDefinition(
                    name=SKILL_NAME,
                    description="Surface one deterministic visible invocation.",
                    content="diagnostic note",
                )
            ]
        )
        preserved_api_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            runtime = assemble_runtime(config)
        finally:
            if preserved_api_key is not None:
                os.environ["OPENAI_API_KEY"] = preserved_api_key

        session = runtime.create_session(session_id="assembly-diagnostics-demo")
        visible = [entry.name for entry in session.visible_invocations() if entry.name == SKILL_NAME]

        preserved_api_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            preflight = run_async(runtime.preflight_default_model_route())
        finally:
            if preserved_api_key is not None:
                os.environ["OPENAI_API_KEY"] = preserved_api_key

        preset = runtime.query_assembly_preset_provenance()

        assert preset["name"] == "headless-live"
        assert visible == [SKILL_NAME]
        assert preflight.ready is False
        assert preflight.failure_class.value == "missing_env"

        print("demo: assembly diagnostics")
        print(f"assembly preset: {preset['name']}")
        print(f"visible invocations: {', '.join(visible)}")
        print(f"failure class: {preflight.failure_class.value}")
        print("status: ok")


if __name__ == "__main__":
    main()
