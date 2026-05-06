from __future__ import annotations

from dataclasses import dataclass

from weavert.runtime_package_protocols import (
    CapabilityBinding,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    RuntimeCapabilityKey,
)
from .reference import CliHostRuntime, SdkHostRuntime


@dataclass(frozen=True, slots=True)
class ReferenceHostPackageComponents:
    cli_host_type: type[CliHostRuntime]
    sdk_host_type: type[SdkHostRuntime]

    @property
    def host_types(self) -> dict[str, type[object]]:
        return {
            "cli": self.cli_host_type,
            "sdk": self.sdk_host_type,
        }


def assemble_reference_host_package() -> ReferenceHostPackageComponents:
    return ReferenceHostPackageComponents(
        cli_host_type=CliHostRuntime,
        sdk_host_type=SdkHostRuntime,
    )


def assemble_runtime_hosts_reference_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = assemble_reference_host_package()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.REFERENCE_HOST_TYPES.value,
                value=components.host_types,
                owner=context.ownership("capability", component="host_types"),
            ),
        ),
    )


__all__ = [
    "ReferenceHostPackageComponents",
    "assemble_reference_host_package",
    "assemble_runtime_hosts_reference_package",
]
