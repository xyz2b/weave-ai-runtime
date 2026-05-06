from __future__ import annotations

from weavert.runtime_package_manifests import (
    _load_builtin_agent_contribution,
    _load_builtin_tool_contribution,
)
from weavert.runtime_package_protocols import PackageAssemblyStage, PackageContext, PackageContribution


def assemble_runtime_devtools_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.BUILTINS:
        return PackageContribution()
    return PackageContribution(
        builtin_tools=_load_builtin_tool_contribution(
            context,
            "weavert_devtools.builtins:devtools_builtin_tools",
        ),
        builtin_agents=_load_builtin_agent_contribution(
            context,
            "weavert_devtools.builtins:devtools_builtin_agents",
        ),
    )


__all__ = ["assemble_runtime_devtools_package"]
