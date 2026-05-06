from __future__ import annotations

from typing import Any

from .._optional_compat import load_optional_attr

_SURFACE = "weavert.testing.assertions"
_DISTRIBUTIONS = ("weavert-testing",)
_SOURCE_PATHS = ("packages/toolchain/testing",)
_MISSING_ROOTS = ("weavert_testing",)

__all__ = [
    "assert_child_summary",
    "assert_no_terminal_failure",
    "assert_skill_outcome",
    "assert_tool_outcome",
    "assert_tool_result",
    "extract_tool_result",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return load_optional_attr(
            "weavert_testing.assertions",
            name,
            surface=_SURFACE,
            distribution_names=_DISTRIBUTIONS,
            source_paths=_SOURCE_PATHS,
            expected_missing_roots=_MISSING_ROOTS,
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
