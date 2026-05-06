from __future__ import annotations

from ..definitions import (
    InterruptBehavior,
    ToolClassifierInput,
    ToolExecutionSemantics,
    ToolFailurePolicy,
    ToolPresentationEmphasis,
    ToolResultSummary,
    ToolResultSummaryStatus,
    ToolRiskLevel,
    ToolUsePresentation,
)


def static_semantics(
    *,
    read_only: bool = False,
    concurrency_safe: bool = False,
    interrupt_behavior: InterruptBehavior = InterruptBehavior.BLOCK,
    failure_policy: ToolFailurePolicy | None = None,
    tool_use_presentation=None,
    tool_result_summary=None,
    classifier_input=None,
) -> ToolExecutionSemantics:
    return ToolExecutionSemantics(
        is_read_only=lambda _tool_input, _context: read_only,
        is_concurrency_safe=lambda _tool_input, _context: concurrency_safe,
        interrupt_behavior=lambda _tool_input, _context: interrupt_behavior,
        failure_policy=lambda _tool_input, _context: failure_policy or ToolFailurePolicy(),
        render_tool_use_message=tool_use_presentation or (lambda _tool_input, _context: None),
        render_tool_result_summary=tool_result_summary or (lambda _tool_input, _context: None),
        to_classifier_input=classifier_input or (lambda _tool_input, _context: None),
    )


def file_semantics(
    *,
    operation: str,
    read_only: bool,
    concurrency_safe: bool,
    summary: str,
    risk_level: ToolRiskLevel,
    failure_policy: ToolFailurePolicy | None = None,
) -> ToolExecutionSemantics:
    return static_semantics(
        read_only=read_only,
        concurrency_safe=concurrency_safe,
        failure_policy=failure_policy,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=summary,
            subtitle=tool_input.get("file_path"),
            emphasis=(
                ToolPresentationEmphasis.LOW
                if read_only
                else ToolPresentationEmphasis.NORMAL
            ),
        ),
        tool_result_summary=lambda tool_input, _context: ToolResultSummary(
            title=summary,
            summary=tool_input.get("file_path", summary),
            status=ToolResultSummaryStatus.SUCCESS,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary}: {tool_input.get('file_path', '')}".strip(": "),
            target_paths=(
                (str(tool_input["file_path"]),)
                if tool_input.get("file_path") is not None
                else ()
            ),
            risk_level=risk_level,
            side_effects=not read_only,
            tags=("filesystem", operation),
        ),
    )


__all__ = ["file_semantics", "static_semantics"]
