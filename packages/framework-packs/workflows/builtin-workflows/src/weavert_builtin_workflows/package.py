from __future__ import annotations

from weavert.package_system.manifests import _load_builtin_skill_contribution
from weavert.package_system.protocols import PackageAssemblyStage, PackageContext, PackageContribution


def assemble_runtime_builtin_workflows_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.BUILTINS:
        return PackageContribution()
    return PackageContribution(
        builtin_skills=_load_builtin_skill_contribution(
            context,
            "weavert_builtin_workflows.builtins:builtin_workflow_skills",
        )
    )


__all__ = ["assemble_runtime_builtin_workflows_package"]
