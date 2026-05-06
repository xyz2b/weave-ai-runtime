from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "core" / "src" / "weavert"


def _imports_extracted_add_on_package(module_name: str) -> bool:
    return module_name.split(".", 1)[0].startswith("weavert_")


def _dynamic_import_target(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    if isinstance(func, ast.Name):
        if func.id not in {"__import__", "import_module", "load_optional_attr", "load_optional_module"}:
            return None
    elif isinstance(func, ast.Attribute):
        if not (isinstance(func.value, ast.Name) and func.value.id == "importlib" and func.attr == "import_module"):
            return None
    else:
        return None
    target = node.args[0]
    if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
        return None
    return target.value


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
            else:
                dynamic_target = _dynamic_import_target(node)
                if dynamic_target is not None:
                    imported_modules = (dynamic_target,)
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


def test_core_isolation_manager_does_not_admit_optional_package_adapters_by_default() -> None:
    module = importlib.import_module("weavert.isolation")

    assert module.IsolationManager().describe_modes() == {
        "none": {
            "status": "ready",
            "effective_mode": "none",
            "adapter": "BaseIsolationAdapter",
        },
        "worktree": {
            "status": "not_available",
            "effective_mode": "worktree",
        },
        "remote": {
            "status": "not_available",
            "effective_mode": "remote",
        },
    }


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
