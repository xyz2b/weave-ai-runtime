from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .bootstrap import PROJECT_ROOT

from weavert.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType

BatchFactory = Callable[[ModelRequest], Sequence[ModelStreamEvent]]
BatchSpec = Sequence[ModelStreamEvent] | BatchFactory


@dataclass(slots=True)
class ScriptedModelClient:
    batches: list[BatchSpec]
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest):  # pragma: no cover - stream-only demo helper
        raise NotImplementedError("The demo client only implements stream().")

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if not self.batches:
            raise AssertionError(f"No scripted model batch left for request in {PROJECT_ROOT.name}")
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
