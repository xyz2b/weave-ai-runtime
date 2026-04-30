from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping
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
from .contracts import (
    ContentBlock,
    MessageRole,
    RuntimeMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from .definitions import ToolDefinition
from .runtime_kernel.config import ModelProviderBinding, ModelRouteBinding
from .turn_engine.models import (
    ModelRequest,
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

_STREAM_SENTINEL = object()
_RESTORE_OMITTED_FIELD = object()

_RoundTripPathSegment = str | int


class OpenAIAdapterError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: str = "internal_error",
        stop_reason: str = "error",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.stop_reason = stop_reason
        self.metadata = dict(metadata or {})


@dataclass(slots=True)
class _PendingFunctionCall:
    key: str
    call_id: str
    tool_name: str
    arguments_json: str = ""
    last_emitted_input: dict[str, Any] | None = None
    closed: bool = False


@dataclass(frozen=True, slots=True)
class _ParsedResponsesPayload:
    blocks: tuple[ContentBlock, ...]
    stop_reason: str
    usage: dict[str, Any]
    request_id: str | None
    terminal: ModelTerminalMetadata


@dataclass(frozen=True, slots=True)
class _RoundTripRestorationPlan:
    restore_null_to_omission: bool = False
    decode_json_object_surrogate: bool = False
    properties: dict[str, _RoundTripRestorationPlan] = field(default_factory=dict)
    array_item_plan: _RoundTripRestorationPlan | None = None


def _empty_round_trip_restoration_plan() -> _RoundTripRestorationPlan:
    return _RoundTripRestorationPlan()


@dataclass(frozen=True, slots=True)
class _NormalizedToolSchema:
    schema: dict[str, Any]
    restoration_plan: _RoundTripRestorationPlan = field(
        default_factory=_empty_round_trip_restoration_plan
    )


@dataclass(frozen=True, slots=True)
class _ResponsesFunctionToolSpec:
    name: str
    function_tool: dict[str, Any]
    restoration_plan: _RoundTripRestorationPlan = field(
        default_factory=_empty_round_trip_restoration_plan
    )


@dataclass(slots=True)
class _ResponsesStreamState:
    started: bool = False
    request_id: str | None = None
    tool_calls: dict[str, _PendingFunctionCall] = field(default_factory=dict)
    tool_specs_by_name: dict[str, _ResponsesFunctionToolSpec] = field(default_factory=dict)
    emitted_blocks: list[ContentBlock] = field(default_factory=list)
    pending_text: str = ""


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



def bundled_openai_capabilities() -> NormalizedModelCapabilities:
    return NormalizedModelCapabilities(
        structured_tool_calls=True,
        streaming_tool_call_deltas=True,
        tool_call_finalize_boundary=True,
        parseable_tool_calls_after_message=True,
        multiple_tool_calls_per_message=True,
        abort_signal_passthrough=False,
        supports_streaming=True,
    )


@dataclass(slots=True)
class BundledOpenAIModelClient:
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    model_env: str = "OPENAI_MODEL"
    normalized_model_capabilities: NormalizedModelCapabilities = field(
        default_factory=bundled_openai_capabilities,
        init=False,
        repr=False,
    )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            return _missing_credentials_response(self.api_key_env)

        model_name = request.model or os.environ.get(self.model_env, "").strip() or DEFAULT_OPENAI_MODEL
        try:
            payload, tool_specs_by_name = _build_responses_request(request, model_name=model_name)
        except OpenAIAdapterError as exc:
            return _adapter_error_response(exc)

        try:
            response_payload = await asyncio.to_thread(
                _post_json,
                _responses_url(os.environ.get(self.base_url_env, "").strip() or DEFAULT_OPENAI_BASE_URL),
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

        try:
            parsed = _parse_responses_payload(response_payload, tool_specs_by_name=tool_specs_by_name)
        except OpenAIAdapterError as exc:
            return _adapter_error_response(exc)
        return ModelResponse(
            message=RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.ASSISTANT,
                content=parsed.blocks,
                metadata={"provider_response_id": parsed.request_id} if parsed.request_id is not None else {},
            ),
            stop_reason=parsed.stop_reason,
            usage=dict(parsed.usage),
            request_id=parsed.request_id,
            terminal=parsed.terminal,
        )

    async def stream(self, request: ModelRequest):
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            yield _error_stream_event(_missing_credentials_response(self.api_key_env).terminal)
            return

        model_name = request.model or os.environ.get(self.model_env, "").strip() or DEFAULT_OPENAI_MODEL
        try:
            payload, tool_specs_by_name = _build_responses_request(request, model_name=model_name)
        except OpenAIAdapterError as exc:
            yield _error_stream_event(_adapter_error_response(exc).terminal)
            return

        stream_payload = dict(payload)
        stream_payload["stream"] = True
        iterator = _post_json_stream(
            _responses_url(os.environ.get(self.base_url_env, "").strip() or DEFAULT_OPENAI_BASE_URL),
            stream_payload,
            api_key=api_key,
        )
        state = _ResponsesStreamState(tool_specs_by_name=tool_specs_by_name)
        try:
            while True:
                event_payload = await asyncio.to_thread(_next_stream_payload, iterator)
                if event_payload is _STREAM_SENTINEL:
                    break
                assert isinstance(event_payload, Mapping)
                try:
                    async for mapped_event in _map_responses_stream_payload(
                        event_payload,
                        state=state,
                    ):
                        yield mapped_event
                except OpenAIAdapterError as exc:
                    if not state.started:
                        yield ModelStreamEvent(
                            event_type=ModelStreamEventType.MESSAGE_START,
                            payload={"request_id": state.request_id} if state.request_id is not None else {},
                        )
                        state.started = True
                    yield _error_stream_event(_adapter_error_response(exc).terminal)
                    return
        except urllib_error.HTTPError as exc:
            yield _error_stream_event(_http_error_response(exc).terminal)
            return
        except Exception as exc:  # pragma: no cover - network boundary
            yield _error_stream_event(
                ModelTerminalMetadata(
                    stop_reason="error",
                    error=str(exc),
                    metadata={
                        "provider_name": OPENAI_PROVIDER_NAME,
                        "error": str(exc),
                        "failure_class": "internal_error",
                        "retryable": False,
                    },
                )
            )
            return


def bundled_openai_provider_binding() -> ModelProviderBinding:
    return ModelProviderBinding(
        client=BundledOpenAIModelClient(),
        provider_name=OPENAI_PROVIDER_NAME,
        capabilities=bundled_openai_capabilities(),
        context_window_profiles=bundled_openai_context_window_profiles(),
        metadata={
            "credential_env": "OPENAI_API_KEY",
            "base_url_env": "OPENAI_BASE_URL",
            "model_env": "OPENAI_MODEL",
            "bundled": True,
            "transport": "responses_api",
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
        metadata={
            "bundled": True,
            "default_model_env": "OPENAI_MODEL",
            "provider_request_policy": {"parallel_tool_calls": True},
            "transport": "responses_api",
        },
        capabilities=bundled_openai_capabilities(),
    )



def _build_responses_request_payload(
    request: ModelRequest,
    *,
    model_name: str,
) -> dict[str, Any]:
    payload, _ = _build_responses_request(request, model_name=model_name)
    return payload


def _build_responses_request(
    request: ModelRequest,
    *,
    model_name: str,
) -> tuple[dict[str, Any], dict[str, _ResponsesFunctionToolSpec]]:
    payload: dict[str, Any] = {
        "model": model_name,
        "input": _serialize_request_input(request.messages),
    }
    if request.system_prompt.strip():
        payload["instructions"] = request.system_prompt
    if request.max_output_tokens is not None:
        payload["max_output_tokens"] = request.max_output_tokens
    tool_specs_by_name: dict[str, _ResponsesFunctionToolSpec] = {}
    if request.tools:
        tool_specs = tuple(_tool_definition_to_function_tool(tool) for tool in request.tools)
        payload["tools"] = [spec.function_tool for spec in tool_specs]
        payload["parallel_tool_calls"] = _provider_parallel_tool_calls_enabled(request.metadata)
        tool_specs_by_name = {spec.name: spec for spec in tool_specs}
    return payload, tool_specs_by_name


def _provider_parallel_tool_calls_enabled(metadata: Mapping[str, Any] | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    raw_policy = metadata.get("provider_request_policy")
    if not isinstance(raw_policy, Mapping):
        return False
    value = raw_policy.get("parallel_tool_calls")
    if isinstance(value, bool):
        return value
    return False


def _serialize_request_input(messages: Iterable[RuntimeMessage]) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    for message in messages:
        role = _responses_role_for_message(message.role)
        buffered_text: list[str] = []

        def flush_text() -> None:
            if not buffered_text:
                return
            text = "".join(buffered_text)
            buffered_text.clear()
            if not text:
                return
            content_type = "output_text" if role == "assistant" else "input_text"
            item: dict[str, Any] = {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": text}],
            }
            if role == "assistant":
                item["status"] = "completed"
            input_items.append(item)

        for block in message.content:
            text = _content_block_text(block)
            if text is not None:
                buffered_text.append(text)
                continue
            if isinstance(block, ToolUseBlock):
                flush_text()
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": block.tool_use_id,
                        "name": block.name,
                        "arguments": _json_dumps(block.input),
                        "status": "completed",
                    }
                )
                continue
            if isinstance(block, ToolResultBlock):
                flush_text()
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.tool_use_id,
                        "output": _serialize_tool_result_output(block),
                    }
                )
        flush_text()
    return input_items



def _content_block_text(block: ContentBlock) -> str | None:
    if isinstance(block, TextBlock):
        return block.text
    return None



def _responses_role_for_message(role: MessageRole) -> str:
    if role == MessageRole.SYSTEM:
        return "system"
    if role == MessageRole.ASSISTANT:
        return "assistant"
    return "user"



def _tool_definition_to_function_tool(tool: ToolDefinition) -> _ResponsesFunctionToolSpec:
    normalized = _normalize_tool_schema(tool)
    function_tool = {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": normalized.schema,
        "strict": True,
    }
    return _ResponsesFunctionToolSpec(
        name=tool.name,
        function_tool=function_tool,
        restoration_plan=normalized.restoration_plan,
    )



def _normalize_tool_schema(tool: ToolDefinition) -> _NormalizedToolSchema:
    schema = tool.input_schema
    if not isinstance(schema, Mapping) or not schema:
        raise OpenAIAdapterError(
            f"Tool '{tool.name}' must declare an object input_schema for the bundled OpenAI route.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "tool_name": tool.name,
                "schema_path": "$.input_schema",
            },
        )
    normalized = _normalize_schema_node(
        schema,
        path="$.input_schema",
        required=True,
        tool_name=tool.name,
    )
    normalized_types = _coerce_schema_types(
        normalized.schema.get("type"),
        path="$.input_schema",
        tool_name=tool.name,
    )
    if "object" not in normalized_types:
        raise OpenAIAdapterError(
            f"Tool '{tool.name}' input_schema must resolve to an object for Responses function tools.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "tool_name": tool.name,
                "schema_path": "$.input_schema.type",
            },
        )
    return normalized



def _normalize_schema_node(
    schema: Mapping[str, Any],
    *,
    path: str,
    required: bool,
    tool_name: str,
) -> _NormalizedToolSchema:
    if not isinstance(schema, Mapping):
        raise OpenAIAdapterError(
            f"Tool '{tool_name}' schema at {path} must be an object.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "tool_name": tool_name,
                "schema_path": path,
            },
        )

    normalized = {
        str(key): value
        for key, value in schema.items()
        if key not in {"$schema", "definitions", "$defs"}
    }
    types = _coerce_schema_types(schema.get("type"), path=path, tool_name=tool_name)
    if not types:
        if "properties" in schema or "additionalProperties" in schema:
            types = ["object"]
        elif "items" in schema:
            types = ["array"]
        else:
            raise OpenAIAdapterError(
                f"Tool '{tool_name}' schema at {path} must declare a JSON Schema type.",
                failure_class="tool_schema_error",
                metadata={
                    "provider_name": OPENAI_PROVIDER_NAME,
                    "tool_name": tool_name,
                    "schema_path": path,
                },
            )

    if "object" in types:
        restore_null_to_omission = not required and "null" not in types
        properties = schema.get("properties") or {}
        if not isinstance(properties, Mapping):
            raise OpenAIAdapterError(
                f"Tool '{tool_name}' object schema at {path} must declare object properties.",
                failure_class="tool_schema_error",
                metadata={
                    "provider_name": OPENAI_PROVIDER_NAME,
                    "tool_name": tool_name,
                    "schema_path": f"{path}.properties",
                },
            )
        additional_properties = schema.get("additionalProperties")
        if not properties and additional_properties is not False:
            return _NormalizedToolSchema(
                schema=_open_object_surrogate_schema(schema, required=required),
                restoration_plan=_RoundTripRestorationPlan(
                    restore_null_to_omission=restore_null_to_omission,
                    decode_json_object_surrogate=True,
                ),
            )
        declared_required = {
            str(name)
            for name in tuple(schema.get("required") or ())
            if isinstance(name, str) and name
        }
        normalized_properties: dict[str, Any] = {}
        restoration_properties: dict[str, _RoundTripRestorationPlan] = {}
        for property_name, property_schema in properties.items():
            name = str(property_name)
            normalized_property = _normalize_schema_node(
                property_schema,
                path=f"{path}.properties.{name}",
                required=name in declared_required,
                tool_name=tool_name,
            )
            normalized_properties[name] = normalized_property.schema
            restoration_properties[name] = normalized_property.restoration_plan
        if isinstance(additional_properties, Mapping):
            raise OpenAIAdapterError(
                (
                    f"Tool '{tool_name}' schema at {path} cannot use schema-valued "
                    "additionalProperties with the bundled OpenAI Responses adapter."
                ),
                failure_class="tool_schema_error",
                metadata={
                    "provider_name": OPENAI_PROVIDER_NAME,
                    "tool_name": tool_name,
                    "schema_path": f"{path}.additionalProperties",
                },
            )
        normalized["type"] = _apply_optional_nullable(types, required=required)
        normalized["properties"] = normalized_properties
        normalized["required"] = list(normalized_properties)
        normalized["additionalProperties"] = False
        return _NormalizedToolSchema(
            schema=normalized,
            restoration_plan=_RoundTripRestorationPlan(
                restore_null_to_omission=restore_null_to_omission,
                properties=restoration_properties,
            ),
        )

    if "array" in types:
        restore_null_to_omission = not required and "null" not in types
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise OpenAIAdapterError(
                f"Tool '{tool_name}' array schema at {path} must declare an item schema.",
                failure_class="tool_schema_error",
                metadata={
                    "provider_name": OPENAI_PROVIDER_NAME,
                    "tool_name": tool_name,
                    "schema_path": f"{path}.items",
                },
            )
        normalized_items = _normalize_schema_node(
            items,
            path=f"{path}.items",
            required=True,
            tool_name=tool_name,
        )
        normalized["type"] = _apply_optional_nullable(types, required=required)
        normalized["items"] = normalized_items.schema
        return _NormalizedToolSchema(
            schema=normalized,
            restoration_plan=_RoundTripRestorationPlan(
                restore_null_to_omission=restore_null_to_omission,
                array_item_plan=normalized_items.restoration_plan,
            ),
        )

    normalized["type"] = _apply_optional_nullable(types, required=required)
    return _NormalizedToolSchema(
        schema=normalized,
        restoration_plan=_RoundTripRestorationPlan(
            restore_null_to_omission=not required and "null" not in types
        ),
    )



def _coerce_schema_types(raw_type: object, *, path: str, tool_name: str) -> list[str]:
    if raw_type is None:
        return []
    if isinstance(raw_type, str):
        stripped = raw_type.strip()
        if stripped:
            return [stripped]
        return []
    if isinstance(raw_type, (list, tuple)):
        normalized: list[str] = []
        for item in raw_type:
            if not isinstance(item, str):
                raise OpenAIAdapterError(
                    f"Tool '{tool_name}' schema type at {path} must contain only strings.",
                    failure_class="tool_schema_error",
                    metadata={
                        "provider_name": OPENAI_PROVIDER_NAME,
                        "tool_name": tool_name,
                        "schema_path": path,
                    },
                )
            stripped = item.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized
    raise OpenAIAdapterError(
        f"Tool '{tool_name}' schema type at {path} must be a string or string array.",
        failure_class="tool_schema_error",
        metadata={
            "provider_name": OPENAI_PROVIDER_NAME,
            "tool_name": tool_name,
            "schema_path": path,
        },
    )



def _apply_optional_nullable(types: list[str], *, required: bool) -> str | list[str]:
    resolved = list(types)
    if not required and "null" not in resolved:
        resolved.append("null")
    if len(resolved) == 1:
        return resolved[0]
    return resolved



def _serialize_tool_result_output(block: ToolResultBlock) -> str:
    payload: Any = block.content
    if block.is_error:
        payload = {"is_error": True, "content": block.content}
    if isinstance(payload, str) and not block.is_error:
        return payload
    return _json_dumps(payload)



def _parse_responses_payload(
    payload: Mapping[str, Any],
    *,
    tool_specs_by_name: Mapping[str, _ResponsesFunctionToolSpec] | None = None,
) -> _ParsedResponsesPayload:
    if not isinstance(payload, Mapping):
        raise OpenAIAdapterError(
            "OpenAI Responses payload must be a JSON object.",
            metadata={"provider_name": OPENAI_PROVIDER_NAME},
        )

    request_id = _string_value(payload.get("id"))
    usage = _mapping_value(payload.get("usage"))
    status = _string_value(payload.get("status")) or "completed"
    output_items = payload.get("output")
    if not isinstance(output_items, list):
        output_items = []

    if status == "failed" or isinstance(payload.get("error"), Mapping):
        raise _payload_error(payload)

    blocks: list[ContentBlock] = []
    has_tool_calls = False
    for index, item in enumerate(output_items):
        if not isinstance(item, Mapping):
            continue
        item_type = _string_value(item.get("type")) or ""
        if item_type == "message":
            blocks.extend(_content_blocks_from_response_message(item))
            continue
        if item_type == "function_call":
            blocks.append(
                _tool_use_block_from_response_item(
                    item,
                    index=index,
                    tool_specs_by_name=tool_specs_by_name,
                )
            )
            has_tool_calls = True
            continue

    stop_reason = _stop_reason_from_payload(payload, has_tool_calls=has_tool_calls)
    terminal_metadata = {
        "provider_name": OPENAI_PROVIDER_NAME,
        "provider_response_id": request_id,
        "response_status": status,
    }
    incomplete_reason = _string_value(_mapping_value(payload.get("incomplete_details")).get("reason"))
    if incomplete_reason is not None:
        terminal_metadata["incomplete_reason"] = incomplete_reason
    terminal = ModelTerminalMetadata(
        stop_reason=stop_reason,
        usage=dict(usage),
        request_id=request_id,
        metadata=terminal_metadata,
    )
    return _ParsedResponsesPayload(
        blocks=tuple(blocks),
        stop_reason=stop_reason,
        usage=dict(usage),
        request_id=request_id,
        terminal=terminal,
    )



def _content_blocks_from_response_message(item: Mapping[str, Any]) -> list[ContentBlock]:
    content = item.get("content")
    if isinstance(content, str):
        return [TextBlock(text=content)] if content else []
    if not isinstance(content, list):
        return []

    blocks: list[ContentBlock] = []
    for entry in content:
        if not isinstance(entry, Mapping):
            continue
        entry_type = _string_value(entry.get("type")) or ""
        if entry_type in {"output_text", "input_text", "text"}:
            text = _string_value(entry.get("text")) or ""
            if text:
                blocks.append(TextBlock(text=text))
            continue
        if entry_type == "refusal":
            refusal = _string_value(entry.get("refusal")) or _string_value(entry.get("text")) or ""
            if refusal:
                blocks.append(TextBlock(text=refusal))
    return blocks



def _tool_use_block_from_response_item(
    item: Mapping[str, Any],
    *,
    index: int,
    tool_specs_by_name: Mapping[str, _ResponsesFunctionToolSpec] | None = None,
) -> ToolUseBlock:
    call_id = _string_value(item.get("call_id")) or _string_value(item.get("id")) or f"call-{index}"
    tool_name = _string_value(item.get("name"))
    if tool_name is None:
        raise OpenAIAdapterError(
            "OpenAI Responses function_call item is missing a tool name.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
            },
        )
    tool_spec = tool_specs_by_name.get(tool_name) if tool_specs_by_name is not None else None
    tool_input = _parse_function_call_arguments(
        item.get("arguments"),
        call_id=call_id,
        tool_name=tool_name,
        restoration_plan=tool_spec.restoration_plan if tool_spec is not None else None,
    )
    return ToolUseBlock(tool_use_id=call_id, name=tool_name, input=tool_input)



def _parse_function_call_arguments(
    raw_arguments: object,
    *,
    call_id: str,
    tool_name: str,
    restoration_plan: _RoundTripRestorationPlan | None = None,
) -> dict[str, Any]:
    plan = restoration_plan or _RoundTripRestorationPlan()
    if raw_arguments in (None, ""):
        return {}
    if isinstance(raw_arguments, Mapping):
        return _restore_tool_input_payload(
            {str(key): value for key, value in raw_arguments.items()},
            tool_name=tool_name,
            call_id=call_id,
            restoration_plan=plan,
        )
    if not isinstance(raw_arguments, str):
        raise OpenAIAdapterError(
            f"OpenAI function call '{tool_name}' returned non-string arguments.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
                "tool_name": tool_name,
            },
        )
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise OpenAIAdapterError(
            f"OpenAI function call '{tool_name}' returned invalid JSON arguments: {exc.msg}.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
                "tool_name": tool_name,
                "raw_arguments": raw_arguments,
            },
        ) from exc
    if not isinstance(parsed, Mapping):
        raise OpenAIAdapterError(
            f"OpenAI function call '{tool_name}' returned a non-object argument payload.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
                "tool_name": tool_name,
                "raw_arguments": raw_arguments,
            },
        )
    return _restore_tool_input_payload(
        {str(key): value for key, value in parsed.items()},
        tool_name=tool_name,
        call_id=call_id,
        restoration_plan=plan,
    )



def _stop_reason_from_payload(payload: Mapping[str, Any], *, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_use"
    status = _string_value(payload.get("status")) or "completed"
    if status == "incomplete":
        reason = _string_value(_mapping_value(payload.get("incomplete_details")).get("reason"))
        if reason == "max_output_tokens":
            return "output_limit"
        return reason or "incomplete"
    return "end_turn"



def _payload_error(payload: Mapping[str, Any]) -> OpenAIAdapterError:
    error_payload = _mapping_value(payload.get("error"))
    incomplete_details = _mapping_value(payload.get("incomplete_details"))
    message = (
        _string_value(error_payload.get("message"))
        or _string_value(incomplete_details.get("reason"))
        or "OpenAI Responses request failed"
    )
    error_code = _string_value(error_payload.get("code"))
    error_type = _string_value(error_payload.get("type"))
    request_id = _string_value(payload.get("id"))
    incomplete_reason = _string_value(incomplete_details.get("reason"))
    failure_class, stop_reason, retryable = _classify_failure(
        message,
        error_code=error_code,
        error_type=error_type,
        http_status=None,
        incomplete_reason=incomplete_reason,
    )
    metadata = {
        "provider_name": OPENAI_PROVIDER_NAME,
        "provider_response_id": request_id,
        "provider_error_code": error_code,
        "provider_error_type": error_type,
        "retryable": retryable,
    }
    if incomplete_reason is not None:
        metadata["incomplete_reason"] = incomplete_reason
    return OpenAIAdapterError(
        message,
        failure_class=failure_class,
        stop_reason=stop_reason,
        metadata=metadata,
    )


async def _map_responses_stream_payload(
    payload: Mapping[str, Any],
    *,
    state: _ResponsesStreamState,
):
    event_type = _string_value(payload.get("type")) or ""

    if event_type == "response.created":
        request_id = _string_value(_mapping_value(payload.get("response")).get("id"))
        state.request_id = request_id or state.request_id
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        return

    if event_type == "response.output_text.delta":
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        delta = _string_value(payload.get("delta")) or ""
        if delta:
            state.pending_text += delta
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_DELTA,
                payload={"text": delta},
            )
        return

    if event_type == "response.output_item.added":
        item = _mapping_value(payload.get("item"))
        item_type = _string_value(item.get("type")) or ""
        if item_type != "function_call":
            return
        _finalize_stream_text_block(state)
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        pending = _pending_function_call_from_item(item, payload)
        state.tool_calls[pending.key] = pending
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.CONTENT_BLOCK_START,
            block_id=pending.call_id,
            block_type="tool_use",
            payload={
                "block_type": "tool_use",
                "tool_use_id": pending.call_id,
                "name": pending.tool_name,
                "input": {},
            },
        )
        return

    if event_type == "response.function_call_arguments.delta":
        pending = _resolve_pending_function_call(state, payload)
        if pending is None:
            return
        pending.arguments_json += _string_value(payload.get("delta")) or ""
        parsed_input = _try_parse_partial_arguments(pending.arguments_json)
        if parsed_input is None:
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_BLOCK_DELTA,
                block_id=pending.call_id,
                block_type="tool_use",
                payload={
                    "block_type": "tool_use",
                    "tool_use_id": pending.call_id,
                    "name": pending.tool_name,
                    "argument_delta": _string_value(payload.get("delta")) or "",
                },
            )
            return
        tool_spec = state.tool_specs_by_name.get(pending.tool_name)
        restored_input = _restore_tool_input_payload(
            parsed_input,
            tool_name=pending.tool_name,
            call_id=pending.call_id,
            restoration_plan=tool_spec.restoration_plan if tool_spec is not None else _RoundTripRestorationPlan(),
        )
        pending.last_emitted_input = restored_input
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.CONTENT_BLOCK_DELTA,
            block_id=pending.call_id,
            block_type="tool_use",
            payload={
                "block_type": "tool_use",
                "tool_use_id": pending.call_id,
                "name": pending.tool_name,
                "input": restored_input,
                "argument_delta": _string_value(payload.get("delta")) or "",
            },
        )
        return

    if event_type == "response.function_call_arguments.done":
        pending = _resolve_pending_function_call(state, payload)
        if pending is None or pending.closed:
            return
        pending.arguments_json = _string_value(payload.get("arguments")) or pending.arguments_json
        tool_spec = state.tool_specs_by_name.get(pending.tool_name)
        final_input = _parse_function_call_arguments(
            pending.arguments_json,
            call_id=pending.call_id,
            tool_name=pending.tool_name,
            restoration_plan=tool_spec.restoration_plan if tool_spec is not None else None,
        )
        pending.last_emitted_input = final_input
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.CONTENT_BLOCK_DELTA,
            block_id=pending.call_id,
            block_type="tool_use",
            payload={
                "block_type": "tool_use",
                "tool_use_id": pending.call_id,
                "name": pending.tool_name,
                "input": final_input,
            },
        )
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.CONTENT_BLOCK_STOP,
            block_id=pending.call_id,
            block_type="tool_use",
            payload={
                "block_type": "tool_use",
                "tool_use_id": pending.call_id,
            },
        )
        state.emitted_blocks.append(
            ToolUseBlock(tool_use_id=pending.call_id, name=pending.tool_name, input=dict(final_input))
        )
        pending.closed = True
        return

    if event_type == "response.output_item.done":
        item = _mapping_value(payload.get("item"))
        item_type = _string_value(item.get("type")) or ""
        if item_type != "function_call":
            return
        pending = _resolve_pending_function_call(state, payload, item=item)
        if pending is None:
            pending = _pending_function_call_from_item(item, payload)
            state.tool_calls[pending.key] = pending
        if pending.closed:
            return
        if not pending.arguments_json:
            pending.arguments_json = _string_value(item.get("arguments")) or ""
        tool_spec = state.tool_specs_by_name.get(pending.tool_name)
        final_input = _parse_function_call_arguments(
            pending.arguments_json,
            call_id=pending.call_id,
            tool_name=pending.tool_name,
            restoration_plan=tool_spec.restoration_plan if tool_spec is not None else None,
        )
        if pending.last_emitted_input != final_input:
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_BLOCK_DELTA,
                block_id=pending.call_id,
                block_type="tool_use",
                payload={
                    "block_type": "tool_use",
                    "tool_use_id": pending.call_id,
                    "name": pending.tool_name,
                    "input": final_input,
                },
            )
        state.emitted_blocks.append(
            ToolUseBlock(tool_use_id=pending.call_id, name=pending.tool_name, input=dict(final_input))
        )
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.CONTENT_BLOCK_STOP,
            block_id=pending.call_id,
            block_type="tool_use",
            payload={
                "block_type": "tool_use",
                "tool_use_id": pending.call_id,
            },
        )
        pending.closed = True
        return

    if event_type == "response.completed":
        response_payload = _mapping_value(payload.get("response"))
        parsed = _parse_responses_payload(
            response_payload,
            tool_specs_by_name=state.tool_specs_by_name,
        )
        state.request_id = parsed.request_id or state.request_id
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        async for fallback_event in _emit_completed_stream_block_fallbacks(state, parsed.blocks):
            yield fallback_event
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.MESSAGE_STOP,
            payload={
                "stop_reason": parsed.stop_reason,
                "usage": dict(parsed.usage),
                "request_id": parsed.request_id,
                "metadata": dict(parsed.terminal.metadata),
            },
            terminal=parsed.terminal,
        )
        return

    if event_type == "response.incomplete":
        response_payload = _mapping_value(payload.get("response"))
        parsed = _parse_responses_payload(
            response_payload,
            tool_specs_by_name=state.tool_specs_by_name,
        )
        state.request_id = parsed.request_id or state.request_id
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        async for fallback_event in _emit_completed_stream_block_fallbacks(state, parsed.blocks):
            yield fallback_event
        yield ModelStreamEvent(
            event_type=ModelStreamEventType.MESSAGE_STOP,
            payload={
                "stop_reason": parsed.stop_reason,
                "usage": dict(parsed.usage),
                "request_id": parsed.request_id,
                "metadata": dict(parsed.terminal.metadata),
            },
            terminal=parsed.terminal,
        )
        return

    if event_type == "response.failed":
        response_payload = _mapping_value(payload.get("response"))
        terminal = _adapter_error_response(_payload_error(response_payload)).terminal
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        yield _error_stream_event(terminal)
        return

    if event_type == "error":
        error_payload = _mapping_value(payload.get("error"))
        message = _string_value(error_payload.get("message")) or "OpenAI stream failed"
        failure_class, stop_reason, retryable = _classify_failure(
            message,
            error_code=_string_value(error_payload.get("code")),
            error_type=_string_value(error_payload.get("type")),
            http_status=None,
            incomplete_reason=None,
        )
        terminal = ModelTerminalMetadata(
            stop_reason=stop_reason,
            request_id=state.request_id,
            error=message,
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "error": message,
                "failure_class": failure_class,
                "retryable": retryable,
                "provider_error_code": _string_value(error_payload.get("code")),
                "provider_error_type": _string_value(error_payload.get("type")),
            },
        )
        if not state.started:
            state.started = True
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.MESSAGE_START,
                payload={"request_id": state.request_id} if state.request_id is not None else {},
                terminal=ModelTerminalMetadata(request_id=state.request_id),
            )
        yield _error_stream_event(terminal)



def _pending_function_call_from_item(
    item: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> _PendingFunctionCall:
    key = _stream_item_key(payload, item=item)
    call_id = _string_value(item.get("call_id")) or _string_value(item.get("id")) or key
    tool_name = _string_value(item.get("name"))
    if tool_name is None:
        raise OpenAIAdapterError(
            "OpenAI function_call stream item is missing a tool name.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
            },
        )
    return _PendingFunctionCall(
        key=key,
        call_id=call_id,
        tool_name=tool_name,
        arguments_json=_string_value(item.get("arguments")) or "",
    )



def _resolve_pending_function_call(
    state: _ResponsesStreamState,
    payload: Mapping[str, Any],
    *,
    item: Mapping[str, Any] | None = None,
) -> _PendingFunctionCall | None:
    key = _stream_item_key(payload, item=item)
    pending = state.tool_calls.get(key)
    if pending is not None:
        return pending
    if item is not None:
        call_id = _string_value(item.get("call_id"))
        if call_id is not None:
            for candidate in state.tool_calls.values():
                if candidate.call_id == call_id:
                    return candidate
    return None



def _stream_item_key(payload: Mapping[str, Any], *, item: Mapping[str, Any] | None = None) -> str:
    for candidate in (
        payload.get("item_id"),
        item.get("id") if item is not None else None,
        item.get("call_id") if item is not None else None,
        payload.get("output_index"),
    ):
        value = _string_value(candidate)
        if value is not None:
            return value
    return uuid4().hex



def _try_parse_partial_arguments(raw_arguments: str) -> dict[str, Any] | None:
    if not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    return {str(key): value for key, value in parsed.items()}



def _open_object_surrogate_schema(schema: Mapping[str, Any], *, required: bool) -> dict[str, Any]:
    surrogate = {
        str(key): value
        for key, value in schema.items()
        if key not in {"$schema", "definitions", "$defs", "properties", "required", "additionalProperties"}
    }
    surrogate["type"] = _apply_optional_nullable(["string"], required=required)
    existing_description = _string_value(schema.get("description")) or ""
    guidance = "Pass a JSON object encoded as a string."
    surrogate["description"] = guidance if not existing_description else f"{existing_description} {guidance}"
    return surrogate


def _restore_tool_input_payload(
    payload: dict[str, Any],
    *,
    tool_name: str,
    call_id: str,
    restoration_plan: _RoundTripRestorationPlan,
) -> dict[str, Any]:
    restored = _restore_round_trip_value(
        payload,
        restoration_plan=restoration_plan,
        path=(),
        tool_name=tool_name,
        call_id=call_id,
    )
    if restored is _RESTORE_OMITTED_FIELD or not isinstance(restored, Mapping):
        return {}
    return {str(key): value for key, value in restored.items()}


def _restore_round_trip_value(
    value: Any,
    *,
    restoration_plan: _RoundTripRestorationPlan,
    path: tuple[_RoundTripPathSegment, ...],
    tool_name: str,
    call_id: str,
) -> Any:
    if value is None and restoration_plan.restore_null_to_omission:
        return _RESTORE_OMITTED_FIELD
    if restoration_plan.decode_json_object_surrogate:
        value = _decode_json_object_surrogate_value(
            value,
            path=path,
            tool_name=tool_name,
            call_id=call_id,
        )
    if isinstance(value, Mapping):
        restored = {str(key): inner for key, inner in value.items()}
        for key, child_plan in restoration_plan.properties.items():
            if key not in restored:
                continue
            restored_value = _restore_round_trip_value(
                restored[key],
                restoration_plan=child_plan,
                path=path + (key,),
                tool_name=tool_name,
                call_id=call_id,
            )
            if restored_value is _RESTORE_OMITTED_FIELD:
                restored.pop(key, None)
                continue
            restored[key] = restored_value
        return restored
    if isinstance(value, list) and restoration_plan.array_item_plan is not None:
        restored_items: list[Any] = []
        for index, item in enumerate(value):
            restored_item = _restore_round_trip_value(
                item,
                restoration_plan=restoration_plan.array_item_plan,
                path=path + (index,),
                tool_name=tool_name,
                call_id=call_id,
            )
            if restored_item is _RESTORE_OMITTED_FIELD:
                restored_items.append(None)
                continue
            restored_items.append(restored_item)
        return restored_items
    return value


def _decode_json_object_surrogate_value(
    value: Any,
    *,
    path: tuple[_RoundTripPathSegment, ...],
    tool_name: str,
    call_id: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): inner for key, inner in value.items()}
    formatted_path = _format_round_trip_path(path)
    if not isinstance(value, str):
        raise OpenAIAdapterError(
            (
                f"OpenAI function call '{tool_name}' returned a non-string JSON-object surrogate "
                f"for '{formatted_path}'."
            ),
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
                "tool_name": tool_name,
                "schema_path": formatted_path,
                "raw_value": value,
            },
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise OpenAIAdapterError(
            f"OpenAI function call '{tool_name}' returned invalid JSON for '{formatted_path}': {exc.msg}.",
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
                "tool_name": tool_name,
                "schema_path": formatted_path,
                "raw_value": value,
            },
        ) from exc
    if not isinstance(parsed, Mapping):
        raise OpenAIAdapterError(
            (
                f"OpenAI function call '{tool_name}' returned a non-object JSON payload "
                f"for '{formatted_path}'."
            ),
            failure_class="tool_schema_error",
            metadata={
                "provider_name": OPENAI_PROVIDER_NAME,
                "provider_call_id": call_id,
                "tool_name": tool_name,
                "schema_path": formatted_path,
                "raw_value": value,
            },
        )
    return {str(key): inner for key, inner in parsed.items()}


def _format_round_trip_path(path: tuple[_RoundTripPathSegment, ...]) -> str:
    if not path:
        return "$"
    formatted = ""
    for segment in path:
        if isinstance(segment, int):
            formatted = f"{formatted}[{segment}]"
            continue
        if not formatted:
            formatted = segment
            continue
        formatted = f"{formatted}.{segment}"
    return formatted


def _finalize_stream_text_block(state: _ResponsesStreamState) -> None:
    if not state.pending_text:
        return
    state.emitted_blocks.append(TextBlock(text=state.pending_text))
    state.pending_text = ""


def _observed_stream_blocks(state: _ResponsesStreamState) -> tuple[ContentBlock, ...]:
    if not state.pending_text:
        return tuple(state.emitted_blocks)
    return tuple(state.emitted_blocks) + (TextBlock(text=state.pending_text),)


def _missing_stream_blocks(
    state: _ResponsesStreamState,
    final_blocks: tuple[ContentBlock, ...],
) -> tuple[ContentBlock, ...]:
    observed = _observed_stream_blocks(state)
    if len(observed) > len(final_blocks):
        return ()
    for observed_block, final_block in zip(observed, final_blocks):
        if observed_block != final_block:
            return ()
    return final_blocks[len(observed) :]


async def _emit_completed_stream_block_fallbacks(
    state: _ResponsesStreamState,
    final_blocks: tuple[ContentBlock, ...],
):
    for block in _missing_stream_blocks(state, final_blocks):
        if isinstance(block, TextBlock) and block.text:
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_DELTA,
                payload={"text": block.text},
            )
            continue
        if isinstance(block, ToolUseBlock):
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_BLOCK_START,
                block_id=block.tool_use_id,
                block_type="tool_use",
                payload={
                    "block_type": "tool_use",
                    "tool_use_id": block.tool_use_id,
                    "name": block.name,
                    "input": {},
                },
            )
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_BLOCK_DELTA,
                block_id=block.tool_use_id,
                block_type="tool_use",
                payload={
                    "block_type": "tool_use",
                    "tool_use_id": block.tool_use_id,
                    "name": block.name,
                    "input": dict(block.input),
                },
            )
            yield ModelStreamEvent(
                event_type=ModelStreamEventType.CONTENT_BLOCK_STOP,
                block_id=block.tool_use_id,
                block_type="tool_use",
                payload={
                    "block_type": "tool_use",
                    "tool_use_id": block.tool_use_id,
                },
            )


def _responses_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/responses"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/responses"
    return f"{normalized}/v1/responses"



def _post_json(url: str, payload: Mapping[str, Any], *, api_key: str) -> dict[str, Any]:
    data = _json_dumps(payload).encode("utf-8")
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



def _post_json_stream(url: str, payload: Mapping[str, Any], *, api_key: str) -> Iterator[dict[str, Any]]:
    data = _json_dumps(payload).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    with urllib_request.urlopen(request, timeout=60) as response:
        yield from _iter_sse_payloads(response)



def _iter_sse_payloads(response) -> Iterator[dict[str, Any]]:
    event_name: str | None = None
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8")
        line = line.rstrip("\n")
        line = line.rstrip("\r")
        if not line:
            payload = _flush_sse_payload(event_name, data_lines)
            if payload is not None:
                yield payload
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value
            continue
        if field == "data":
            data_lines.append(value)
    payload = _flush_sse_payload(event_name, data_lines)
    if payload is not None:
        yield payload



def _flush_sse_payload(event_name: str | None, data_lines: list[str]) -> dict[str, Any] | None:
    if not data_lines:
        return None
    data = "\n".join(data_lines)
    if data == "[DONE]":
        return None
    payload = json.loads(data)
    if isinstance(payload, dict) and event_name and "type" not in payload:
        payload = {"type": event_name, **payload}
    if not isinstance(payload, dict):
        raise OpenAIAdapterError(
            "OpenAI stream emitted a non-object event payload.",
            metadata={"provider_name": OPENAI_PROVIDER_NAME},
        )
    return payload



def _next_stream_payload(iterator: Iterator[dict[str, Any]]) -> object:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_SENTINEL



def _http_error_response(exc: urllib_error.HTTPError) -> ModelResponse:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:  # pragma: no cover - defensive boundary
        payload = {}
    error_payload = payload.get("error") if isinstance(payload, Mapping) else {}
    if not isinstance(error_payload, Mapping):
        error_payload = {}
    error_message = str(error_payload.get("message") or exc.reason or "OpenAI request failed")
    error_code = _string_value(error_payload.get("code"))
    error_type = _string_value(error_payload.get("type"))
    failure_class, stop_reason, retryable = _classify_failure(
        error_message,
        error_code=error_code,
        error_type=error_type,
        http_status=exc.code,
        incomplete_reason=None,
    )
    return _error_response(
        message=error_message,
        stop_reason=stop_reason,
        failure_class=failure_class,
        metadata={
            "provider_name": OPENAI_PROVIDER_NAME,
            "provider_error_code": error_code,
            "provider_error_type": error_type,
            "http_status": exc.code,
            "retryable": retryable,
        },
    )



def _classify_failure(
    message: str,
    *,
    error_code: str | None,
    error_type: str | None,
    http_status: int | None,
    incomplete_reason: str | None,
) -> tuple[str, str, bool]:
    lower_message = message.lower()
    code = (error_code or "").lower()
    provider_type = (error_type or "").lower()

    if http_status in {401, 403} or provider_type == "invalid_api_key_error" or "api key" in lower_message:
        return "auth_error", "auth_error", False
    if (
        http_status == 413
        or code in {"context_length_exceeded", "prompt_too_long"}
        or "context length" in lower_message
        or "prompt is too long" in lower_message
    ):
        return "context_limit", "context_limit", True
    if incomplete_reason == "max_output_tokens" or code in {"max_output_tokens", "output_limit"}:
        return "output_limit", "output_limit", True
    if (
        http_status == 429
        or provider_type == "rate_limit_error"
        or code in {"rate_limit_exceeded", "server_overloaded", "overloaded"}
        or "rate limit" in lower_message
        or "overloaded" in lower_message
    ):
        return "provider_overload", "provider_overload", True
    if "schema" in lower_message or "additionalproperties" in lower_message or "function tool" in lower_message:
        return "tool_schema_error", "error", False
    return "internal_error", "error", False



def _missing_credentials_response(credential_env: str) -> ModelResponse:
    return _error_response(
        message=(
            f"Bundled OpenAI route '{OPENAI_ROUTE_NAME}' requires {credential_env} "
            "or an explicit host override."
        ),
        stop_reason="auth_error",
        failure_class="auth_error",
        metadata={
            "configuration_error": True,
            "credential_env": credential_env,
            "provider_name": OPENAI_PROVIDER_NAME,
        },
    )



def _adapter_error_response(exc: OpenAIAdapterError) -> ModelResponse:
    metadata = {"provider_name": OPENAI_PROVIDER_NAME, **dict(exc.metadata)}
    return _error_response(
        message=str(exc),
        stop_reason=exc.stop_reason,
        failure_class=exc.failure_class,
        metadata=metadata,
    )



def _error_stream_event(terminal: ModelTerminalMetadata | None) -> ModelStreamEvent:
    resolved_terminal = terminal or ModelTerminalMetadata(
        stop_reason="error",
        error="OpenAI request failed",
        metadata={
            "provider_name": OPENAI_PROVIDER_NAME,
            "error": "OpenAI request failed",
            "failure_class": "internal_error",
            "retryable": False,
        },
    )
    payload = {
        "stop_reason": resolved_terminal.stop_reason,
        "request_id": resolved_terminal.request_id,
        "usage": dict(resolved_terminal.usage),
        "error": resolved_terminal.error,
        "metadata": dict(resolved_terminal.metadata),
    }
    return ModelStreamEvent(
        event_type=ModelStreamEventType.ERROR,
        payload=payload,
        terminal=resolved_terminal,
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



def _mapping_value(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): inner for key, inner in value.items()}



def _string_value(value: object) -> str | None:
    if value is None:
        return None
    return str(value)



def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


__all__ = [
    "BundledOpenAIModelClient",
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_OPENAI_MODEL",
    "OPENAI_PROVIDER_NAME",
    "OPENAI_ROUTE_NAME",
    "bundled_openai_capabilities",
    "bundled_openai_context_window_profiles",
    "bundled_openai_provider_binding",
    "bundled_openai_recovery_hints",
    "bundled_openai_route_binding",
]
