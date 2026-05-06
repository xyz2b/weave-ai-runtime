from .base import (
    BoundHostInspectionSurface,
    BoundHostPromptSurface,
    BoundHostRuntime,
    BoundHostSessionSurface,
    BoundHostWorkSurface,
    CallbackHostAdapter,
    HostAdapter,
    HostExtensionEvent,
    HostFactory,
    HostRuntime,
    NullHostAdapter,
)

__all__ = [
    "BoundHostInspectionSurface",
    "BoundHostPromptSurface",
    "BoundHostRuntime",
    "BoundHostSessionSurface",
    "BoundHostWorkSurface",
    "CallbackHostAdapter",
    "CliHostRuntime",
    "HostAdapter",
    "HostExtensionEvent",
    "HostFactory",
    "HostRuntime",
    "NullHostAdapter",
    "ReferenceHostPackageComponents",
    "SdkHostRuntime",
    "assemble_reference_host_package",
]


def __getattr__(name: str):
    if name in {"CliHostRuntime", "SdkHostRuntime"}:
        from .reference import CliHostRuntime, SdkHostRuntime

        mapping = {
            "CliHostRuntime": CliHostRuntime,
            "SdkHostRuntime": SdkHostRuntime,
        }
        return mapping[name]
    if name in {"ReferenceHostPackageComponents", "assemble_reference_host_package"}:
        from .package import ReferenceHostPackageComponents, assemble_reference_host_package

        mapping = {
            "ReferenceHostPackageComponents": ReferenceHostPackageComponents,
            "assemble_reference_host_package": assemble_reference_host_package,
        }
        return mapping[name]
    raise AttributeError(name)
