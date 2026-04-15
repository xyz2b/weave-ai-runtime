from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..hooks import ElicitationPayload, ElicitationResultPayload
from .models import ElicitationRequest, ElicitationResponse


@dataclass(slots=True)
class SharedElicitationService:
    metadata: dict[str, Any] = field(default_factory=dict)

    async def request(
        self,
        request: ElicitationRequest,
        *,
        runtime_context: Any = None,
    ) -> ElicitationResponse:
        hook_bus = None
        host_runtime = None
        if runtime_context is not None and getattr(runtime_context, "runtime_services", None) is not None:
            hook_bus = runtime_context.runtime_services.hook_bus
            host_runtime = runtime_context.runtime_services.host
        elif runtime_context is not None:
            hook_bus = getattr(runtime_context, "hook_bus", None)
            host_runtime = getattr(runtime_context, "host_runtime", None)

        if hook_bus is not None:
            hook_result = await _maybe_await(
                hook_bus.dispatch(
                    request.session_id,
                    ElicitationPayload(
                        session_id=request.session_id,
                        prompt=request.prompt,
                        kind=request.kind,
                    ),
                )
            )
            if getattr(hook_result, "elicitation_result", None) is not None:
                return ElicitationResponse(
                    response=hook_result.elicitation_result,
                    source="hook",
                    metadata={"matched_hooks": list(getattr(hook_result, "matched_owners", ()))},
                )

        if host_runtime is None or not hasattr(host_runtime, "request_elicitation"):
            raise RuntimeError("No elicitation handler is configured")

        response = await _maybe_await(host_runtime.request_elicitation(request))
        if not isinstance(response, ElicitationResponse):
            response = ElicitationResponse(response=response)

        if hook_bus is not None:
            await _maybe_await(
                hook_bus.dispatch(
                    request.session_id,
                    ElicitationResultPayload(
                        session_id=request.session_id,
                        prompt=request.prompt,
                        response={"response": response.response, **response.metadata},
                    ),
                )
            )
        return response

    async def ask(
        self,
        question: str,
        options: Sequence[str] | None = None,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        runtime_context: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.request(
            ElicitationRequest(
                session_id=session_id or "",
                turn_id=turn_id,
                prompt=question,
                options=tuple(options or ()),
                metadata=dict(metadata or {}),
            ),
            runtime_context=runtime_context,
        )
        return response.response


__all__ = ["SharedElicitationService"]


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
