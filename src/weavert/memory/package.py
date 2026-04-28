from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..definitions import MemoryScope
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


__all__ = [
    "MemoryCapabilityComponents",
    "assemble_memory_capability",
]
