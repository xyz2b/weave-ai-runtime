__all__ = [
    "FileMemoryProvider",
    "MemoryDocument",
    "MemoryEmbeddingShortlistProvider",
    "MemoryEntry",
    "MemoryProvider",
    "MemoryRerankProvider",
    "MemoryRetrievalCandidate",
    "MemoryRetrievalPolicy",
    "MemoryRetrievalRankedHit",
    "MemoryTurnResult",
    "MemoryWriteReceipt",
    "ResolvedMemoryScope",
    "LongTermMemory",
    "LongTermMemoryService",
    "MemoryCapabilityComponents",
    "MemoryConsolidationConfig",
    "MemoryExtractionConfig",
    "MemoryManager",
    "MemoryManagerService",
    "MemoryRetrievalConfig",
    "MemoryRuntimeConfig",
    "MemorySessionConfig",
    "MemorySessionRefreshConfig",
    "ResolvedMemoryConfig",
    "assemble_memory_capability",
]

_OPTIONAL_EXPORTS = {
    "FileMemoryProvider": ("weavert_memory.providers", ".providers", "FileMemoryProvider"),
    "LongTermMemory": ("weavert_memory.manager", ".manager", "LongTermMemory"),
    "LongTermMemoryService": ("weavert_memory.manager", ".manager", "LongTermMemoryService"),
    "MemoryCapabilityComponents": ("weavert_memory.package", ".package", "MemoryCapabilityComponents"),
    "MemoryConsolidationConfig": ("weavert_memory.config", ".config", "MemoryConsolidationConfig"),
    "MemoryDocument": ("weavert_memory.models", ".models", "MemoryDocument"),
    "MemoryEmbeddingShortlistProvider": (
        "weavert_memory.models",
        ".models",
        "MemoryEmbeddingShortlistProvider",
    ),
    "MemoryEntry": ("weavert_memory.models", ".models", "MemoryEntry"),
    "MemoryExtractionConfig": ("weavert_memory.config", ".config", "MemoryExtractionConfig"),
    "MemoryManager": ("weavert_memory.manager", ".manager", "MemoryManager"),
    "MemoryManagerService": ("weavert_memory.manager", ".manager", "MemoryManagerService"),
    "MemoryProvider": ("weavert_memory.providers", ".providers", "MemoryProvider"),
    "MemoryRerankProvider": ("weavert_memory.models", ".models", "MemoryRerankProvider"),
    "MemoryRetrievalCandidate": ("weavert_memory.models", ".models", "MemoryRetrievalCandidate"),
    "MemoryRetrievalConfig": ("weavert_memory.config", ".config", "MemoryRetrievalConfig"),
    "MemoryRetrievalPolicy": ("weavert_memory.models", ".models", "MemoryRetrievalPolicy"),
    "MemoryRetrievalRankedHit": ("weavert_memory.models", ".models", "MemoryRetrievalRankedHit"),
    "MemoryRuntimeConfig": ("weavert_memory.config", ".config", "MemoryRuntimeConfig"),
    "MemorySessionConfig": ("weavert_memory.config", ".config", "MemorySessionConfig"),
    "MemorySessionRefreshConfig": (
        "weavert_memory.config",
        ".config",
        "MemorySessionRefreshConfig",
    ),
    "MemoryTurnResult": ("weavert_memory.models", ".models", "MemoryTurnResult"),
    "MemoryWriteReceipt": ("weavert_memory.models", ".models", "MemoryWriteReceipt"),
    "ResolvedMemoryConfig": ("weavert_memory.config", ".config", "ResolvedMemoryConfig"),
    "ResolvedMemoryScope": ("weavert_memory.models", ".models", "ResolvedMemoryScope"),
    "assemble_memory_capability": ("weavert_memory.package", ".package", "assemble_memory_capability"),
}


def __getattr__(name: str):
    if name in _OPTIONAL_EXPORTS:
        from importlib import import_module

        preferred_module, fallback_module, attr_name = _OPTIONAL_EXPORTS[name]
        try:
            module = import_module(preferred_module)
        except ModuleNotFoundError:
            module = import_module(fallback_module, __name__)
        return getattr(module, attr_name)
    raise AttributeError(name)
