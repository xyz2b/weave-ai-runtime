from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .tool_orchestration import StreamingToolOrchestrator
from .tool_runtime import ToolCall, ToolContext
from .turn_engine.models import NormalizedModelCapabilities, ToolExecutorTier


@dataclass(slots=True)
class BaseToolExecutor:
    context: ToolContext
    model_capabilities: NormalizedModelCapabilities
    initial_tier: ToolExecutorTier
    effective_tier: ToolExecutorTier
    orchestrator: StreamingToolOrchestrator
    downgrade_reason: str | None = None
    _observed_tool_use_ids: set[str] = field(default_factory=set)

    async def observe_stream_calls(
        self,
        calls: Sequence[ToolCall],
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
        block_offset: int = 0,
    ) -> None:
        _ = calls, assistant_message_id, provider_request_id, block_offset
        return None

    async def finalize(
        self,
        calls: Sequence[ToolCall],
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
        has_pending_tool_use: bool = False,
    ):
        raise NotImplementedError

    def _mark_observed(self, call: ToolCall) -> bool:
        if call.call_id in self._observed_tool_use_ids:
            return False
        self._observed_tool_use_ids.add(call.call_id)
        return True

    def _downgrade(self, tier: ToolExecutorTier, reason: str) -> None:
        self.effective_tier = tier
        self.downgrade_reason = reason

    def interrupt(self, reason: str = "interrupt") -> None:
        self.orchestrator.interrupt(reason)


@dataclass(slots=True)
class FullStreamingToolExecutor(BaseToolExecutor):
    async def observe_stream_calls(
        self,
        calls: Sequence[ToolCall],
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
        block_offset: int = 0,
    ) -> None:
        if self.effective_tier != ToolExecutorTier.FULL_STREAMING:
            return
        for index, call in enumerate(calls):
            if not self._mark_observed(call):
                continue
            await self.orchestrator.observe_tool_call(
                call,
                assistant_message_id=assistant_message_id,
                provider_request_id=provider_request_id,
                block_index=block_offset + index,
            )

    async def finalize(
        self,
        calls: Sequence[ToolCall],
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
        has_pending_tool_use: bool = False,
    ):
        if has_pending_tool_use and self.effective_tier == ToolExecutorTier.FULL_STREAMING:
            self._downgrade(
                ToolExecutorTier.BUFFERED,
                "stream ended without a safe pre-message_stop finalize boundary",
            )
        if self.effective_tier != ToolExecutorTier.FULL_STREAMING:
            buffered = BufferedToolExecutor(
                context=self.context,
                model_capabilities=self.model_capabilities,
                initial_tier=self.initial_tier,
                effective_tier=self.effective_tier,
                orchestrator=self.orchestrator,
                downgrade_reason=self.downgrade_reason,
                _observed_tool_use_ids=set(self._observed_tool_use_ids),
            )
            return await buffered.finalize(
                calls,
                assistant_message_id=assistant_message_id,
                provider_request_id=provider_request_id,
            )
        return await self.orchestrator.finalize()


@dataclass(slots=True)
class BufferedToolExecutor(BaseToolExecutor):
    async def finalize(
        self,
        calls: Sequence[ToolCall],
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
        has_pending_tool_use: bool = False,
    ):
        _ = has_pending_tool_use
        for index, call in enumerate(calls):
            if not self._mark_observed(call):
                continue
            await self.orchestrator.observe_tool_call(
                call,
                assistant_message_id=assistant_message_id,
                provider_request_id=provider_request_id,
                block_index=index,
            )
        return await self.orchestrator.finalize()


@dataclass(slots=True)
class BatchToolExecutor(BufferedToolExecutor):
    pass


def select_tool_executor(
    model_client: Any,
    *,
    context: ToolContext,
    lifecycle_sink=None,
    request: Any = None,
) -> BaseToolExecutor | None:
    capabilities = model_capabilities_for(model_client, request=request)
    tier = select_tool_executor_tier(capabilities)
    if tier == ToolExecutorTier.NONE:
        return None
    orchestrator = StreamingToolOrchestrator(
        context=context,
        executor_tier=tier.value,
        model_capabilities=capabilities,
        lifecycle_sink=lifecycle_sink,
    )
    if tier == ToolExecutorTier.FULL_STREAMING:
        return FullStreamingToolExecutor(
            context=context,
            model_capabilities=capabilities,
            initial_tier=tier,
            effective_tier=tier,
            orchestrator=orchestrator,
        )
    if tier == ToolExecutorTier.BUFFERED:
        return BufferedToolExecutor(
            context=context,
            model_capabilities=capabilities,
            initial_tier=tier,
            effective_tier=tier,
            orchestrator=orchestrator,
        )
    return BatchToolExecutor(
        context=context,
        model_capabilities=capabilities,
        initial_tier=tier,
        effective_tier=tier,
        orchestrator=orchestrator,
    )


def select_tool_executor_tier(
    capabilities: NormalizedModelCapabilities,
) -> ToolExecutorTier:
    if (
        capabilities.structured_tool_calls
        and capabilities.streaming_tool_call_deltas
        and capabilities.tool_call_finalize_boundary
    ):
        return ToolExecutorTier.FULL_STREAMING
    if capabilities.structured_tool_calls:
        return ToolExecutorTier.BUFFERED
    if capabilities.parseable_tool_calls_after_message:
        return ToolExecutorTier.BATCH
    return ToolExecutorTier.NONE


def model_capabilities_for(
    model_client: Any,
    *,
    request: Any = None,
) -> NormalizedModelCapabilities:
    if request is not None and isinstance(getattr(request, "resolved_capabilities", None), NormalizedModelCapabilities):
        return request.resolved_capabilities
    if hasattr(model_client, "tool_capabilities"):
        capabilities = model_client.tool_capabilities(request)
        if isinstance(capabilities, NormalizedModelCapabilities):
            return capabilities
    if hasattr(model_client, "normalized_model_capabilities"):
        capabilities = model_client.normalized_model_capabilities
        if isinstance(capabilities, NormalizedModelCapabilities):
            return capabilities
    return NormalizedModelCapabilities(
        structured_tool_calls=True,
        streaming_tool_call_deltas=False,
        tool_call_finalize_boundary=False,
        parseable_tool_calls_after_message=True,
        multiple_tool_calls_per_message=True,
        abort_signal_passthrough=True,
    )
