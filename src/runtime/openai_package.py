from __future__ import annotations

from dataclasses import dataclass

from .openai_client import (
    OPENAI_PROVIDER_NAME,
    OPENAI_ROUTE_NAME,
    bundled_openai_provider_binding,
    bundled_openai_route_binding,
)
from .runtime_kernel.config import ModelProviderBinding, ModelRouteBinding


@dataclass(frozen=True, slots=True)
class OpenAIPackageComponents:
    provider_name: str
    route_name: str
    provider_binding: ModelProviderBinding
    route_binding: ModelRouteBinding


def assemble_openai_package(
    *,
    provider_binding: ModelProviderBinding | None = None,
    route_binding: ModelRouteBinding | None = None,
) -> OpenAIPackageComponents:
    return OpenAIPackageComponents(
        provider_name=OPENAI_PROVIDER_NAME,
        route_name=OPENAI_ROUTE_NAME,
        provider_binding=provider_binding or bundled_openai_provider_binding(),
        route_binding=route_binding or bundled_openai_route_binding(),
    )


__all__ = [
    "OpenAIPackageComponents",
    "assemble_openai_package",
]
