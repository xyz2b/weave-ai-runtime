__all__ = [
    "CompactionBoundary",
    "CompactionContinuation",
    "CompactionManager",
    "CompactionPackageComponents",
    "CompactionPolicy",
    "CompactionRequest",
    "CompactionResult",
    "CompactionStepResult",
    "CompactionSummary",
    "ContextPressure",
    "OrderedCompactionStrategy",
    "ThresholdSummaryCompactionStrategy",
    "CompactionPackageComponents",
    "assemble_compaction_package",
    "evaluate_context_pressure",
    "latest_compaction_payload",
    "serialize_compaction_boundary",
    "serialize_compaction_continuation",
    "serialize_compaction_policy",
    "serialize_compaction_result",
    "serialize_compaction_step",
    "serialize_compaction_summary",
    "serialize_context_pressure",
]


def __getattr__(name: str):
    from importlib import import_module

    preferred_modules = (
        "weavert_compaction.manager",
        "weavert_compaction.models",
        "weavert_compaction.package",
    )
    fallback_modules = (".manager", ".models", ".package")
    for preferred_module, fallback_module in zip(preferred_modules, fallback_modules, strict=False):
        try:
            module = import_module(preferred_module)
        except ModuleNotFoundError:
            module = import_module(fallback_module, __name__)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)
