from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .bootstrap import PROJECT_ROOT

from weavert.contracts import RuntimeMessage
from weavert.permissions import AllowAllPermissionService
from weavert.session_runtime import InboundEvent, InboundEventType, SessionController
from weavert.testing import discovery_source, extract_tool_result, temporary_workspace
from weavert.turn_engine import TurnStreamEventType


def demo_workspace(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath("demos", *parts)



def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, sort_keys=True)}")


async def run_session_prompt(
    session: SessionController,
    prompt: str,
) -> tuple[RuntimeMessage, ...]:
    await session.start()
    session.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, prompt))
    produced: list[RuntimeMessage] = []
    async for event in session.stream_until_idle():
        if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
            produced.append(event.message)
    return tuple(produced)


async def close_session_and_wait_for_background_memory(
    session: SessionController,
    *,
    memory_service: Any | None,
) -> None:
    await session.close()
    if memory_service is None or not hasattr(memory_service, "wait_for_background_consolidation"):
        return
    task_ids = session.state.metadata.get("background_memory_consolidation_tasks")
    if not isinstance(task_ids, list):
        return
    seen: set[str] = set()
    for task_id in task_ids:
        normalized = str(task_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        await memory_service.wait_for_background_consolidation(normalized)



def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


__all__ = [
    "AllowAllPermissionService",
    "close_session_and_wait_for_background_memory",
    "demo_workspace",
    "discovery_source",
    "extract_tool_result",
    "print_json",
    "run_async",
    "run_session_prompt",
    "temporary_workspace",
]
