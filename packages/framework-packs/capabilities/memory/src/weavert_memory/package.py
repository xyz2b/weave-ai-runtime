from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from weavert.definitions import MemoryScope
from weavert.runtime_package_manifests import _load_builtin_skill_contribution
from weavert.runtime_package_protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    ContextContributorStage,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    RuntimeCapabilityKey,
)
from .config import MemoryRuntimeConfig
from .manager import MemoryManager, MemoryManagerService
from .models import MemoryEmbeddingShortlistProvider, MemoryRetrievalPolicy, MemoryRerankProvider
from .providers import MemoryProvider


@dataclass(frozen=True, slots=True)
class MemoryCapabilityComponents:
    provider: MemoryProvider
    manager: MemoryManager
    service: MemoryManagerService


def assemble_memory_capability(
    *,
    project_root: Path | None = None,
    user_root: Path | None = None,
    default_scope: MemoryScope = MemoryScope.PROJECT,
    retrieval_limit: int = 3,
    retrieval_policy: MemoryRetrievalPolicy | None = None,
    embedding_shortlist_provider: MemoryEmbeddingShortlistProvider | None = None,
    rerank_provider: MemoryRerankProvider | None = None,
    memory_config: Mapping[str, Any] | MemoryRuntimeConfig | None = None,
    provider: MemoryProvider | None = None,
    manager: MemoryManager | None = None,
    service: MemoryManagerService | None = None,
) -> MemoryCapabilityComponents:
    resolved_service = service or MemoryManagerService(
        provider=provider,
        project_root=project_root,
        user_root=user_root,
        default_scope=default_scope,
        retrieval_limit=retrieval_limit,
        retrieval_policy=retrieval_policy,
        embedding_shortlist_provider=embedding_shortlist_provider,
        rerank_provider=rerank_provider,
        memory_config=memory_config,
        manager=manager,
    )
    resolved_manager = resolved_service.manager
    return MemoryCapabilityComponents(
        provider=resolved_manager.provider,
        manager=resolved_manager,
        service=resolved_service,
    )


def assemble_runtime_memory_package(context: PackageContext) -> PackageContribution:
    if context.stage == PackageAssemblyStage.BUILTINS:
        return PackageContribution(
            builtin_skills=_load_builtin_skill_contribution(
                context,
                "weavert_memory.builtins:memory_builtin_skills",
            )
        )
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = assemble_memory_capability(
        project_root=context.working_directory,
        memory_config=getattr(context.config, "memory_config", None),
    )
    return PackageContribution(
        context_contributors=(
            ContextContributorBinding(
                name="weavert-memory.collect",
                stage=ContextContributorStage.MEMORY,
                contributor=components.service,
                owner=context.ownership(
                    "context_contributor",
                    component="collect",
                    stage=ContextContributorStage.MEMORY.value,
                ),
                metadata={
                    "compatibility_surface": "RuntimeServices.memory.collect",
                },
            ),
        ),
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.MEMORY_SERVICE.value,
                value=components.service,
                owner=context.ownership("capability", component="service"),
            ),
        ),
    )


__all__ = [
    "MemoryCapabilityComponents",
    "assemble_memory_capability",
    "assemble_runtime_memory_package",
]
