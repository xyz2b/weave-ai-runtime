from __future__ import annotations

from pathlib import Path

from demos._shared.common import (
    close_session_and_wait_for_background_memory,
    run_async,
    temporary_workspace,
)

from weavert.runtime_kernel import RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.testing import ScriptedModelClient, text_batch


SESSION_ID = "durable-resume-demo"


def main() -> None:
    with temporary_workspace() as workspace:
        workspace_path = Path(workspace)
        first_runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace_path,
                distribution=RuntimeDistribution.FULL,
                model_client=ScriptedModelClient(
                    [
                        text_batch(
                            request_id="req-durable-resume-1",
                            text="first turn reply",
                        )
                    ]
                ),
            )
        )
        first_session = first_runtime.create_session(session_id=SESSION_ID)
        first_report = run_async(
            first_runtime.run_prompt_report_in_session(
                first_session,
                "Turn one should persist.",
                wait_for_finalization=True,
            )
        )
        transcript_after_first = run_async(first_runtime.transcript_store.load(SESSION_ID))
        run_async(
            close_session_and_wait_for_background_memory(
                first_session,
                memory_service=first_runtime.services.memory,
            )
        )

        second_runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace_path,
                distribution=RuntimeDistribution.FULL,
                model_client=ScriptedModelClient(
                    [
                        text_batch(
                            request_id="req-durable-resume-2",
                            text="after resume",
                        )
                    ]
                ),
            )
        )
        resumed_session = second_runtime.create_session(session_id=SESSION_ID)
        run_async(resumed_session.resume())
        resumed_messages = tuple(
            message.text for message in resumed_session.messages if message.text
        )
        second_report = run_async(
            second_runtime.run_prompt_report_in_session(
                resumed_session,
                "Turn two should reuse the same session.",
                wait_for_finalization=True,
            )
        )
        run_async(
            close_session_and_wait_for_background_memory(
                resumed_session,
                memory_service=second_runtime.services.memory,
            )
        )

        turn_one_persisted = len(transcript_after_first.entries) > 0
        session_resumed = "first turn reply" in resumed_messages

        assert first_report.messages[-1].text == "first turn reply"
        assert turn_one_persisted is True
        assert session_resumed is True
        assert second_report.messages[-1].text == "after resume"

        print("demo: durable resume")
        print(f"turn one persisted: {str(turn_one_persisted).lower()}")
        print(f"session resumed: {str(session_resumed).lower()}")
        print("status: ok")


if __name__ == "__main__":
    main()
