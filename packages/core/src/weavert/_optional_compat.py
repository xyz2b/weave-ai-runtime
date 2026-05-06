from __future__ import annotations

from importlib import import_module
from types import ModuleType


def load_optional_module(
    module_name: str,
    *,
    surface: str,
    distribution_names: tuple[str, ...],
    source_paths: tuple[str, ...] = (),
    expected_missing_roots: tuple[str, ...] = (),
) -> ModuleType:
    expected_roots = {module_name.split(".", 1)[0], *expected_missing_roots}
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_root = str(getattr(exc, "name", "") or "").split(".", 1)[0]
        if missing_root and missing_root not in expected_roots:
            raise
        raise ModuleNotFoundError(_optional_dependency_message(surface, distribution_names, source_paths)) from exc


def load_optional_attr(
    module_name: str,
    attr_name: str,
    *,
    surface: str,
    distribution_names: tuple[str, ...],
    source_paths: tuple[str, ...] = (),
    expected_missing_roots: tuple[str, ...] = (),
):
    module = load_optional_module(
        module_name,
        surface=surface,
        distribution_names=distribution_names,
        source_paths=source_paths,
        expected_missing_roots=expected_missing_roots,
    )
    return getattr(module, attr_name)


def _optional_dependency_message(
    surface: str,
    distribution_names: tuple[str, ...],
    source_paths: tuple[str, ...],
) -> str:
    package_list = ", ".join(f"`{name}`" for name in distribution_names)
    if source_paths:
        source_list = ", ".join(f"`{path}`" for path in source_paths)
        return (
            f"{surface} now lives in optional package(s) {package_list}. "
            f"Install the corresponding local package(s) from {source_list} to use this compatibility shim."
        )
    return (
        f"{surface} now lives in optional package(s) {package_list}. "
        "Install the corresponding optional package(s) to use this compatibility shim."
    )


__all__ = ["load_optional_attr", "load_optional_module"]
