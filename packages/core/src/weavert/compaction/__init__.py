from .._optional_compat import load_optional_attr
from .models import (
    CompactionBoundary,
    CompactionContinuation,
    CompactionPolicy,
    CompactionRequest,
    CompactionResult,
    CompactionStepResult,
    CompactionSummary,
    ContextPressure,
    evaluate_context_pressure,
    latest_compaction_payload,
    serialize_compaction_boundary,
    serialize_compaction_continuation,
    serialize_compaction_policy,
    serialize_compaction_result,
    serialize_compaction_step,
    serialize_compaction_summary,
    serialize_context_pressure,
)

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

_OPTIONAL_EXPORTS = {
    "CompactionManager": ("weavert_compaction.manager", "CompactionManager"),
    "CompactionPackageComponents": ("weavert_compaction.package", "CompactionPackageComponents"),
    "OrderedCompactionStrategy": ("weavert_compaction.manager", "OrderedCompactionStrategy"),
    "ThresholdSummaryCompactionStrategy": (
        "weavert_compaction.manager",
        "ThresholdSummaryCompactionStrategy",
    ),
    "assemble_compaction_package": ("weavert_compaction.package", "assemble_compaction_package"),
}


def __getattr__(name: str):
    if name in _OPTIONAL_EXPORTS:
        module_name, attr_name = _OPTIONAL_EXPORTS[name]
        return load_optional_attr(
            module_name,
            attr_name,
            surface=f"weavert.compaction.{name}",
            distribution_names=("weavert-compaction",),
            source_paths=("packages/framework-packs/mechanisms/compaction",),
        )
    raise AttributeError(name)
