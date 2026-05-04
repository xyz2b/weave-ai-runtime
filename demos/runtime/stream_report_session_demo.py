from __future__ import annotations

from pathlib import Path

from demos._shared.common import run_async, temporary_workspace

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
                            request_id="req-stream-report-helper-1",
                            text="helper-owned reply",
                        ),
                        text_batch(
                            request_id="req-stream-report-caller-1",
                            text="caller turn one",
                        ),
                        text_batch(
                            request_id="req-stream-report-caller-2",
                            text="caller turn two",
                        ),
                    ]
                ),
            )
        )

        helper_report = run_async(
            runtime.run_prompt_report(
                "Run the helper-owned report path.",
                session_id="stream-report-helper-session",
            )
        )
        session = runtime.create_session(session_id="stream-report-caller-session")
        first_caller_report = run_async(
            runtime.stream_prompt_report_in_session(
                session,
                "Run the streamed caller-owned turn.",
            ).report()
        )
        messages_after_first = len(session.messages)
        second_caller_report = run_async(
            runtime.run_prompt_report_in_session(
                session,
                "Run the reusable caller-owned follow-up turn.",
            )
        )
        messages_after_second = len(session.messages)

        assert helper_report.session_owner == "helper"
        assert helper_report.final_status == "completed"
        assert first_caller_report.session_owner == "caller"
        assert second_caller_report.session_owner == "caller"
        assert messages_after_first == 2
        assert messages_after_second == 4
        assert session.state.status.value == "ready"
        assert second_caller_report.messages[-1].text == "caller turn two"

        run_async(session.close())

        print("demo: stream/report session")
        print(f"helper-owned report: {helper_report.final_status}")
        print("session reusable: true")
        print("status: ok")


if __name__ == "__main__":
    main()
