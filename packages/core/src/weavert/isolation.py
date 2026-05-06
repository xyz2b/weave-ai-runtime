from __future__ import annotations

from ._isolation_contracts import (
    BaseIsolationAdapter,
    IsolationAdapter,
    IsolationLease,
    IsolationManager,
    IsolationPreparationError,
    IsolationRequest,
    serialize_isolation_lease,
)
from ._optional_compat import load_optional_attr

__all__ = [
    "BaseIsolationAdapter",
    "IsolationAdapter",
    "IsolationLease",
    "IsolationManager",
    "IsolationPreparationError",
    "IsolationRequest",
    "RemoteIsolationAdapter",
    "WorktreeIsolationAdapter",
    "serialize_isolation_lease",
]

_OPTIONAL_EXPORTS = {
    "RemoteIsolationAdapter": (
        "weavert_isolation.isolation",
        "RemoteIsolationAdapter",
    ),
    "WorktreeIsolationAdapter": (
        "weavert_isolation.isolation",
        "WorktreeIsolationAdapter",
    ),
}


def __getattr__(name: str):
    if name in _OPTIONAL_EXPORTS:
        module_name, attr_name = _OPTIONAL_EXPORTS[name]
        return load_optional_attr(
            module_name,
            attr_name,
            surface=f"weavert.isolation.{name}",
            distribution_names=("weavert-isolation",),
            source_paths=("packages/framework-packs/mechanisms/isolation",),
        )
    raise AttributeError(name)
