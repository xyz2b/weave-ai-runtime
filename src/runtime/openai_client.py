from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from .context_window import (
    MinimalRecoveryClassificationHints,
    ModelContextWindowProfile,
    RecoveryClassificationRule,
    RouteContextWindowPolicy,
    TokenEstimationHint,
)
from .contracts import MessageRole, RuntimeMessage
from .runtime_kernel.config import ModelProviderBinding, ModelRouteBinding
from .turn_engine.models import (
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ModelTerminalMetadata,
    NormalizedModelCapabilities,
)


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
OPENAI_PROVIDER_NAME = "openai-prod"
OPENAI_ROUTE_NAME = "openai_default"


def bundled_openai_recovery_hints() -> MinimalRecoveryClassificationHints:
    return MinimalRecoveryClassificationHints(
        context_limit=RecoveryClassificationRule(
            stop_reasons=("context_limit", "prompt_too_long"),
            provider_error_codes=("context_length_exceeded", "prompt_too_long"),
            http_statuses=(400, 413),
            message_substrings=(
                "maximum context length",
                "context length exceeded",
                "prompt is too long",
            ),
            retryable=True,
        ),
        output_limit=RecoveryClassificationRule(
            stop_reasons=("output_limit", "max_tokens"),
            provider_error_codes=("max_output_tokens", "output_limit"),
            message_substrings=("maximum output tokens", "max_tokens"),
            retryable=True,
        ),
    )


def bundled_openai_context_window_profiles() -> tuple[ModelContextWindowProfile, ...]:
    estimation_hint = TokenEstimationHint(
        tokenizer_name="openai_approximation",
        chars_per_token=4.0,
        advisory_only=True,
    )
    recovery_hints = bundled_openai_recovery_hints()
    return (
        ModelContextWindowProfile(
            provider_name=OPENAI_PROVIDER_NAME,
            profile_name="openai-provider-default",
            model_selector=None,
            max_input_tokens=128000,
            reserved_output_tokens=16384,
            token_estimation_hint=estimation_hint,
            recovery_classification_hints=recovery_hints,
            source="bundled",
            confidence="medium",
        ),
        ModelContextWindowProfile(
            provider_name=OPENAI_PROVIDER_NAME,
            profile_name="gpt-4.1",
            model_selector="gpt-4.1",
            max_input_tokens=1047576,
            reserved_output_tokens=32768,
            token_estimation_hint=estimation_hint,
            recovery_classification_hints=recovery_hints,
            source="bundled",
            confidence="high",
        ),
        ModelContextWindowProfile(
            provider_name=OPENAI_PROVIDER_NAME,
            profile_name="gpt-4.1-mini",
            model_selector="gpt-4.1-mini",
            max_input_tokens=1047576,
            reserved_output_tokens=32768,
            token_estimation_hint=estimation_hint,
            recovery_classification_hints=recovery_hints,
            source="bundled",
            confidence="high",
        ),
        ModelContextWindowProfile(
            provider_name=OPENAI_PROVIDER_NAME,
            profile_name="gpt-4.1-family",
            model_selector="gpt-4.1-*",
            max_input_tokens=1047576,
            reserved_output_tokens=32768,
            token_estimation_hint=estimation_hint,
            recovery_classification_hints=recovery_hints,
            source="bundled",
            confidence="medium",
        ),
    )


@dataclass(slots=True)
class BundledOpenAIModelClient:
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    model_env: str = "OPENAI_MODEL"

    async def complete(self, request) -> ModelResponse:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            return _error_response(
                message=(
                    f"Bundled OpenAI route '{OPENAI_ROUTE_NAME}' requires {self.api_key_env} "
                    "or an explicit host override."
                ),
                stop_reason="auth_error",
                failure_class="auth_error",
                metadata={
                    "configuration_error": True,
                    "credential_env": self.api_key_env,
                    "provider_name": OPENAI_PROVIDER_NAME,
                },
            )
        model_name = request.model or os.environ.get(self.model_env, "").strip() or DEFAULT_OPENAI_MODEL
        payload = {
            "model": model_name,
            "messages": _serialize_request_messages(request.system_prompt, request.messages),
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        try:
            response_payload = await asyncio.to_thread(
                _post_json,
                _chat_completions_url(os.environ.get(self.base_url_env, "").strip() or DEFAULT_OPENAI_BASE_URL),
                payload,
                api_key=api_key,
            )
        except urllib_error.HTTPError as exc:
            return _http_error_response(exc)
        except Exception as exc:  # pragma: no cover - network boundary
            return _error_response(
                message=str(exc),
                stop_reason="error",
                failure_class="internal_error",
                metadata={"provider_name": OPENAI_PROVIDER_NAME},
            )
        return _response_from_openai_payload(response_payload)

    async def stream(self, request):
        response = await self.complete(request)
        terminal = response.terminal or ModelTerminalMetadata(
            stop_reason=response.stop_reason,
            usage=dict(response.usage),
            request_id=response.request_id,
        )
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.MESSAGE_START,
            payload={"request_id": response.request_id},
            terminal=ModelTerminalMetadata(
                request_id=response.request_id,
                usage=dict(response.usage),
            ),
        )
        if response.message.text:
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_DELTA,
                payload={"text": response.message.text},
            )
        yield ModelStreamEvent(
            event_type=(
                ModelStreamEventType.ERROR
                if terminal.error is not None and not response.message.text
                else ModelStreamEventType.MESSAGE_STOP
            ),
            payload={
                "stop_reason": terminal.stop_reason,
                "usage": dict(terminal.usage),
                "request_id": terminal.request_id,
                "error": terminal.error,
                "metadata": dict(terminal.metadata),
            },
            terminal=terminal,
        )


def bundled_openai_provider_binding() -> ModelProviderBinding:
    return ModelProviderBinding(
        client=BundledOpenAIModelClient(),
        provider_name=OPENAI_PROVIDER_NAME,
        capabilities=NormalizedModelCapabilities(
            structured_tool_calls=False,
            streaming_tool_call_deltas=False,
            tool_call_finalize_boundary=False,
            parseable_tool_calls_after_message=False,
            multiple_tool_calls_per_message=False,
            abort_signal_passthrough=False,
            supports_streaming=False,
        ),
        context_window_profiles=bundled_openai_context_window_profiles(),
        metadata={
            "credential_env": "OPENAI_API_KEY",
            "base_url_env": "OPENAI_BASE_URL",
            "model_env": "OPENAI_MODEL",
            "bundled": True,
        },
    )


def bundled_openai_route_binding() -> ModelRouteBinding:
    return ModelRouteBinding(
        provider_binding=OPENAI_PROVIDER_NAME,
        default_model=DEFAULT_OPENAI_MODEL,
        provider_name=OPENAI_PROVIDER_NAME,
        context_window_policy=RouteContextWindowPolicy(
            trigger_buffer_tokens=8192,
            fallback_mode="proactive_and_reactive",
            policy_tag=OPENAI_ROUTE_NAME,
        ),
        metadata={"bundled": True, "default_model_env": "OPENAI_MODEL"},
    )


def _serialize_request_messages(
    system_prompt: str,
    messages: tuple[RuntimeMessage, ...],
) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    if system_prompt.strip():
        serialized.append({"role": "system", "content": system_prompt})
    for message in messages:
        content = message.text.strip()
        if not content:
            continue
        role = _openai_role_for_message(message.role)
        serialized.append({"role": role, "content": content})
    return serialized


def _openai_role_for_message(role: MessageRole) -> str:
    if role == MessageRole.SYSTEM:
        return "system"
    if role == MessageRole.ASSISTANT:
        return "assistant"
    return "user"


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _post_json(url: str, payload: Mapping[str, Any], *, api_key: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib_request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_error_response(exc: urllib_error.HTTPError) -> ModelResponse:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:  # pragma: no cover - defensive boundary
        payload = {}
    error_payload = payload.get("error") if isinstance(payload, Mapping) else {}
    if not isinstance(error_payload, Mapping):
        error_payload = {}
    error_message = str(error_payload.get("message") or exc.reason or "OpenAI request failed")
    error_code = str(error_payload.get("code") or "") or None
    failure_class = "internal_error"
    stop_reason = "error"
    if exc.code in {401, 403}:
        failure_class = "auth_error"
        stop_reason = "auth_error"
    elif error_code in {"context_length_exceeded", "prompt_too_long"} or exc.code == 413:
        failure_class = "context_limit"
        stop_reason = "context_limit"
    elif error_code in {"max_output_tokens", "output_limit"}:
        failure_class = "output_limit"
        stop_reason = "output_limit"
    return _error_response(
        message=error_message,
        stop_reason=stop_reason,
        failure_class=failure_class,
        metadata={
            "provider_name": OPENAI_PROVIDER_NAME,
            "provider_error_code": error_code,
            "http_status": exc.code,
            "retryable": failure_class in {"context_limit", "output_limit"},
        },
    )


def _response_from_openai_payload(payload: Mapping[str, Any]) -> ModelResponse:
    choices = payload.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    message_payload = first_choice.get("message") if isinstance(first_choice, Mapping) else {}
    if not isinstance(message_payload, Mapping):
        message_payload = {}
    content = message_payload.get("content")
    if isinstance(content, list):
        text = "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, Mapping)
        )
    else:
        text = str(content or "")
    finish_reason = str(first_choice.get("finish_reason") or "stop")
    stop_reason = "end_turn" if finish_reason == "stop" else ("output_limit" if finish_reason == "length" else finish_reason)
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    request_id = payload.get("id")
    terminal = ModelTerminalMetadata(
        stop_reason=stop_reason,
        usage=dict(usage),
        request_id=str(request_id) if request_id is not None else None,
    )
    return ModelResponse(
        message=RuntimeMessage(
            message_id=uuid4().hex,
            role=MessageRole.ASSISTANT,
            content=text,
            metadata={},
        ),
        stop_reason=stop_reason,
        usage=dict(usage),
        request_id=str(request_id) if request_id is not None else None,
        terminal=terminal,
    )


def _error_response(
    *,
    message: str,
    stop_reason: str,
    failure_class: str,
    metadata: Mapping[str, Any] | None = None,
) -> ModelResponse:
    metadata_dict = dict(metadata or {})
    terminal = ModelTerminalMetadata(
        stop_reason=stop_reason,
        error=message,
        metadata={
            "error": message,
            **metadata_dict,
            "failure_class": failure_class,
            "retryable": bool(metadata_dict.get("retryable", False)),
        },
    )
    return ModelResponse(
        message=RuntimeMessage(
            message_id=uuid4().hex,
            role=MessageRole.ASSISTANT,
            content=(),
            metadata={},
        ),
        stop_reason=stop_reason,
        terminal=terminal,
    )


__all__ = [
    "BundledOpenAIModelClient",
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_OPENAI_MODEL",
    "OPENAI_PROVIDER_NAME",
    "OPENAI_ROUTE_NAME",
    "bundled_openai_context_window_profiles",
    "bundled_openai_provider_binding",
    "bundled_openai_recovery_hints",
    "bundled_openai_route_binding",
]
