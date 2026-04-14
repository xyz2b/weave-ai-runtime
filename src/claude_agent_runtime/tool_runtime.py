from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .contracts import ExecutionResult, ExecutionStatus
from .definitions import (
    InterruptBehavior,
    PermissionBehavior,
    PermissionDecision,
    ToolDefinition,
    ValidationOutcome,
)
from .registries import ToolRegistry
from .tasking import TaskManager


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class ToolProgressUpdate:
    tool_name: str
    message: str
    progress: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolProgressSink(Protocol):
    async def emit(self, update: ToolProgressUpdate) -> None: ...


class PermissionHandler(Protocol):
    async def __call__(
        self,
        definition: ToolDefinition,
        tool_input: dict[str, Any],
        decision: PermissionDecision,
        context: "ToolContext",
    ) -> PermissionDecision: ...


class AskUserHandler(Protocol):
    async def __call__(
        self,
        question: str,
        options: Sequence[str] | None = None,
    ) -> Any: ...


class AgentRunner(Protocol):
    async def __call__(
        self,
        agent_name: str,
        prompt: str,
        context: "ToolContext",
        *,
        background: bool = False,
    ) -> Any: ...


class SkillRunner(Protocol):
    async def __call__(
        self,
        skill_name: str,
        arguments: Sequence[str],
        context: "ToolContext",
    ) -> Any: ...


@dataclass(slots=True)
class ToolContext:
    session_id: str
    turn_id: str
    agent_name: str
    cwd: Path
    tool_registry: ToolRegistry | None = None
    agent_registry: Any = None
    skill_registry: Any = None
    progress_sink: ToolProgressSink | None = None
    permission_handler: PermissionHandler | None = None
    ask_user_handler: AskUserHandler | None = None
    agent_runner: AgentRunner | None = None
    skill_runner: SkillRunner | None = None
    task_manager: TaskManager | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _interrupt_reason: str | None = None

    async def emit_progress(
        self,
        tool_name: str,
        message: str,
        *,
        progress: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.progress_sink is None:
            return
        await self.progress_sink.emit(
            ToolProgressUpdate(
                tool_name=tool_name,
                message=message,
                progress=progress,
                metadata=metadata or {},
            )
        )

    def request_interrupt(self, reason: str = "interrupt") -> None:
        self._interrupt_reason = reason

    def interrupted(self) -> bool:
        return self._interrupt_reason is not None

    @property
    def interrupt_reason(self) -> str | None:
        return self._interrupt_reason


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass(slots=True)
class ToolCallResult:
    call_id: str
    tool_name: str
    status: ToolCallStatus
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_execution_result(self) -> ExecutionResult[Any]:
        if self.status == ToolCallStatus.SUCCESS:
            return ExecutionResult(status=ExecutionStatus.SUCCESS, value=self.output, metadata=self.metadata)
        if self.status == ToolCallStatus.CANCELLED:
            return ExecutionResult(status=ExecutionStatus.CANCELLED, error=self.error, metadata=self.metadata)
        if self.status == ToolCallStatus.DENIED:
            return ExecutionResult(status=ExecutionStatus.FAILED, error=self.error, metadata=self.metadata)
        return ExecutionResult(status=ExecutionStatus.FAILED, error=self.error, metadata=self.metadata)


class ToolScheduler:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._running: dict[str, tuple[asyncio.Task[ToolCallResult], ToolDefinition]] = {}

    async def run(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
    ) -> tuple[ToolCallResult, ...]:
        results: list[ToolCallResult] = []
        for concurrent, batch in self.partition_calls(calls):
            if concurrent:
                batch_results = await self._run_concurrent_batch(batch, context)
                results.extend(batch_results)
            else:
                for call in batch:
                    results.append(await self._run_single(call, context))
        return tuple(results)

    def interrupt(self, reason: str = "interrupt") -> None:
        for task, definition in self._running.values():
            if definition.traits.interrupt_behavior == InterruptBehavior.CANCEL:
                task.cancel()

    def partition_calls(self, calls: Sequence[ToolCall]) -> list[tuple[bool, list[ToolCall]]]:
        batches: list[tuple[bool, list[ToolCall]]] = []
        for call in calls:
            definition = self._registry.get(call.tool_name)
            concurrent = bool(
                definition is not None
                and definition.traits.read_only
                and definition.traits.concurrency_safe
            )
            if concurrent and batches and batches[-1][0]:
                batches[-1][1].append(call)
            else:
                batches.append((concurrent, [call]))
        return batches

    async def _run_concurrent_batch(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
    ) -> tuple[ToolCallResult, ...]:
        tasks = [asyncio.create_task(self._run_single(call, context)) for call in calls]
        for call, task in zip(calls, tasks):
            definition = self._registry.get(call.tool_name)
            if definition is not None:
                self._running[call.call_id] = (task, definition)
        try:
            return tuple(await asyncio.gather(*tasks))
        finally:
            for call in calls:
                self._running.pop(call.call_id, None)

    async def _run_single(self, call: ToolCall, context: ToolContext) -> ToolCallResult:
        definition = self._registry.get(call.tool_name)
        if definition is None:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.ERROR,
                error=f"Unknown tool: {call.tool_name}",
            )
        try:
            task = asyncio.current_task()
            if task is not None:
                self._running[call.call_id] = (task, definition)
            return await execute_tool_call(definition, call, context)
        except asyncio.CancelledError:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.CANCELLED,
                error="Tool execution cancelled",
            )
        finally:
            self._running.pop(call.call_id, None)


async def execute_tool_call(
    definition: ToolDefinition,
    call: ToolCall,
    context: ToolContext,
) -> ToolCallResult:
    try:
        if context.interrupted() and definition.traits.interrupt_behavior == InterruptBehavior.CANCEL:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.CANCELLED,
                error=context.interrupt_reason or "Tool execution interrupted",
            )

        normalized_input = validate_input_schema(definition.input_schema, call.tool_input)

        if definition.validate_input is not None:
            validation = await maybe_await(definition.validate_input(normalized_input, context))
            if not validation.valid:
                return ToolCallResult(
                    call_id=call.call_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.ERROR,
                    error=validation.message or "Tool input validation failed",
                    metadata=validation.details,
                )
            if validation.updated_input is not None:
                normalized_input = validation.updated_input

        permission_decision = PermissionDecision(PermissionBehavior.ALLOW)
        if definition.check_permissions is not None:
            permission_decision = await maybe_await(
                definition.check_permissions(normalized_input, context)
            )
        normalized_input = permission_decision.updated_input or normalized_input

        if permission_decision.behavior == PermissionBehavior.DENY:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.DENIED,
                error=permission_decision.message or "Tool use denied",
                metadata=permission_decision.details,
            )

        if permission_decision.behavior == PermissionBehavior.ASK:
            if context.permission_handler is None:
                return ToolCallResult(
                    call_id=call.call_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.DENIED,
                    error=permission_decision.message or "Permission required",
                    metadata=permission_decision.details,
                )
            permission_decision = await context.permission_handler(
                definition,
                normalized_input,
                permission_decision,
                context,
            )
            normalized_input = permission_decision.updated_input or normalized_input
            if permission_decision.behavior != PermissionBehavior.ALLOW:
                return ToolCallResult(
                    call_id=call.call_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.DENIED,
                    error=permission_decision.message or "Tool use denied",
                    metadata=permission_decision.details,
                )

        if definition.execute is None:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.ERROR,
                error=f"Tool '{definition.name}' has no execution handler",
            )

        raw_output = await maybe_await(definition.execute(normalized_input, context))
        return map_tool_output(definition.name, call.call_id, raw_output)
    except Exception as exc:  # pragma: no cover - defensive boundary
        return ToolCallResult(
            call_id=call.call_id,
            tool_name=definition.name,
            status=ToolCallStatus.ERROR,
            error=str(exc),
        )


def map_tool_output(tool_name: str, call_id: str, raw_output: Any) -> ToolCallResult:
    if isinstance(raw_output, ToolCallResult):
        return raw_output
    if isinstance(raw_output, ExecutionResult):
        status = ToolCallStatus.SUCCESS if raw_output.status == ExecutionStatus.SUCCESS else ToolCallStatus.ERROR
        return ToolCallResult(
            call_id=call_id,
            tool_name=tool_name,
            status=status,
            output=raw_output.value,
            error=raw_output.error,
            metadata=raw_output.metadata,
        )
    return ToolCallResult(
        call_id=call_id,
        tool_name=tool_name,
        status=ToolCallStatus.SUCCESS,
        output=raw_output,
    )


def assemble_main_thread_tool_pool(
    registry: ToolRegistry,
    *,
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    return resolve_tool_pool(
        registry,
        base_pool=registry.definitions(),
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )


def assemble_subagent_tool_pool(
    registry: ToolRegistry,
    *,
    parent_pool: Sequence[ToolDefinition],
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    return resolve_tool_pool(
        registry,
        base_pool=tuple(parent_pool),
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )


def resolve_tool_pool(
    registry: ToolRegistry,
    *,
    base_pool: Sequence[ToolDefinition],
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    base_definitions = tuple(base_pool)
    if not allowed_tools:
        selected = list(base_definitions)
    else:
        selected = []
        for definition in base_definitions:
            if any(_matches_tool_selector(definition, selector) for selector in allowed_tools):
                selected.append(definition)
    if disallowed_tools:
        selected = [
            definition
            for definition in selected
            if not any(_matches_tool_selector(definition, selector) for selector in disallowed_tools)
        ]
    deduped: dict[str, ToolDefinition] = {definition.name: definition for definition in selected}
    return tuple(sorted(deduped.values(), key=lambda definition: definition.name))


def validate_input_schema(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    if not schema:
        return dict(payload)
    value = _validate_schema_node(schema, payload, "$")
    if not isinstance(value, dict):
        raise ValueError("Tool input schema must validate to an object payload")
    return value


def _validate_schema_node(schema: Mapping[str, Any], value: Any, path: str) -> Any:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            raise ValueError(f"{path}: expected object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        result: dict[str, Any] = {}
        for field_name in required:
            if field_name not in value:
                raise ValueError(f"{path}.{field_name}: required field missing")
        for key, raw_item in value.items():
            if key in properties:
                result[key] = _validate_schema_node(properties[key], raw_item, f"{path}.{key}")
                continue
            if additional is False:
                raise ValueError(f"{path}.{key}: additional properties are not allowed")
            if isinstance(additional, Mapping):
                result[key] = _validate_schema_node(additional, raw_item, f"{path}.{key}")
            else:
                result[key] = raw_item
        return result

    if expected_type == "array":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{path}: expected array")
        item_schema = schema.get("items", {})
        return [_validate_schema_node(item_schema, item, f"{path}[{index}]") for index, item in enumerate(value)]

    if expected_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected string")
        enum = schema.get("enum")
        if enum is not None and value not in enum:
            raise ValueError(f"{path}: expected one of {enum}")
        return value

    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path}: expected integer")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path}: value must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path}: value must be <= {maximum}")
        return value

    if expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{path}: expected number")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path}: value must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path}: value must be <= {maximum}")
        return value

    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected boolean")
        return value

    return value


def _matches_tool_selector(definition: ToolDefinition, selector: str) -> bool:
    if selector == "*":
        return True
    candidates = (definition.name, *definition.aliases)
    if any(char in selector for char in "*?[]"):
        return any(fnmatch(candidate, selector) for candidate in candidates)
    return definition.matches(selector)


async def maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
