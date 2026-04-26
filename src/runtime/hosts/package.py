from __future__ import annotations

from dataclasses import dataclass

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


__all__ = [
    "ReferenceHostPackageComponents",
    "assemble_reference_host_package",
]
