from .mailbox import FileBackedTeammateMailbox, TeammateMailboxPaths
from .models import (
    MailboxEnvelope,
    MailboxSender,
    MailboxTerminalState,
    SharedExecutionCore,
    TeammateExecutionRequest,
    TeammateLifecycleState,
    TeammateOrchestrationConfig,
    TeammateProjection,
    TeammateRecoveryResult,
    TeammateRegistration,
    TeammateStateSnapshot,
)

__all__ = [
    "FileBackedTeammateMailbox",
    "MailboxEnvelope",
    "MailboxSender",
    "MailboxTerminalState",
    "PersistentTeammateHostBridge",
    "PersistentTeammateOrchestrator",
    "SharedExecutionCore",
    "TeammateExecutionRequest",
    "TeammateLifecycleState",
    "TeammateMailboxPaths",
    "TeammateOrchestrationConfig",
    "TeammateProjection",
    "TeammateRecoveryResult",
    "TeammateRegistration",
    "TeammateRegistry",
    "TeammateStateSnapshot",
]


def __getattr__(name: str):
    if name in {
        "PersistentTeammateHostBridge",
        "PersistentTeammateOrchestrator",
        "TeammateRegistry",
    }:
        from .service import (
            PersistentTeammateHostBridge,
            PersistentTeammateOrchestrator,
            TeammateRegistry,
        )

        mapping = {
            "PersistentTeammateHostBridge": PersistentTeammateHostBridge,
            "PersistentTeammateOrchestrator": PersistentTeammateOrchestrator,
            "TeammateRegistry": TeammateRegistry,
        }
        return mapping[name]
    raise AttributeError(name)
