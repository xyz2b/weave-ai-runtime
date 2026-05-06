from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    (
        "weavert_memory.package",
        "weavert_team.assembly",
        "weavert_compaction.manager",
        "weavert_compaction.package",
        "weavert_isolation.package",
        "weavert_openai.package",
        "weavert_hosts_reference.package",
        "weavert_stores_file.child_runs",
        "weavert_stores_file.package",
        "weavert_planning.builtins",
        "weavert_devtools.builtins",
        "weavert_builtin_workflows.builtins",
    ),
)
def test_framework_pack_modules_import_from_canonical_package_roots(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name
