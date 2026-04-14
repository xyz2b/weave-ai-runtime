from .models import (
    ModelClient,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    TranscriptEntry,
    TranscriptSession,
    TranscriptStore,
)

__all__ = [
    "ModelClient",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelStreamEventType",
    "PromptComposer",
    "PromptComposition",
    "TranscriptEntry",
    "TranscriptSession",
    "TranscriptStore",
    "TurnEngine",
    "TurnResult",
]


def __getattr__(name: str):
    if name in {"PromptComposer", "PromptComposition"}:
        from .composer import PromptComposer, PromptComposition

        return {"PromptComposer": PromptComposer, "PromptComposition": PromptComposition}[name]
    if name in {"TurnEngine", "TurnResult"}:
        from .engine import TurnEngine, TurnResult

        return {"TurnEngine": TurnEngine, "TurnResult": TurnResult}[name]
    raise AttributeError(name)
