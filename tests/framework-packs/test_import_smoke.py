from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("compat_module", "package_local_module"),
    (
        ("weavert.memory.package", "weavert_memory.package"),
        ("weavert.team.assembly", "weavert_team.assembly"),
        ("weavert.compaction.manager", "weavert_compaction.manager"),
        ("weavert.compaction.package", "weavert_compaction.package"),
        ("weavert.isolation_package", "weavert_isolation.package"),
        ("weavert.openai_package", "weavert_openai.package"),
        ("weavert.hosts.package", "weavert_hosts_reference.package"),
        ("weavert.stores_file.child_runs", "weavert_stores_file.child_runs"),
        ("weavert.stores_file.package", "weavert_stores_file.package"),
        ("weavert.planning.builtins", "weavert_planning.builtins"),
        ("weavert.devtools.builtins", "weavert_devtools.builtins"),
        (
            "weavert.builtin_workflows.builtins",
            "weavert_builtin_workflows.builtins",
        ),
    ),
)
def test_framework_pack_compatibility_shims_resolve_to_package_local_modules(
    compat_module: str,
    package_local_module: str,
) -> None:
    compat = importlib.import_module(compat_module)
    package_local = importlib.import_module(package_local_module)

    assert compat is package_local
