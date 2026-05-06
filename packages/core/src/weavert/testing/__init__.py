from __future__ import annotations

from typing import Any

from .._optional_compat import load_optional_attr

_SURFACE = "weavert.testing"
_DISTRIBUTIONS = ("weavert-testing",)
_SOURCE_PATHS = ("packages/toolchain/testing",)
_MISSING_ROOTS = ("weavert_testing",)

__all__ = [
    "BatchFactory",
    "BatchSpec",
    "FixtureWorkspace",
    "ScriptedModelClient",
    "ScriptedModelExhaustionError",
    "WorkflowTestReport",
    "assert_child_summary",
    "assert_no_terminal_failure",
    "assert_skill_outcome",
    "assert_tool_outcome",
    "assert_tool_result",
    "copied_fixture_workspace",
    "discovery_source",
    "discovery_sources",
    "extract_tool_result",
    "run_workflow_test",
    "temporary_workspace",
    "text_batch",
    "tool_call_batch",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return load_optional_attr(
            "weavert_testing",
            name,
            surface=_SURFACE,
            distribution_names=_DISTRIBUTIONS,
            source_paths=_SOURCE_PATHS,
            expected_missing_roots=_MISSING_ROOTS,
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
