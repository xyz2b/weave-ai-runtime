from __future__ import annotations

from dataclasses import dataclass

from weavert.runtime_kernel.config import ModelProviderBinding, ModelRouteBinding
from weavert.package_system.protocols import (
    ModelProviderContribution,
    ModelRouteContribution,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
)
from .openai_client import (
    OPENAI_PROVIDER_NAME,
    OPENAI_ROUTE_NAME,
    bundled_openai_provider_binding,
    bundled_openai_route_binding,
)


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


def assemble_runtime_openai_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = assemble_openai_package()
    return PackageContribution(
        model_providers=(
            ModelProviderContribution(
                name=components.provider_name,
                binding=components.provider_binding,
                owner=context.ownership("model_provider", provider_name=components.provider_name),
            ),
        ),
        model_routes=(
            ModelRouteContribution(
                name=components.route_name,
                binding=components.route_binding,
                owner=context.ownership("model_route", route_name=components.route_name),
            ),
        ),
    )


__all__ = [
    "OpenAIPackageComponents",
    "assemble_openai_package",
    "assemble_runtime_openai_package",
]
