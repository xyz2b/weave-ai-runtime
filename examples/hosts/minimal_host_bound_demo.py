from __future__ import annotations

from pathlib import Path

from examples._shared.common import run_async, temporary_workspace

from weavert.hosts import SdkHostRuntime
from weavert.runtime_kernel import RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.testing import ScriptedModelClient, text_batch


def main() -> None:
    with temporary_workspace() as workspace:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=Path(workspace),
                distribution=RuntimeDistribution.CORE,
                model_client=ScriptedModelClient(
                    [
                        text_batch(
                            request_id="req-minimal-host-1",
                            text="host-bound reply",
                        )
                    ]
                ),
            )
        )
        host = SdkHostRuntime(name="sdk")
        bound = runtime.bind_host(host)

        messages = run_async(
            bound.prompts.run_prompt(
                "hello host",
                session_id="minimal-host-bound-demo",
            )
        )
        turn_terminal_observed = any(
            event.event_type.value == "terminal" for _, event in host.turn_events
        )
        run_async(bound.shutdown())

        assert messages[-1].text == "host-bound reply"
        assert host.lifecycle == ["startup", "ready", "shutdown"]
        assert turn_terminal_observed is True

        print("demo: minimal host-bound")
        print(f"host lifecycle: {', '.join(host.lifecycle)}")
        print(f"turn terminal observed: {str(turn_terminal_observed).lower()}")
        print("status: ok")


if __name__ == "__main__":
    main()
