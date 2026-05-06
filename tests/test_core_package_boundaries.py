from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "core" / "src" / "weavert"


def _imports_extracted_add_on_package(module_name: str) -> bool:
    return module_name.split(".", 1)[0].startswith("weavert_")


def _core_direct_add_on_import_violations() -> tuple[str, ...]:
    violations: list[str] = []
    for source_path in sorted(CORE_SRC.rglob("*.py")):
        parsed = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(parsed):
            imported_modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported_modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                imported_modules = (node.module,)
            for module_name in imported_modules:
                if _imports_extracted_add_on_package(module_name):
                    violations.append(
                        f"{source_path.relative_to(ROOT)}:{node.lineno} imports {module_name}"
                    )
    return tuple(violations)


def test_core_source_tree_avoids_direct_imports_of_extracted_add_on_packages() -> None:
    violations = _core_direct_add_on_import_violations()

    assert violations == (), (
        "Core modules must resolve extracted add-on packages through manifest, entrypoint, "
        "capability, or protocol seams instead of direct imports:\n- "
        + "\n- ".join(violations)
    )


@pytest.mark.parametrize(
    ("module_name", "expected_attrs", "forbidden_attrs"),
    (
        ("weavert", ("RuntimeConfig", "RuntimePackageManifest"), ("SdkHostRuntime", "CliHostRuntime")),
        (
            "weavert.package_system",
            ("RuntimePackageManifest", "official_runtime_package_catalog"),
            (),
        ),
        ("weavert.extension_contracts", ("CANONICAL_IMPORT_ROOT", "IsolationManager"), ()),
        ("weavert.memory", ("MemoryTurnResult",), ("MemoryManager",)),
        ("weavert.compaction", ("CompactionPolicy",), ("CompactionManager",)),
        ("weavert.hosts", ("HostRuntime",), ("SdkHostRuntime",)),
        ("weavert.isolation", ("IsolationManager",), ("WorktreeIsolationAdapter",)),
    ),
)
def test_canonical_core_modules_expose_only_core_owned_public_surface(
    module_name: str,
    expected_attrs: tuple[str, ...],
    forbidden_attrs: tuple[str, ...],
) -> None:
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name
    for attr_name in expected_attrs:
        assert hasattr(module, attr_name), f"{module_name} should expose {attr_name}"
    for attr_name in forbidden_attrs:
        assert not hasattr(module, attr_name), f"{module_name} should not expose {attr_name}"


@pytest.mark.parametrize(
    "module_name",
    (
        "weavert.openai_client",
        "weavert.hosts.reference",
        "weavert.stores_file",
        "weavert.team.assembly",
        "weavert.devtools.builtins",
        "weavert.planning.builtins",
        "weavert.starter_scaffolds",
    ),
)
def test_removed_core_projection_modules_are_not_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
