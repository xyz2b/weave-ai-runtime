from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from weavert.contracts import TurnContext
from weavert.definitions import AgentDefinition
from weavert.runtime_kernel import BuiltinPackConfig, ModelRouteBinding, RuntimeConfig, WorkflowRunReport
from weavert.testing import (
    ScriptedModelClient,
    ScriptedModelExhaustionError,
    assert_child_summary,
    assert_no_terminal_failure,
    assert_skill_outcome,
    assert_tool_outcome,
    assert_tool_result,
    copied_fixture_workspace,
    run_workflow_test,
    text_batch,
    tool_call_batch,
)
from weavert.turn_engine import ModelRequest

ROOT = Path(__file__).resolve().parents[1]
CODING_FIXTURE = ROOT / "examples" / "projects" / "workspaces" / "coding_workflow"
VERIFICATION_COMMAND = "python3 -m unittest discover -s tests"


async def _drain_stream(client: ScriptedModelClient, request: ModelRequest) -> list[object]:
    return [event async for event in client.stream(request)]



def _fake_request(*, agent_name: str = "test-agent") -> ModelRequest:
    return ModelRequest(
        system_prompt="Test prompt",
        turn_context=TurnContext(
            session_id="session-scripted",
            turn_id="turn-1",
            agent_name=agent_name,
            cwd=".",
            messages=(),
        ),
        messages=(),
        agent=AgentDefinition(
            name=agent_name,
            description="Test agent",
            prompt="You are a test agent.",
        ),
    )



def _workflow_client() -> ScriptedModelClient:
    def _assert_parent_request(request: ModelRequest) -> None:
        assert request.agent is not None
        assert request.agent.name == "coding-assistant"
        assert set(request.turn_context.available_tools) == {
            "bash",
            "edit",
            "glob",
            "grep",
            "read",
            "skill",
        }
        assert set(request.turn_context.available_skills) == {"coding-loop", "review-change"}

    def _assert_reviewer_request(request: ModelRequest) -> None:
        assert request.agent is not None
        assert request.agent.name == "reviewer"
        assert set(request.turn_context.available_tools) == {"glob", "grep", "read"}

    return ScriptedModelClient(
        [
            lambda request: (
                _assert_parent_request(request)
                or tool_call_batch(
                    request_id="req-coding-workflow-1",
                    tool_name="skill",
                    tool_input={"skill": "coding-loop"},
                    call_id="call-coding-loop",
                )
            ),
            lambda request: (
                _assert_parent_request(request)
                or tool_call_batch(
                    request_id="req-coding-workflow-2",
                    tool_name="grep",
                    tool_input={"pattern": "DEFAULT_NAME", "path": "src/demo_service"},
                    call_id="call-inspect-grep",
                )
            ),
            lambda request: (
                _assert_parent_request(request)
                or tool_call_batch(
                    request_id="req-coding-workflow-3",
                    tool_name="edit",
                    tool_input={
                        "file_path": "src/demo_service/greeting.py",
                        "old_string": 'DEFAULT_NAME = "runtime"',
                        "new_string": 'DEFAULT_NAME = "WeaveRT"',
                    },
                    call_id="call-edit-greeting",
                )
            ),
            lambda request: (
                _assert_parent_request(request)
                or tool_call_batch(
                    request_id="req-coding-workflow-4",
                    tool_name="bash",
                    tool_input={"command": VERIFICATION_COMMAND},
                    call_id="call-run-tests",
                )
            ),
            lambda request: (
                _assert_parent_request(request)
                or tool_call_batch(
                    request_id="req-coding-workflow-5",
                    tool_name="skill",
                    tool_input={
                        "skill": "review-change",
                        "arguments": [
                            "changed file: src/demo_service/greeting.py",
                            f"verification: {VERIFICATION_COMMAND}",
                        ],
                    },
                    call_id="call-review-skill",
                )
            ),
            lambda request: (
                _assert_reviewer_request(request)
                or tool_call_batch(
                    request_id="req-coding-workflow-6",
                    tool_name="read",
                    tool_input={"file_path": "src/demo_service/greeting.py"},
                    call_id="call-review-read",
                )
            ),
            lambda request: (
                _assert_reviewer_request(request)
                or text_batch(
                    request_id="req-coding-workflow-7",
                    text="review: pass",
                )
            ),
            lambda request: (
                _assert_parent_request(request)
                or text_batch(
                    request_id="req-coding-workflow-8",
                    text="updated src/demo_service/greeting.py; verification: passed; review: pass",
                )
            ),
        ]
    )



def _minimal_runtime_config(workspace: Path, *, model_client=None) -> RuntimeConfig:
    return RuntimeConfig(
        working_directory=workspace,
        model_client=model_client,
        builtins=BuiltinPackConfig(
            extra_agents=[
                AgentDefinition(
                    name="main-router",
                    description="Test router",
                    prompt="Return the scripted response.",
                )
            ]
        ),
    )


def test_scripted_model_client_records_requests_and_raises_when_batches_are_exhausted() -> None:
    client = ScriptedModelClient([text_batch(request_id="req-scripted-1", text="first reply")])
    request = _fake_request()

    events = asyncio.run(_drain_stream(client, request))

    assert [event.payload for event in events] == [
        {"request_id": "req-scripted-1"},
        {"text": "first reply"},
        {"stop_reason": "end_turn"},
    ]
    assert client.requests == [request]
    assert client.initial_batch_count == 1
    assert client.consumed_batch_count == 1
    assert client.remaining_batch_count == 0

    with pytest.raises(ScriptedModelExhaustionError, match="unexpected request 2"):
        asyncio.run(_drain_stream(client, request))



def test_copied_fixture_workspace_copies_tree_and_points_discovery_at_temp_project(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    (fixture_root / ".weavert" / "agents").mkdir(parents=True)
    (fixture_root / ".weavert" / "agents" / "main-router.md").write_text("# agent\n")
    (fixture_root / "notes.txt").write_text("original\n")

    with copied_fixture_workspace(fixture_root) as fixture:
        assert fixture.fixture_source == fixture_root.resolve()
        assert fixture.workspace_root != fixture_root.resolve()
        assert fixture.discovery_sources[0].root == fixture.workspace_root / ".weavert"
        assert (fixture.workspace_root / "notes.txt").read_text() == "original\n"

        (fixture.workspace_root / "notes.txt").write_text("edited\n")
        assert (fixture.workspace_root / "notes.txt").read_text() == "edited\n"
        assert (fixture_root / "notes.txt").read_text() == "original\n"

        workspace_root = fixture.workspace_root

    assert not workspace_root.exists()



def test_run_workflow_test_preserves_explicit_empty_discovery_sources(tmp_path: Path) -> None:
    client = ScriptedModelClient([text_batch(request_id="req-empty-discovery-1", text="ok")])

    async def _run() -> None:
        report = await run_workflow_test(
            "Reply with ok.",
            workspace=tmp_path,
            runtime_config=_minimal_runtime_config(tmp_path, model_client=client),
            discovery_sources=(),
            session_id="workflow-testing-empty-discovery",
            agent_name="main-router",
        )

        assert report.discovery_sources == ()
        assert report.messages[-1].text == "ok"
        assert len(report.scripted_requests) == 1

    asyncio.run(_run())


def test_run_workflow_test_collects_scripted_diagnostics_from_route_model_client(tmp_path: Path) -> None:
    client = ScriptedModelClient([text_batch(request_id="req-route-scripted-1", text="route ok")])

    async def _run() -> None:
        config = _minimal_runtime_config(tmp_path)
        config.model_routes["scripted"] = ModelRouteBinding(client=client)
        config.default_model_route = "scripted"

        report = await run_workflow_test(
            "Reply with route ok.",
            workspace=tmp_path,
            runtime_config=config,
            discovery_sources=(),
            session_id="workflow-testing-route-model-client",
            agent_name="main-router",
        )

        assert report.messages[-1].text == "route ok"
        assert report.scripted_batch_count_consumed == 1
        assert report.scripted_batch_count_remaining == 0
        assert [request.agent.name for request in report.scripted_requests if request.agent is not None] == [
            "main-router"
        ]

    asyncio.run(_run())


def test_run_workflow_test_returns_canonical_report_plus_test_diagnostics() -> None:
    client = _workflow_client()

    async def _run() -> object:
        with copied_fixture_workspace(CODING_FIXTURE) as fixture:
            report = await run_workflow_test(
                "Apply the coding-loop skill, fix the greeting, run tests, and review the change.",
                workspace=fixture,
                model_client=client,
                session_id="workflow-testing-demo",
                agent_name="coding-assistant",
            )

            assert isinstance(report.workflow, WorkflowRunReport)
            assert report.session_id == "workflow-testing-demo"
            assert report.fixture_source == CODING_FIXTURE.resolve()
            assert report.workspace_root != CODING_FIXTURE.resolve()
            assert report.discovery_sources[0].root == report.workspace_root / ".weavert"
            assert report.scripted_batch_count_consumed == 8
            assert report.scripted_batch_count_remaining == 0
            assert len(report.scripted_requests) == 8
            assert report.child_runs

            assert_no_terminal_failure(report)
            assert report.final_status == "completed"
            assert report.finalization.requested is True

            verification = assert_tool_outcome(
                report,
                "bash",
                matcher=lambda outcome: str(outcome.tool_input.get("command") or "").strip()
                == VERIFICATION_COMMAND,
            )
            assert verification.output["exit_code"] == 0
            assert assert_tool_result(report, "call-run-tests")["exit_code"] == 0

            review_skill = assert_skill_outcome(report, "review-change")
            assert review_skill.mode == "fork"
            assert review_skill.agent_summary is not None
            assert review_skill.agent_summary.summary == "review: pass"

            reviewer = assert_child_summary(report, agent_name="reviewer")
            assert reviewer.summary == "review: pass"
            assert reviewer.status == "completed"

            file_text = (report.workspace_root / "src" / "demo_service" / "greeting.py").read_text()
            assert 'DEFAULT_NAME = "WeaveRT"' in file_text
            return report

    asyncio.run(_run())
