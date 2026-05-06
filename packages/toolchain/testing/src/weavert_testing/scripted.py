from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from weavert.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType

BatchFactory = Callable[[ModelRequest], Sequence[ModelStreamEvent]]
BatchSpec = Sequence[ModelStreamEvent] | BatchFactory


class ScriptedModelExhaustionError(AssertionError):
    """Raised when a scripted model receives more requests than configured batches."""


@dataclass(slots=True)
class ScriptedModelClient:
    batches: list[BatchSpec]
    requests: list[ModelRequest] = field(default_factory=list)
    _initial_batch_count: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.batches = list(self.batches)
        self.requests = list(self.requests)
        self._initial_batch_count = len(self.batches)

    @property
    def initial_batch_count(self) -> int:
        return self._initial_batch_count

    @property
    def remaining_batch_count(self) -> int:
        return len(self.batches)

    @property
    def consumed_batch_count(self) -> int:
        return self.initial_batch_count - self.remaining_batch_count

    async def complete(self, request: ModelRequest):  # pragma: no cover - stream-only test double
        _ = request
        raise NotImplementedError("ScriptedModelClient only implements stream().")

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if not self.batches:
            raise ScriptedModelExhaustionError(
                _scripted_batch_exhaustion_message(request, request_count=len(self.requests))
            )
        batch = self.batches.pop(0)
        events = batch(request) if callable(batch) else batch
        for event in events:
            yield event



def tool_call_batch(
    *,
    request_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    call_id: str,
    stop_reason: str = "tool_use",
) -> list[ModelStreamEvent]:
    return [
        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": request_id}),
        ModelStreamEvent(
            ModelStreamEventType.TOOL_CALL,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "call_id": call_id,
            },
        ),
        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": stop_reason}),
    ]



def text_batch(
    *,
    request_id: str,
    text: str,
    stop_reason: str = "end_turn",
) -> list[ModelStreamEvent]:
    return [
        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": request_id}),
        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": text}),
        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": stop_reason}),
    ]



def _scripted_batch_exhaustion_message(request: ModelRequest, *, request_count: int) -> str:
    agent_name = request.agent.name if request.agent is not None else "<unknown>"
    return (
        "ScriptedModelClient exhausted its configured batches after "
        f"{request_count - 1} completed request(s); received unexpected request {request_count} "
        f"for agent '{agent_name}'."
    )


__all__ = [
    "BatchFactory",
    "BatchSpec",
    "ScriptedModelClient",
    "ScriptedModelExhaustionError",
    "text_batch",
    "tool_call_batch",
]
