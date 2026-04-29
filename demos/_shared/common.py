from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .bootstrap import PROJECT_ROOT

from weavert.contracts import RuntimeMessage, ToolResultBlock
from weavert.definitions import DefinitionSource, PermissionBehavior, PermissionDecision
from weavert.runtime_kernel import DefinitionSourcePaths
from weavert.session_runtime import InboundEvent, InboundEventType, SessionController
from weavert.turn_engine import TurnStreamEventType


class AllowAllPermissionService:
    async def evaluate(
        self,
        request: Any,
        *,
        initial_decision: Any = None,
        hook_result: Any = None,
        runtime_context: Any = None,
    ) -> PermissionDecision:
        _ = request, initial_decision, hook_result, runtime_context
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def authorize(
        self,
        definition: Any,
        tool_input: Any,
        decision: Any,
        context: Any,
    ) -> PermissionDecision:
        _ = definition, tool_input, decision, context
        return PermissionDecision(PermissionBehavior.ALLOW)


def discovery_source(workspace: Path) -> DefinitionSourcePaths:
    return DefinitionSourcePaths(DefinitionSource.PROJECT, workspace / ".weavert")


def demo_workspace(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath("demos", *parts)


@contextmanager
def temporary_workspace(template: Path | None = None):
    with tempfile.TemporaryDirectory(prefix="weavert-demo-") as tmpdir:
        workspace = Path(tmpdir)
        if template is not None:
            shutil.copytree(template, workspace, dirs_exist_ok=True)
        yield workspace


def extract_tool_result(messages: tuple[RuntimeMessage, ...], tool_use_id: str) -> Any:
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id == tool_use_id:
                return block.content
    raise AssertionError(f"Missing tool result for {tool_use_id}")


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


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)
