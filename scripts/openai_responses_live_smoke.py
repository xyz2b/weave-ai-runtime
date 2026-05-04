#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from weavert.contracts import MessageRole, ToolResultBlock, ToolUseBlock
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.turn_engine.engine import TurnStreamEventType
import weavert.openai_client as openai_client


PROMPT = "Summarize this repository and use tools when needed."


def _capture_stream_requests() -> tuple[list[dict[str, Any]], Any]:
    captured: list[dict[str, Any]] = []
    original = openai_client._post_json_stream

    def wrapped(url: str, payload: dict[str, Any], *, api_key: str):
        record = {
            "url": url,
            "model": payload.get("model"),
            "parallel_tool_calls": payload.get("parallel_tool_calls"),
            "stream": payload.get("stream"),
            "tool_count": len(payload.get("tools", []) or []),
            "sample_tools": [
                tool.get("name") for tool in (payload.get("tools", []) or [])[:16]
            ],
            "input_types": [
                item.get("type")
                for item in payload.get("input", [])
                if isinstance(item, dict)
            ],
            "stream_calls": [],
            "completed_output_len": None,
        }
        captured.append(record)
        for event in original(url, payload, api_key=api_key):
            if (
                event.get("type") == "response.output_item.added"
                and event.get("item", {}).get("type") == "function_call"
            ):
                item = event["item"]
                record["stream_calls"].append(
                    {
                        "call_id": item.get("call_id"),
                        "name": item.get("name"),
                    }
                )
            elif event.get("type") == "response.completed":
                output = event.get("response", {}).get("output")
                if isinstance(output, list):
                    record["completed_output_len"] = len(output)
            yield event

    openai_client._post_json_stream = wrapped
    return captured, original


async def _run_smoke(runtime) -> dict[str, Any]:
    captured, original = _capture_stream_requests()
    attempts: list[dict[str, Any]] = []
    assistant_tool_turns: list[dict[str, Any]] = []
    user_tool_result_turns: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    final_assistant_text: str | None = None

    try:
        async for event in runtime.stream_prompt(
            PROMPT,
            session_id=f"live-openai-smoke-{uuid4().hex[:8]}",
        ):
            if event.event_type == TurnStreamEventType.ATTEMPT_FINISHED and event.attempt is not None:
                attempts.append(
                    {
                        "iteration": event.attempt.iteration,
                        "request_id": event.attempt.request_id,
                        "stop_reason": event.attempt.stop_reason,
                        "produced_tool_calls": event.attempt.produced_tool_calls,
                        "tool_call_count": event.attempt.tool_call_count,
                        "error": event.attempt.error,
                        "fallback": event.attempt.metadata.get(
                            "stream_completed_output_fallback"
                        ),
                    }
                )
                continue

            if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                message = event.message
                if message.role == MessageRole.ASSISTANT:
                    tool_uses = [
                        {
                            "tool_use_id": block.tool_use_id,
                            "name": block.name,
                        }
                        for block in message.content
                        if isinstance(block, ToolUseBlock)
                    ]
                    if tool_uses:
                        assistant_tool_turns.append(
                            {
                                "message_id": message.message_id,
                                "tool_use_count": len(tool_uses),
                                "tool_uses": tool_uses,
                            }
                        )
                    if message.text:
                        final_assistant_text = message.text
                elif message.role == MessageRole.USER:
                    tool_results = [
                        {
                            "tool_use_id": block.tool_use_id,
                            "is_error": block.is_error,
                        }
                        for block in message.content
                        if isinstance(block, ToolResultBlock)
                    ]
                    if tool_results:
                        user_tool_result_turns.append(
                            {
                                "message_id": message.message_id,
                                "tool_result_count": len(tool_results),
                                "tool_results": tool_results,
                            }
                        )
                continue

            if event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                terminal = {
                    "stop_reason": event.terminal.stop_reason,
                    "request_id": event.terminal.request_id,
                    "provider_stop_reason": event.terminal.provider_stop_reason,
                    "error": event.terminal.error,
                    "metadata": event.terminal.metadata,
                }
    finally:
        openai_client._post_json_stream = original

    checks = {
        "default_route_is_openai_default": runtime.kernel.config.default_model_route
        == openai_client.OPENAI_ROUTE_NAME,
        "parallel_tool_calls_requested": any(
            record.get("parallel_tool_calls") is True for record in captured
        ),
        "multiple_sibling_tool_uses_observed": any(
            turn["tool_use_count"] > 1 for turn in assistant_tool_turns
        ),
        "tool_use_attempt_observed": any(
            attempt["stop_reason"] == "tool_use" and attempt["produced_tool_calls"]
            for attempt in attempts
        ),
        "final_answer_observed": bool(final_assistant_text),
    }
    if any(record["completed_output_len"] == 0 and record["stream_calls"] for record in captured):
        checks["empty_completed_output_fallback_observed"] = any(
            attempt.get("fallback") == "finalized_stream_tool_blocks"
            for attempt in attempts
        )

    failures = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failures,
        "failures": failures,
        "prompt": PROMPT,
        "runtime": {
            "distribution": str(runtime.kernel.config.distribution),
            "default_model_route": runtime.kernel.config.default_model_route,
            "route_metadata": runtime.kernel.config.model_routes[
                runtime.kernel.config.default_model_route
            ].metadata,
        },
        "checks": checks,
        "attempts": attempts,
        "assistant_tool_turns": assistant_tool_turns,
        "user_tool_result_turns": user_tool_result_turns,
        "terminal": terminal,
        "requests": captured,
        "final_text_prefix": final_assistant_text[:300] if final_assistant_text else None,
    }


def main() -> int:
    runtime = assemble_runtime(RuntimeConfig.for_headless_live(PROJECT_ROOT))
    preflight = asyncio.run(runtime.preflight_default_model_route())
    if not preflight.ready:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "preflight_not_ready",
                    "preflight": preflight.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    result = asyncio.run(_run_smoke(runtime))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
