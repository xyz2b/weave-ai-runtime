from __future__ import annotations

from pathlib import Path

from examples._shared.common import run_async, temporary_workspace

from weavert import AgentDefinition, ToolDefinition, ToolTraits
from weavert.permissions import AllowAllPermissionService
from weavert.result_projections import child_summary
from weavert.runtime_kernel import (
    BuiltinPackConfig,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
)
from weavert_testing import ScriptedModelClient, text_batch, tool_call_batch

_VISIBLE_TOOLS: tuple[str, ...] = ()
_CHILD_SUMMARY = "worker summary: scoped tools only"


def _scope_tool(name: str, label: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=label,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=lambda _tool_input, _context: {"scope": label},
    )


def _parent_batch(request):
    assert request.agent is not None
    assert request.agent.name == "main-router"
    return tool_call_batch(
        request_id="req-scoped-agent-parent-1",
        tool_name="agent",
        tool_input={
            "agent": "scoped-worker",
            "prompt": "Inspect your scoped tools and reply once.",
        },
        call_id="call-scoped-agent",
    )


def _child_batch(request):
    global _VISIBLE_TOOLS
    assert request.agent is not None
    assert request.agent.name == "scoped-worker"
    _VISIBLE_TOOLS = request.turn_context.available_tools
    return text_batch(
        request_id="req-scoped-agent-child-1",
        text=_CHILD_SUMMARY,
    )


def _finish_batch(request):
    assert request.agent is not None
    assert request.agent.name == "main-router"
    return text_batch(
        request_id="req-scoped-agent-parent-2",
        text="parent finished delegation demo",
    )


def main() -> None:
    with temporary_workspace() as workspace:
        client = ScriptedModelClient([
            _parent_batch,
            _child_batch,
            _finish_batch,
        ])
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=Path(workspace),
                distribution=RuntimeDistribution.CORE,
                model_client=client,
                builtins=BuiltinPackConfig(
                    extra_tools=[
                        _scope_tool("collect_scope", "child-visible"),
                        _scope_tool("parent_only", "parent-only"),
                    ],
                    extra_agents=[
                        AgentDefinition(
                            name="scoped-worker",
                            description="Worker with a narrow tool pool.",
                            prompt="Reply with a short child summary.",
                            tools=("collect_scope",),
                        )
                    ],
                    agent_replacements={
                        "main-router": AgentDefinition(
                            name="main-router",
                            description="Routes the scoped agent demo.",
                            prompt="Delegate to the scoped worker once.",
                            tools=("agent", "collect_scope", "parent_only"),
                        )
                    },
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        report = run_async(
            runtime.run_prompt_report(
                "Delegate once.",
                session_id="scoped-agent-demo",
                wait_for_finalization=True,
            )
        )
        summary = child_summary(report.messages, agent_name="scoped-worker")

        assert _VISIBLE_TOOLS == ("collect_scope",)
        assert summary is not None
        assert summary.summary == _CHILD_SUMMARY
        assert summary.scope_summary is not None
        assert summary.scope_summary.visible_tools == ("collect_scope",)
        assert summary.scope_summary.permission_mode == "default"
        assert summary.scope_summary.memory_scope is None
        assert summary.scope_summary.isolation_mode == "none"
        assert report.final_status == "completed"

        print("demo: scoped agent delegation")
        print(f"visible tools: {', '.join(_VISIBLE_TOOLS)}")
        print(f"scope tools: {', '.join(summary.scope_summary.visible_tools)}")
        print(f"scope memory: {summary.scope_summary.memory_scope or 'none'}")
        print("delegated agent: scoped-worker")
        print(f"child summary: {summary.summary}")
        print("status: ok")


if __name__ == "__main__":
    main()
