from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .contracts import PromptContextEnvelope, RuntimePrivateContext

if TYPE_CHECKING:
    from .runtime_services import RuntimeServices


@dataclass(frozen=True, slots=True)
class RuntimeControlPlaneContext:
    runtime_services: "RuntimeServices"
    permission_context: Any = None
    prompt_context: PromptContextEnvelope = field(default_factory=PromptContextEnvelope)
    private_context: RuntimePrivateContext = field(default_factory=RuntimePrivateContext)

    @property
    def host_runtime(self) -> Any:
        return self.runtime_services.host

    @property
    def hook_bus(self) -> Any:
        return self.runtime_services.hook_bus


def resolve_runtime_services(runtime_context: Any) -> Any | None:
    return getattr(runtime_context, "runtime_services", None)


def resolve_host_runtime(runtime_context: Any) -> Any | None:
    runtime_services = resolve_runtime_services(runtime_context)
    if runtime_services is not None:
        return getattr(runtime_services, "host", None)
    return getattr(runtime_context, "host_runtime", None)


def resolve_hook_bus(runtime_context: Any) -> Any | None:
    runtime_services = resolve_runtime_services(runtime_context)
    if runtime_services is not None:
        return getattr(runtime_services, "hook_bus", None)
    return getattr(runtime_context, "hook_bus", None)


__all__ = [
    "RuntimeControlPlaneContext",
    "resolve_hook_bus",
    "resolve_host_runtime",
    "resolve_runtime_services",
]
