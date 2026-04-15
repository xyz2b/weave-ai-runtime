from .models import (
    ModelAbortSignal,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ModelTerminalMetadata,
    TranscriptEntry,
    TranscriptSession,
    TranscriptStore,
)

__all__ = [
    "ContextAssembler",
    "ContextAssembly",
    "ModelAbortSignal",
    "ModelClient",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelStreamEventType",
    "ModelTerminalMetadata",
    "PromptComposer",
    "PromptComposition",
    "TranscriptEntry",
    "TranscriptSession",
    "TranscriptStore",
    "TurnStreamEvent",
    "TurnStreamEventType",
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
    if name in {"TurnEngine", "TurnResult", "TurnStreamEvent", "TurnStreamEventType"}:
        from .engine import TurnEngine, TurnResult, TurnStreamEvent, TurnStreamEventType

        return {
            "TurnEngine": TurnEngine,
            "TurnResult": TurnResult,
            "TurnStreamEvent": TurnStreamEvent,
            "TurnStreamEventType": TurnStreamEventType,
        }[name]
    raise AttributeError(name)
