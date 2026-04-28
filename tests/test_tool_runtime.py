import asyncio
import time
from pathlib import Path

import runtime.tool_runtime as tool_runtime_module
from runtime.builtins import tool_impls as builtins_tool_impls
from runtime.permissions import PermissionContext
from runtime.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    ToolDefinition,
    ToolTraits,
    ValidationOutcome,
)
from runtime.registries import ToolRegistry
from runtime.runtime_services import RuntimeServices
from runtime.tool_runtime import (
    ToolCall,
    ToolCallStatus,
    ToolContext,
    ToolScheduler,
    assemble_main_thread_tool_pool,
    assemble_subagent_tool_pool,
)


def test_tool_runtime_validation_permission_and_mapping(tmp_path: Path) -> None:
    async def validate_input(tool_input: dict[str, str], _: ToolContext) -> ValidationOutcome:
        value = tool_input["value"].strip()
        if value == "blocked":
            return ValidationOutcome(False, "blocked by validator")
        return ValidationOutcome(True, updated_input={"value": value})

    async def check_permissions(tool_input: dict[str, str], _: ToolContext) -> PermissionDecision:
        if tool_input["value"] == "secret":
            return PermissionDecision(PermissionBehavior.ASK, "approval required")
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def execute(tool_input: dict[str, str], _: ToolContext) -> dict[str, str]:
        return {"echo": tool_input["value"]}

    async def permission_handler(
        _: ToolDefinition,
        tool_input: dict[str, str],
        __: PermissionDecision,
        ___: ToolContext,
    ) -> PermissionDecision:
        if tool_input["value"] == "secret":
            return PermissionDecision(PermissionBehavior.ALLOW)
        return PermissionDecision(PermissionBehavior.DENY, "denied")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo values",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            validate_input=validate_input,
            check_permissions=check_permissions,
            execute=execute,
        )
    )

    scheduler = ToolScheduler(registry)
    context = ToolContext(
        session_id="s1",
        turn_id="t1",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        permission_handler=permission_handler,
    )

    results = asyncio.run(
        scheduler.run(
            [
                ToolCall(call_id="1", tool_name="echo", tool_input={"value": " secret "}),
                ToolCall(call_id="2", tool_name="echo", tool_input={"value": "blocked"}),
                ToolCall(call_id="3", tool_name="echo", tool_input={"missing": "value"}),
            ],
            context,
        )
    )

    assert results[0].status == ToolCallStatus.SUCCESS
    assert results[0].output == {"echo": "secret"}
    assert results[1].status == ToolCallStatus.ERROR
    assert results[1].error == "blocked by validator"
    assert results[2].status == ToolCallStatus.ERROR
    assert "required field missing" in results[2].error


def test_tool_pool_resolution_and_scheduler_partitioning(tmp_path: Path) -> None:
    log: list[tuple[str, str, float]] = []

    def make_tool(name: str, *, read_only: bool, concurrency_safe: bool) -> ToolDefinition:
        async def execute(_: dict[str, str], __: ToolContext) -> str:
            log.append(("start", name, time.monotonic()))
            await asyncio.sleep(0.05)
            log.append(("end", name, time.monotonic()))
            return name

        return ToolDefinition(
            name=name,
            description=name,
            aliases=(name.upper(),),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            traits=ToolTraits(read_only=read_only, concurrency_safe=concurrency_safe),
            execute=execute,
        )

    registry = ToolRegistry()
    read_a = make_tool("read-a", read_only=True, concurrency_safe=True)
    read_b = make_tool("read-b", read_only=True, concurrency_safe=True)
    write_c = make_tool("write-c", read_only=False, concurrency_safe=False)
    registry.register(read_a)
    registry.register(read_b)
    registry.register(write_c)

    main_pool = assemble_main_thread_tool_pool(
        registry,
        allowed_tools=["READ-*", "write-c"],
        disallowed_tools=["read-b"],
    )
    subagent_pool = assemble_subagent_tool_pool(
        registry,
        parent_pool=main_pool,
        allowed_tools=["*"],
        disallowed_tools=["write-*"],
    )

    assert [tool.name for tool in main_pool] == ["read-a", "write-c"]
    assert [tool.name for tool in subagent_pool] == ["read-a"]

    scheduler = ToolScheduler(registry)
    context = ToolContext(
        session_id="s2",
        turn_id="t2",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
    )
    results = asyncio.run(
        scheduler.run(
            [
                ToolCall("a", "read-a", {}),
                ToolCall("b", "read-b", {}),
                ToolCall("c", "write-c", {}),
            ],
            context,
        )
    )

    assert [result.output for result in results] == ["read-a", "read-b", "write-c"]
    start_events = [entry for entry in log if entry[0] == "start"]
    end_events = [entry for entry in log if entry[0] == "end"]
    assert start_events[0][1] in {"read-a", "read-b"}
    assert start_events[1][1] in {"read-a", "read-b"}
    write_start = next(index for index, entry in enumerate(log) if entry[0] == "start" and entry[1] == "write-c")
    assert all(index < write_start for index, entry in enumerate(log) if entry[0] == "end" and entry[1] in {"read-a", "read-b"})


def test_tool_context_exposes_runtime_private_context(tmp_path: Path) -> None:
    permission_context = PermissionContext(session_id="s3", mode=PermissionMode.ACCEPT_EDITS)
    context = ToolContext(
        session_id="s3",
        turn_id="t3",
        agent_name="main-router",
        cwd=tmp_path,
        permission_context=permission_context,
        metadata={"run_id": "run-1", "parent_run_id": "run-0", "query_source": "agent_tool"},
    )

    assert context.private_context.permission_context is permission_context
    assert context.private_context.run_id == "run-1"
    assert context.private_context.parent_run_id == "run-0"
    assert context.private_context.extensions["query_source"] == "agent_tool"


def test_guarded_memory_roots_use_canonical_memory_resolver(tmp_path: Path) -> None:
    class BrokenMemorySlot:
        pass

    class RecordingMemoryService:
        def __init__(self, roots: tuple[Path, ...]) -> None:
            self._roots = roots
            self.calls: list[dict[str, object]] = []

        def guarded_roots(self, **kwargs):
            self.calls.append(dict(kwargs))
            return self._roots

    class ResolverOnlyRuntimeServices(RuntimeServices):
        def __init__(self, canonical_memory: RecordingMemoryService) -> None:
            super().__init__(memory=BrokenMemorySlot())
            self._canonical_memory = canonical_memory

        def resolve_memory_service(self):
            return getattr(self, "_canonical_memory", object.__getattribute__(self, "memory"))

    guarded_root = tmp_path / ".runtime" / "memory" / "shared"
    canonical_memory = RecordingMemoryService((guarded_root,))
    services = ResolverOnlyRuntimeServices(canonical_memory)
    context = ToolContext(
        session_id="session-guarded",
        turn_id="turn-guarded",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )

    assert tool_runtime_module._guarded_memory_roots(context) == (guarded_root.resolve(),)
    assert builtins_tool_impls._guarded_memory_roots(context) == (guarded_root.resolve(),)
    assert canonical_memory.calls == [
        {
            "session_id": "session-guarded",
            "agent": AgentDefinition(name="main-router", description="", prompt=""),
            "cwd": tmp_path,
        },
        {
            "session_id": "session-guarded",
            "agent": AgentDefinition(name="main-router", description="", prompt=""),
            "cwd": tmp_path,
        },
    ]
