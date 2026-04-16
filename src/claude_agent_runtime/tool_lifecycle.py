from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .contracts import RuntimeMessage, ToolResultBlock
from .definitions import PermissionBehavior, PermissionMode, ToolCallStatus
from .memory.models import MemoryEntry


class ToolResolutionStatus(StrEnum):
    EXECUTABLE = "executable"
    DENIED = "denied"
    INVALID = "invalid"


class ToolSchedulerLaneKind(StrEnum):
    CONCURRENT = "concurrent"
    EXCLUSIVE = "exclusive"
    CONFLICT = "conflict"


class ToolLaneDerivationMode(StrEnum):
    PRECISE = "precise"
    COARSE = "coarse"


class ContextUpdatePhase(StrEnum):
    BEFORE_REPLAY = "before_replay"
    WITH_REPLAY = "with_replay"
    AFTER_REPLAY = "after_replay"


class ToolLifecycleStage(StrEnum):
    OBSERVED = "observed"
    RESOLVING = "resolving"
    RESOLVED_NON_EXECUTABLE = "resolved_non_executable"
    QUEUED = "queued"
    RUNNING = "running"
    TERMINAL_PENDING_REPLAY = "terminal_pending_replay"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class CatalogEntryView:
    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    source_label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class _CatalogView:
    def __init__(self, entries: Sequence[CatalogEntryView]) -> None:
        self._entries = tuple(entries)
        self._by_name = {entry.name: entry for entry in self._entries}
        self._aliases: dict[str, str] = {}
        for entry in self._entries:
            for alias in entry.aliases:
                self._aliases.setdefault(alias, entry.name)

    def get(self, name_or_alias: str) -> CatalogEntryView | None:
        canonical = self.resolve_alias(name_or_alias) or name_or_alias
        return self._by_name.get(canonical)

    def list(self) -> tuple[CatalogEntryView, ...]:
        return self._entries

    def snapshot(self) -> tuple[CatalogEntryView, ...]:
        return self._entries

    def resolve_alias(self, name_or_alias: str) -> str | None:
        if name_or_alias in self._by_name:
            return name_or_alias
        return self._aliases.get(name_or_alias)


class ToolCatalog(_CatalogView):
    pass


class AgentCatalog(_CatalogView):
    pass


class SkillCatalog(_CatalogView):
    pass


@dataclass(frozen=True, slots=True)
class PermissionRuleView:
    target_type: str
    selector: str
    behavior: PermissionBehavior
    message: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionContextView:
    effective_mode: PermissionMode
    interactive_prompts_allowed: bool
    bubbles_to_caller: bool
    requires_host_mediation: bool
    rules: tuple[PermissionRuleView, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryAbortHandle:
    signal: Any | None = None

    @property
    def aborted(self) -> bool:
        return bool(self.signal is not None and getattr(self.signal, "aborted", False))

    @property
    def reason(self) -> str | None:
        if self.signal is None:
            return None
        return getattr(self.signal, "reason", None)

    def abort(self, reason: str = "interrupt") -> None:
        if self.signal is not None and hasattr(self.signal, "abort"):
            self.signal.abort(reason)

    async def wait(self) -> None:
        if self.signal is not None and hasattr(self.signal, "wait"):
            await self.signal.wait()


@dataclass(frozen=True, slots=True)
class QueryContext:
    session_id: str
    turn_id: str
    agent_name: str
    cwd: Path
    messages: tuple[RuntimeMessage, ...] = ()
    selected_executor_tier: str = "none"
    model_capabilities: Any = None
    abort_handle: QueryAbortHandle | None = None
    continuation_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AppState:
    _state: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, namespace: str, key: str) -> Any | None:
        return self._state.get(namespace, {}).get(key)

    def set(self, namespace: str, key: str, value: Any) -> None:
        self._state.setdefault(namespace, {})[key] = value

    def compare_and_set(self, namespace: str, key: str, expected: Any, value: Any) -> bool:
        current = self.get(namespace, key)
        if current != expected:
            return False
        self.set(namespace, key, value)
        return True


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    exists: bool
    is_file: bool
    size: int | None = None
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class FileObservation:
    path: str
    observation_kind: str
    digest: str | None = None
    conflict_key: str | None = None


@dataclass(frozen=True, slots=True)
class FileConflictHandle:
    path: str
    conflict_key: str


@dataclass(slots=True)
class FileState:
    guarded_roots: tuple[Path, ...] = ()
    _observations: dict[str, FileObservation] = field(default_factory=dict)

    def stat(self, path: str) -> FileSnapshot | None:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return FileSnapshot(path=str(resolved), exists=False, is_file=False)
        digest = None
        if resolved.is_file():
            digest = _digest_path(resolved)
        return FileSnapshot(
            path=str(resolved),
            exists=True,
            is_file=resolved.is_file(),
            size=resolved.stat().st_size if resolved.is_file() else None,
            digest=digest,
        )

    def read_observed(self, path: str) -> FileObservation | None:
        return self._observations.get(str(Path(path).resolve()))

    def record_read(self, path: str, digest: str | None = None) -> None:
        resolved = str(Path(path).resolve())
        self._observations[resolved] = FileObservation(
            path=resolved,
            observation_kind="read",
            digest=digest,
            conflict_key=self.conflict_key(resolved),
        )

    def record_write_intent(self, path: str) -> FileConflictHandle:
        resolved = str(Path(path).resolve())
        conflict_key = self.conflict_key(resolved)
        self._observations[resolved] = FileObservation(
            path=resolved,
            observation_kind="write_intent",
            conflict_key=conflict_key,
        )
        return FileConflictHandle(path=resolved, conflict_key=conflict_key)

    def record_write_commit(self, path: str, digest: str | None = None) -> None:
        resolved = str(Path(path).resolve())
        self._observations[resolved] = FileObservation(
            path=resolved,
            observation_kind="write_commit",
            digest=digest,
            conflict_key=self.conflict_key(resolved),
        )

    def conflict_key(self, path: str) -> str:
        return str(Path(path).resolve())

    def guarded_status(self, path: str) -> str:
        resolved = Path(path).resolve()
        for root in self.guarded_roots:
            try:
                resolved.relative_to(root)
                return "guarded"
            except ValueError:
                continue
        return "allowed"


ProgressEmitter = Callable[[str, str, float | None], Any]
NotificationEmitter = Callable[[str, str], Any]
RefreshEmitter = Callable[[str, str], Any]
MemoryReader = Callable[[str, str | None], Sequence[MemoryEntry]]
MemoryAppender = Callable[[str, MemoryEntry], Any]


@dataclass(frozen=True, slots=True)
class RefreshReceipt:
    scope: str
    reason: str
    accepted: bool = True


@dataclass(slots=True)
class ProgressHandle:
    emitter: ProgressEmitter | None = None

    def start(self, label: str, metadata: Mapping[str, Any] | None = None) -> str:
        progress_id = _stable_progress_id(label, metadata)
        self.update(progress_id, label, None)
        return progress_id

    def update(self, progress_id: str, message: str, percent: float | None = None) -> None:
        if self.emitter is not None:
            self.emitter(progress_id, message, percent)

    def complete(self, progress_id: str, message: str | None = None) -> None:
        self.update(progress_id, message or progress_id, 1.0)


@dataclass(slots=True)
class NotificationsHandle:
    emitter: NotificationEmitter | None = None

    def emit(self, message: str, level: str = "info") -> None:
        if self.emitter is not None:
            self.emitter(message, level)


@dataclass(slots=True)
class CapabilityRefreshHandle:
    emitter: RefreshEmitter | None = None
    receipts: list[RefreshReceipt] = field(default_factory=list)

    def request(self, scope: str, reason: str) -> RefreshReceipt:
        receipt = RefreshReceipt(scope=scope, reason=reason, accepted=True)
        self.receipts.append(receipt)
        if self.emitter is not None:
            self.emitter(scope, reason)
        return receipt


@dataclass(slots=True)
class MemoryAccess:
    reader: MemoryReader | None = None
    appender: MemoryAppender | None = None
    _entries: dict[str, list[MemoryEntry]] = field(default_factory=dict)

    def read(self, scope: str, query: str | None = None) -> Sequence[MemoryEntry]:
        if self.reader is not None:
            return tuple(self.reader(scope, query))
        return tuple(self._entries.get(scope, ()))

    def append(self, scope: str, entry: MemoryEntry) -> None:
        self._entries.setdefault(scope, []).append(entry)
        if self.appender is not None:
            self.appender(scope, entry)


@dataclass(frozen=True, slots=True)
class ToolCallEnvelope:
    envelope_id: str
    tool_use_id: str
    sequence_index: int
    raw_tool_name: str
    raw_input: Mapping[str, Any]
    assistant_message_id: str
    provider_request_id: str | None = None
    block_index: int | None = None
    observed_at: Any = None
    query_snapshot: QueryContext | None = None


@dataclass(frozen=True, slots=True)
class PermissionAllowed:
    kind: str = "allow"
    source: str = "policy"
    updated_input: Mapping[str, Any] | None = None
    user_modified: bool = False
    accept_feedback: str | None = None
    content_blocks: tuple[Any, ...] = ()
    audit_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PermissionDenied:
    denied_status: ToolCallStatus
    message: str
    kind: str = "deny"
    source: str = "policy"
    content_blocks: tuple[Any, ...] = ()
    retry_hint: str = "none"
    audit_metadata: Mapping[str, Any] = field(default_factory=dict)


ResolvedPermissionDecision = PermissionAllowed | PermissionDenied


@dataclass(frozen=True, slots=True)
class ToolSchedulerLane:
    lane_kind: ToolSchedulerLaneKind
    lane_key: str | None = None
    conflict_domains: tuple[str, ...] = ()
    failure_scope_key: str = "turn"
    shares_concurrency: bool = False
    derivation_mode: ToolLaneDerivationMode = ToolLaneDerivationMode.COARSE


@dataclass(frozen=True, slots=True)
class ToolCapabilityContext:
    tool_use_id: str
    canonical_tool_name: str | None
    assistant_message_id: str
    replay_index: int
    executor_tier: str
    query_context: QueryContext
    tool_catalog: ToolCatalog
    agent_catalog: AgentCatalog
    skill_catalog: SkillCatalog
    permission_context: PermissionContextView
    app_state: AppState
    file_state: FileState
    progress: ProgressHandle
    notifications: NotificationsHandle
    refresh_capabilities: CapabilityRefreshHandle
    memory_access: MemoryAccess


@dataclass(frozen=True, slots=True)
class ResolvedToolCall:
    envelope: ToolCallEnvelope
    resolution_status: ToolResolutionStatus
    canonical_tool_name: str | None
    tool_definition_ref: Any | None
    execution_input: Mapping[str, Any] | None
    observable_input: Mapping[str, Any] | None
    resolved_semantics: Any | None
    permission_decision: ResolvedPermissionDecision | None
    scheduler_lane: ToolSchedulerLane | None
    replay_index: int
    capability_context: ToolCapabilityContext


@dataclass(frozen=True, slots=True)
class AppStateSet:
    namespace: str
    key: str
    value: Any
    kind: str = "app_state_set"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.AFTER_REPLAY


@dataclass(frozen=True, slots=True)
class FileObservationRecorded:
    observation_kind: str
    path: str
    digest: str | None = None
    conflict_key: str | None = None
    kind: str = "file_observation_recorded"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.BEFORE_REPLAY


@dataclass(frozen=True, slots=True)
class MemoryAppended:
    scope: str
    entry: MemoryEntry
    kind: str = "memory_appended"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.AFTER_REPLAY


@dataclass(frozen=True, slots=True)
class CapabilityRefreshRequested:
    scope: str
    reason: str
    kind: str = "capability_refresh_requested"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.BEFORE_REPLAY


@dataclass(frozen=True, slots=True)
class NotificationEmitted:
    level: str
    message: str
    kind: str = "notification_emitted"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.BEFORE_REPLAY


@dataclass(frozen=True, slots=True)
class TranscriptAttachmentAdded:
    attachment_type: str
    payload: Mapping[str, Any]
    kind: str = "transcript_attachment_added"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.WITH_REPLAY


@dataclass(frozen=True, slots=True)
class LegacyContextModifierWrapped:
    adapter_label: str
    summary: str
    modifier: Callable[[Any], Any] | None = None
    kind: str = "legacy_context_modifier_wrapped"
    apply_phase: ContextUpdatePhase = ContextUpdatePhase.AFTER_REPLAY


ContextUpdate = (
    AppStateSet
    | FileObservationRecorded
    | MemoryAppended
    | CapabilityRefreshRequested
    | NotificationEmitted
    | TranscriptAttachmentAdded
    | LegacyContextModifierWrapped
)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    resolved_call: ResolvedToolCall
    status: ToolCallStatus
    terminal_reason: str | None
    raw_output: Any | None = None
    error_message: str | None = None
    result_block: ToolResultBlock | None = None
    result_summary: Any | None = None
    context_updates: tuple[ContextUpdate, ...] = ()
    completion_index: int = 0
    replay_index: int = 0
    replay_eligible: bool = False


@dataclass(frozen=True, slots=True)
class EnvelopeObserved:
    tool_use_id: str
    replay_index: int
    assistant_message_id: str
    raw_tool_name: str
    kind: str = "envelope_observed"


@dataclass(frozen=True, slots=True)
class ResolutionStarted:
    tool_use_id: str
    replay_index: int
    kind: str = "resolution_started"


@dataclass(frozen=True, slots=True)
class ResolutionCompleted:
    tool_use_id: str
    replay_index: int
    resolution_status: ToolResolutionStatus
    canonical_tool_name: str | None
    kind: str = "resolution_completed"


@dataclass(frozen=True, slots=True)
class ExecutionQueued:
    tool_use_id: str
    replay_index: int
    lane_kind: ToolSchedulerLaneKind
    lane_key: str | None = None
    kind: str = "execution_queued"


@dataclass(frozen=True, slots=True)
class ExecutionStarted:
    tool_use_id: str
    replay_index: int
    lane_kind: ToolSchedulerLaneKind
    kind: str = "execution_started"


@dataclass(frozen=True, slots=True)
class ProgressEmitted:
    tool_use_id: str
    replay_index: int
    progress_id: str
    message: str
    percent: float | None = None
    kind: str = "progress_emitted"


@dataclass(frozen=True, slots=True)
class OutcomeRecorded:
    tool_use_id: str
    replay_index: int
    completion_index: int
    status: ToolCallStatus
    kind: str = "outcome_recorded"


@dataclass(frozen=True, slots=True)
class ReplayCommitted:
    tool_use_id: str
    replay_index: int
    completion_index: int
    status: ToolCallStatus
    kind: str = "replay_committed"


ToolLifecycleEvent = (
    EnvelopeObserved
    | ResolutionStarted
    | ResolutionCompleted
    | ExecutionQueued
    | ExecutionStarted
    | ProgressEmitted
    | OutcomeRecorded
    | ReplayCommitted
)


class LifecycleTransitionError(RuntimeError):
    pass


def project_lifecycle_stage(
    current: ToolLifecycleStage | None,
    event: ToolLifecycleEvent,
) -> ToolLifecycleStage:
    if isinstance(event, EnvelopeObserved):
        _require_transition(current, None)
        return ToolLifecycleStage.OBSERVED
    if isinstance(event, ResolutionStarted):
        _require_transition(current, ToolLifecycleStage.OBSERVED)
        return ToolLifecycleStage.RESOLVING
    if isinstance(event, ResolutionCompleted):
        _require_transition(current, ToolLifecycleStage.RESOLVING)
        if event.resolution_status == ToolResolutionStatus.EXECUTABLE:
            return ToolLifecycleStage.QUEUED
        return ToolLifecycleStage.RESOLVED_NON_EXECUTABLE
    if isinstance(event, ExecutionQueued):
        if current != ToolLifecycleStage.QUEUED:
            raise LifecycleTransitionError(f"Invalid queued transition from {current!r}")
        return ToolLifecycleStage.QUEUED
    if isinstance(event, ExecutionStarted):
        _require_transition(current, ToolLifecycleStage.QUEUED)
        return ToolLifecycleStage.RUNNING
    if isinstance(event, ProgressEmitted):
        if current != ToolLifecycleStage.RUNNING:
            raise LifecycleTransitionError(f"Progress emitted outside running stage: {current!r}")
        return ToolLifecycleStage.RUNNING
    if isinstance(event, OutcomeRecorded):
        if current not in {
            ToolLifecycleStage.RUNNING,
            ToolLifecycleStage.QUEUED,
            ToolLifecycleStage.RESOLVED_NON_EXECUTABLE,
        }:
            raise LifecycleTransitionError(f"Invalid outcome transition from {current!r}")
        return ToolLifecycleStage.TERMINAL_PENDING_REPLAY
    if isinstance(event, ReplayCommitted):
        _require_transition(current, ToolLifecycleStage.TERMINAL_PENDING_REPLAY)
        return ToolLifecycleStage.REPLAYED
    raise LifecycleTransitionError(f"Unsupported lifecycle event: {event!r}")


def _require_transition(
    current: ToolLifecycleStage | None,
    expected: ToolLifecycleStage | None,
) -> None:
    if current != expected:
        raise LifecycleTransitionError(
            f"Invalid lifecycle transition from {current!r}; expected {expected!r}"
        )


def _digest_path(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _stable_progress_id(label: str, metadata: Mapping[str, Any] | None) -> str:
    payload = f"{label}|{sorted((metadata or {}).items())}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
