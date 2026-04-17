from .models import (
    ModelCapabilityProvider,
    ModelAbortSignal,
    ModelClient,
    ModelInvocationMode,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ModelTerminalMetadata,
    NormalizedModelCapabilities,
    TranscriptEntry,
    TranscriptSession,
    TranscriptStore,
    ToolExecutorTier,
)

__all__ = [
    "AttemptFinished",
    "ContextAssembler",
    "ContextAssembly",
    "ModelCapabilityProvider",
    "ModelAbortSignal",
    "ModelClient",
    "ModelInvocationMode",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelStreamEventType",
    "ModelTerminalMetadata",
    "NormalizedModelCapabilities",
    "PromptComposer",
    "PromptComposition",
    "TranscriptEntry",
    "TranscriptSession",
    "TranscriptStore",
    "ToolExecutorTier",
    "TurnStreamEvent",
    "TurnStreamEventType",
    "TurnLoopState",
    "TurnPhase",
    "TurnPostEffects",
    "TurnRecoveryAction",
    "TurnTerminal",
    "TurnTerminalReason",
    "TurnTransition",
    "TurnTransitionReason",
    "TurnEngine",
    "TurnResult",
]


def __getattr__(name: str):
    if name in {"ContextAssembler", "ContextAssembly", "PromptComposer", "PromptComposition"}:
        from .composer import ContextAssembler, ContextAssembly, PromptComposer, PromptComposition

        return {
            "ContextAssembler": ContextAssembler,
            "ContextAssembly": ContextAssembly,
            "PromptComposer": PromptComposer,
            "PromptComposition": PromptComposition,
        }[name]
    if name in {
        "AttemptFinished",
        "TurnEngine",
        "TurnLoopState",
        "TurnPhase",
        "TurnPostEffects",
        "TurnRecoveryAction",
        "TurnResult",
        "TurnStreamEvent",
        "TurnStreamEventType",
        "TurnTerminal",
        "TurnTerminalReason",
        "TurnTransition",
        "TurnTransitionReason",
    }:
        from .engine import (
            AttemptFinished,
            TurnEngine,
            TurnLoopState,
            TurnPhase,
            TurnPostEffects,
            TurnRecoveryAction,
            TurnResult,
            TurnStreamEvent,
            TurnStreamEventType,
            TurnTerminal,
            TurnTerminalReason,
            TurnTransition,
            TurnTransitionReason,
        )

        return {
            "AttemptFinished": AttemptFinished,
            "TurnEngine": TurnEngine,
            "TurnLoopState": TurnLoopState,
            "TurnPhase": TurnPhase,
            "TurnPostEffects": TurnPostEffects,
            "TurnRecoveryAction": TurnRecoveryAction,
            "TurnResult": TurnResult,
            "TurnStreamEvent": TurnStreamEvent,
            "TurnStreamEventType": TurnStreamEventType,
            "TurnTerminal": TurnTerminal,
            "TurnTerminalReason": TurnTerminalReason,
            "TurnTransition": TurnTransition,
            "TurnTransitionReason": TurnTransitionReason,
        }[name]
    raise AttributeError(name)
