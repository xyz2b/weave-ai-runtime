from __future__ import annotations

from typing import Any

from ._optional_compat import load_optional_attr

_SURFACE = "weavert.starter_scaffolds"
_DISTRIBUTIONS = ("weavert-starter",)
_SOURCE_PATHS = ("packages/toolchain/starter",)
_MISSING_ROOTS = ("weavert_starter",)

__all__ = [
    "StarterScaffoldDefinition",
    "StarterScaffoldGenerationResult",
    "StarterScaffoldName",
    "generate_starter_scaffold",
    "main",
    "official_starter_scaffold",
    "official_starter_scaffold_catalog",
]


def _load_starter_attr(name: str) -> Any:
    return load_optional_attr(
        "weavert_starter",
        name,
        surface=_SURFACE,
        distribution_names=_DISTRIBUTIONS,
        source_paths=_SOURCE_PATHS,
        expected_missing_roots=_MISSING_ROOTS,
    )


def generate_starter_scaffold(*args: Any, **kwargs: Any) -> Any:
    return _load_starter_attr("generate_starter_scaffold")(*args, **kwargs)


def main(*args: Any, **kwargs: Any) -> Any:
    return _load_starter_attr("main")(*args, **kwargs)


def official_starter_scaffold(*args: Any, **kwargs: Any) -> Any:
    return _load_starter_attr("official_starter_scaffold")(*args, **kwargs)


def official_starter_scaffold_catalog(*args: Any, **kwargs: Any) -> Any:
    return _load_starter_attr("official_starter_scaffold_catalog")(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name in __all__:
        return _load_starter_attr(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
