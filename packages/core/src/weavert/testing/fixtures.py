from __future__ import annotations

from typing import Any

from .._optional_compat import load_optional_attr

_SURFACE = "weavert.testing.fixtures"
_DISTRIBUTIONS = ("weavert-testing",)
_SOURCE_PATHS = ("packages/toolchain/testing",)
_MISSING_ROOTS = ("weavert_testing",)

__all__ = [
    "FixtureWorkspace",
    "copied_fixture_workspace",
    "discovery_source",
    "discovery_sources",
    "temporary_workspace",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return load_optional_attr(
            "weavert_testing.fixtures",
            name,
            surface=_SURFACE,
            distribution_names=_DISTRIBUTIONS,
            source_paths=_SOURCE_PATHS,
            expected_missing_roots=_MISSING_ROOTS,
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
