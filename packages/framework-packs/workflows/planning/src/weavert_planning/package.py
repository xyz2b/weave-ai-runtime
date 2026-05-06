from __future__ import annotations

from weavert.package_system.manifests import _load_builtin_agent_contribution
from weavert.package_system.protocols import PackageAssemblyStage, PackageContext, PackageContribution


def assemble_runtime_planning_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.BUILTINS:
        return PackageContribution()
    return PackageContribution(
        builtin_agents=_load_builtin_agent_contribution(
            context,
            "weavert_planning.builtins:planning_builtin_agents",
        )
    )


__all__ = ["assemble_runtime_planning_package"]
