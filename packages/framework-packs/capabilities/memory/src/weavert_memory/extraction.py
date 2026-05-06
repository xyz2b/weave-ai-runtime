from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Sequence

from weavert.contracts import MessageRole, RuntimeMessage
from .models import MemoryEntry, normalize_memory_segment

_MAX_EXTRACTION_DECISIONS = 8
_QUESTION_PREFIXES = ("how ", "what ", "why ", "when ", "where ", "who ", "can ", "could ", "should ", "would ")
_TRANSIENT_PREFIXES = (
    "today ",
    "for now ",
    "right now ",
    "this turn ",
    "this pass ",
    "this session ",
    "next ",
    "todo",
    "let's ",
    "we need to ",
    "i need to ",
)
_TRANSIENT_MARKERS = (
    "temporary",
    "temporarily",
    "one-off",
    "for this turn",
    "for this pass",
    "for this session",
    "this turn only",
    "this pass only",
    "this session only",
    "only for this turn",
    "only for this pass",
    "only for this session",
)
_TRANSIENT_TEMPORAL_MARKERS = (" today", "today ", "for now", "right now", "this turn", "this pass", "this session")
_TRANSIENT_ACTION_WORDS = (
    "implement",
    "fix",
    "check",
    "update",
    "review",
    "investigate",
    "rename",
    "refactor",
    "ship",
    "build",
    "verify",
    "continue",
    "debug",
    "keep",
    "use",
    "answer",
    "respond",
)
_PROJECT_MARKERS = (
    "project uses",
    "the project uses",
    "our project uses",
    "repo uses",
    "the repo uses",
    "our repo uses",
    "repository uses",
    "project convention",
    "repo convention",
    "repository convention",
    "project standard",
    "repo standard",
)
_SESSION_THREAD_MARKERS = (
    "blocked",
    "blocking progress",
    "waiting for",
    "waiting on",
    "follow up",
    "pending answer",
    "unresolved",
    "need user input",
)
_SESSION_CONTINUITY_MARKERS = (
    "we are currently",
    "we're currently",
    "currently debugging",
    "current objective",
    "keep in mind",
    "continue with",
    "before the next step",
    "recent decision",
    "session continuity",
)
_AGENT_WORKFLOW_MARKERS = (
    "when verifying",
    "before broader",
    "for small code changes",
    "for this agent",
    "for the agent",
    "delegated",
    "namespace",
    "start with",
)
_SMALLTALK = {"thanks", "thank you", "ok", "okay", "sounds good", "done", "got it"}
_SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|password|passwd|secret|token|credential|private key)\b", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|gho|ghu|glpat|xoxb|xoxp)-[a-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_BACKTICK_COMMAND_PATTERN = re.compile(r"`([^`]+)`")
_COMMAND_PATTERN = re.compile(
    r"\b(?:run|use|start with|check|invoke|execute|prefer)\s+([a-z0-9_.:/-]+(?:\s+[a-z0-9_.:/=-]+){0,5})",
    re.IGNORECASE,
)
_CLI_COMMAND_HEADS = frozenset(
    {
        "pytest",
        "python",
        "python3",
        "uv",
        "ruff",
        "cargo",
        "npm",
        "pnpm",
        "yarn",
        "make",
        "cmake",
        "go",
        "node",
        "npx",
        "docker",
        "kubectl",
        "git",
        "bash",
        "sh",
        "just",
        "bazel",
        "gradle",
        "mvn",
    }
)
_CLI_COMMAND_PAIRS = frozenset(
    {
        ("cargo", "test"),
        ("go", "test"),
        ("python", "-m"),
        ("python3", "-m"),
        ("uv", "run"),
        ("git", "status"),
        ("git", "diff"),
        ("git", "show"),
    }
)
_TAG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("testing", re.compile(r"\b(?:pytest|test|tests|cargo test|unittest)\b", re.IGNORECASE)),
    ("workflow", re.compile(r"\b(?:run|check|build|verify|workflow|command)\b", re.IGNORECASE)),
    ("python", re.compile(r"\b(?:python|pytest|ruff|uv)\b", re.IGNORECASE)),
    ("style", re.compile(r"\b(?:concise|brief|short|verbose)\b", re.IGNORECASE)),
)
_BACKGROUND_SYNTHESIS_LIMIT = 3
_TOPIC_STOPWORDS = {
    "about",
    "after",
    "agent",
    "answer",
    "before",
    "broad",
    "change",
    "changes",
    "check",
    "current",
    "detail",
    "details",
    "help",
    "here",
    "keep",
    "need",
    "next",
    "note",
    "repo",
    "response",
    "responses",
    "review",
    "service",
    "should",
    "step",
    "steps",
    "task",
    "tests",
    "things",
    "turn",
    "update",
    "user",
    "verify",
    "work",
    "workflow",
}


@dataclass(frozen=True, slots=True)
class MemoryExtractionDecision:
    fact_type: str
    title: str
    content: str
    target_layer: str
    namespace: str
    retention: str
    merge_policy: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_message_ids: tuple[str, ...] = ()
    source_roles: tuple[str, ...] = ()
    reason: str | None = None

    def to_entry(self) -> MemoryEntry:
        return MemoryEntry(
            title=self.title,
            content=self.content,
            metadata=dict(self.metadata),
        )


def extract_memory_decisions(
    messages: Sequence[RuntimeMessage],
    *,
    agent_name: str,
) -> tuple[MemoryExtractionDecision, ...]:
    normalized_agent = normalize_memory_segment(agent_name, default="agent")
    decisions: list[MemoryExtractionDecision] = []
    seen: set[tuple[str, str]] = set()

    for message in messages:
        if message.role not in {MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL}:
            continue
        for sentence in _split_sentences(message.text):
            decision = _classify_sentence(
                sentence,
                role=message.role,
                message_id=message.message_id,
                agent_name=normalized_agent,
            )
            if decision is None:
                continue
            dedupe_key = (decision.fact_type, decision.content.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            decisions.append(decision)
            if len(decisions) >= _MAX_EXTRACTION_DECISIONS:
                return tuple(decisions)
    return tuple(decisions)


def synthesize_background_memory_decisions(
    messages: Sequence[RuntimeMessage],
    *,
    agent_name: str,
) -> tuple[MemoryExtractionDecision, ...]:
    normalized_agent = normalize_memory_segment(agent_name, default="agent")
    decisions: list[MemoryExtractionDecision] = []

    repeated_preference = _synthesize_repeated_preference(messages)
    if repeated_preference is not None:
        decisions.append(repeated_preference)

    topic_memory = _synthesize_topic_memory(messages)
    if topic_memory is not None:
        decisions.append(topic_memory)

    agent_note = _synthesize_agent_note(messages, agent_name=normalized_agent)
    if agent_note is not None:
        decisions.append(agent_note)

    return tuple(decisions[:_BACKGROUND_SYNTHESIS_LIMIT])


def _split_sentences(text: str) -> tuple[str, ...]:
    chunks = re.findall(r"[^.!?\n]+[.!?]?", text)
    sentences = [" ".join(chunk.strip().split()) for chunk in chunks]
    return tuple(sentence for sentence in sentences if sentence)


def _synthesize_repeated_preference(messages: Sequence[RuntimeMessage]) -> MemoryExtractionDecision | None:
    evidence: dict[str, dict[str, Any]] = {}
    for message in messages:
        if message.role != MessageRole.USER:
            continue
        for sentence in _split_sentences(message.text):
            normalized = _strip_memory_prefix(sentence)
            if not normalized or _has_transient_qualifier(normalized.lower()) or not _looks_preference(normalized):
                continue
            key = _conflict_key("preference", normalized)
            record = evidence.setdefault(
                key,
                {
                    "content": normalized,
                    "message_ids": [],
                    "roles": [],
                },
            )
            record["message_ids"].append(message.message_id)
            record["roles"].append(message.role.value)

    repeated = [
        record
        for record in evidence.values()
        if len(dict.fromkeys(record["message_ids"])) >= 2
    ]
    if not repeated:
        return None

    best = max(repeated, key=lambda record: len(dict.fromkeys(record["message_ids"])))
    normalized_content = _normalize_content(str(best["content"]))
    content = f"User repeatedly reinforced this preference across recent turns: {normalized_content}"
    confidence = min(0.95, 0.6 + (0.1 * len(dict.fromkeys(best["message_ids"]))))
    return _background_durable_decision(
        fact_type="preference",
        title=f"Repeated Preference {_title_for_fact(normalized_content)}".strip(),
        content=content,
        target_layer="shared_long_term",
        namespace="shared",
        retention="durable_until_superseded",
        merge_policy="require_multi_source_confirmation",
        source_message_ids=best["message_ids"],
        source_roles=best["roles"],
        confidence=confidence,
        extra_metadata={"conflict_key": _conflict_key("preference", normalized_content)},
    )


def _synthesize_topic_memory(messages: Sequence[RuntimeMessage]) -> MemoryExtractionDecision | None:
    token_counter: Counter[str] = Counter()
    token_messages: dict[str, set[str]] = defaultdict(set)
    supporting_sentences: dict[str, list[str]] = defaultdict(list)
    source_roles: dict[str, list[str]] = defaultdict(list)

    for message in messages:
        if message.role not in {MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL}:
            continue
        for sentence in _split_sentences(message.text):
            normalized = _strip_memory_prefix(sentence)
            if not normalized or _looks_sensitive(normalized) or _looks_transient_task(normalized):
                continue
            tokens = {
                token
                for token in re.findall(r"[a-z0-9]+", normalized.lower())
                if len(token) >= 4 and token not in _TOPIC_STOPWORDS
            }
            for token in tokens:
                token_counter[token] += 1
                token_messages[token].add(message.message_id)
                if len(supporting_sentences[token]) < 3:
                    supporting_sentences[token].append(_normalize_content(normalized))
                source_roles[token].append(message.role.value)

    ranked = [
        token
        for token, count in token_counter.most_common()
        if count >= 3 and len(token_messages[token]) >= 2
    ]
    if not ranked:
        return None

    topic = ranked[0]
    examples = supporting_sentences[topic][:2]
    content = f"Recent discussion repeatedly centered on {topic}. " + " ".join(examples)
    confidence = min(0.9, 0.55 + (0.1 * len(token_messages[topic])))
    return _background_durable_decision(
        fact_type="topic_memory",
        title=f"Topic Memory {topic.title()}",
        content=content,
        target_layer="shared_long_term",
        namespace="shared",
        retention="durable_until_superseded",
        merge_policy="synthesize_then_merge",
        source_message_ids=tuple(sorted(token_messages[topic])),
        source_roles=source_roles[topic],
        confidence=confidence,
        extra_metadata={"conflict_key": f"topic_memory.{normalize_memory_segment(topic, default='topic')}"},
    )


def _synthesize_agent_note(
    messages: Sequence[RuntimeMessage],
    *,
    agent_name: str,
) -> MemoryExtractionDecision | None:
    heuristics: list[str] = []
    message_ids: list[str] = []
    roles: list[str] = []

    for message in messages:
        if message.role != MessageRole.ASSISTANT:
            continue
        for sentence in _split_sentences(message.text):
            normalized = _strip_memory_prefix(sentence)
            if not normalized or not _looks_agent_workflow(normalized, role=message.role, agent_name=agent_name):
                continue
            normalized_sentence = _normalize_content(normalized)
            if normalized_sentence in heuristics:
                continue
            heuristics.append(normalized_sentence)
            message_ids.append(message.message_id)
            roles.append(message.role.value)

    if len(heuristics) < 2:
        return None

    content = "Durable agent workflow note: " + "; ".join(heuristics[:3])
    topic_seed = heuristics[0]
    return _background_durable_decision(
        fact_type="agent_note",
        title=f"Agent Note {agent_name}",
        content=content,
        target_layer="agent_namespace",
        namespace=f"agent:{agent_name}",
        retention="durable_reviewable",
        merge_policy="append_with_dedupe",
        source_message_ids=message_ids,
        source_roles=roles,
        confidence=min(0.9, 0.55 + (0.1 * len(heuristics))),
        extra_metadata={
            "agent_namespace": agent_name,
            "conflict_key": _conflict_key("agent_note", topic_seed, agent_name=agent_name),
        },
    )


def _classify_sentence(
    sentence: str,
    *,
    role: MessageRole,
    message_id: str,
    agent_name: str,
) -> MemoryExtractionDecision | None:
    normalized = _strip_memory_prefix(sentence)
    if not normalized or _should_ignore_sentence(normalized, role=role):
        return None

    if _looks_sensitive(normalized):
        return _drop_decision(
            "sensitive_value",
            normalized,
            role=role,
            message_id=message_id,
            reason="sensitive_value",
        )
    if _looks_transient_task(normalized):
        return _drop_decision(
            "transient_task",
            normalized,
            role=role,
            message_id=message_id,
            reason="transient_task",
        )
    if _looks_session_thread(normalized, role=role):
        return _session_decision(
            fact_type="session_thread",
            content=normalized,
            role=role,
            message_id=message_id,
            target_layer="session_open_threads",
            merge_policy="upsert_by_thread_key",
            reason="session_thread",
        )
    if _looks_session_continuity(normalized):
        return _session_decision(
            fact_type="session_continuity",
            content=normalized,
            role=role,
            message_id=message_id,
            target_layer="session_summary",
            merge_policy="replace_summary_window",
            reason="session_continuity",
        )
    if _looks_agent_workflow(normalized, role=role, agent_name=agent_name):
        return _durable_decision(
            fact_type="agent_workflow",
            content=normalized,
            role=role,
            message_id=message_id,
            target_layer="agent_namespace",
            namespace=f"agent:{agent_name}",
            retention="durable_reviewable",
            merge_policy="overwrite_inside_namespace",
            extra_metadata={
                "agent_namespace": agent_name,
                "conflict_key": _conflict_key("agent_workflow", normalized, agent_name=agent_name),
            },
        )
    if _looks_project_convention(normalized):
        return _durable_decision(
            fact_type="project_convention",
            content=normalized,
            role=role,
            message_id=message_id,
            target_layer="shared_long_term",
            namespace="shared",
            retention="durable_until_revoked",
            merge_policy="merge_with_provenance",
            extra_metadata={"conflict_key": _conflict_key("project_convention", normalized)},
        )
    if _looks_workflow_command(normalized):
        return _durable_decision(
            fact_type="workflow_command",
            content=normalized,
            role=role,
            message_id=message_id,
            target_layer="shared_long_term",
            namespace="shared",
            retention="durable_until_revoked",
            merge_policy="merge_with_last_confirmed_at",
            extra_metadata={"conflict_key": _conflict_key("workflow_command", normalized)},
        )
    if _looks_preference(normalized):
        return _durable_decision(
            fact_type="preference",
            content=normalized,
            role=role,
            message_id=message_id,
            target_layer="shared_long_term",
            namespace="shared",
            retention="durable_until_superseded",
            merge_policy="overwrite_on_newer_confirmation",
            extra_metadata={"conflict_key": _conflict_key("preference", normalized)},
        )
    if _looks_noise(normalized):
        return _drop_decision(
            "ephemeral_observation",
            normalized,
            role=role,
            message_id=message_id,
            reason="obvious_noise",
        )
    return None


def _durable_decision(
    *,
    fact_type: str,
    content: str,
    role: MessageRole,
    message_id: str,
    target_layer: str,
    namespace: str,
    retention: str,
    merge_policy: str,
    extra_metadata: dict[str, Any] | None = None,
) -> MemoryExtractionDecision:
    metadata: dict[str, Any] = {
        "memory_kind": fact_type,
        "namespace": namespace,
        "retention": retention,
        "merge_policy": merge_policy,
        "source_pathway": "rule",
        "source_message_ids": [message_id],
        "tags": list(_infer_tags(content)),
    }
    if extra_metadata is not None:
        metadata.update(extra_metadata)
    return MemoryExtractionDecision(
        fact_type=fact_type,
        title=_title_for_fact(content),
        content=_normalize_content(content),
        target_layer=target_layer,
        namespace=namespace,
        retention=retention,
        merge_policy=merge_policy,
        metadata=metadata,
        source_message_ids=(message_id,),
        source_roles=(role.value,),
    )


def _background_durable_decision(
    *,
    fact_type: str,
    title: str,
    content: str,
    target_layer: str,
    namespace: str,
    retention: str,
    merge_policy: str,
    source_message_ids: Sequence[str],
    source_roles: Sequence[str],
    confidence: float,
    extra_metadata: dict[str, Any] | None = None,
) -> MemoryExtractionDecision:
    normalized_content = _normalize_content(content)
    metadata: dict[str, Any] = {
        "memory_kind": fact_type,
        "namespace": namespace,
        "retention": retention,
        "merge_policy": merge_policy,
        "source_pathway": "background_extractor",
        "source_message_ids": list(dict.fromkeys(source_message_ids)),
        "source_roles": list(dict.fromkeys(source_roles)),
        "tags": list(_infer_tags(normalized_content)),
        "confidence": confidence,
        "summary": normalized_content,
    }
    if extra_metadata is not None:
        metadata.update(extra_metadata)
    return MemoryExtractionDecision(
        fact_type=fact_type,
        title=title,
        content=normalized_content,
        target_layer=target_layer,
        namespace=namespace,
        retention=retention,
        merge_policy=merge_policy,
        metadata=metadata,
        source_message_ids=tuple(dict.fromkeys(source_message_ids)),
        source_roles=tuple(dict.fromkeys(source_roles)),
    )


def _session_decision(
    *,
    fact_type: str,
    content: str,
    role: MessageRole,
    message_id: str,
    target_layer: str,
    merge_policy: str,
    reason: str,
) -> MemoryExtractionDecision:
    return MemoryExtractionDecision(
        fact_type=fact_type,
        title=_title_for_fact(content),
        content=_normalize_content(content),
        target_layer=target_layer,
        namespace="session",
        retention="session_lifetime",
        merge_policy=merge_policy,
        source_message_ids=(message_id,),
        source_roles=(role.value,),
        reason=reason,
    )


def _drop_decision(
    fact_type: str,
    content: str,
    *,
    role: MessageRole,
    message_id: str,
    reason: str,
) -> MemoryExtractionDecision:
    return MemoryExtractionDecision(
        fact_type=fact_type,
        title=_title_for_fact(content),
        content=_normalize_content(content),
        target_layer="do_not_persist",
        namespace="none",
        retention="drop",
        merge_policy="no_write",
        source_message_ids=(message_id,),
        source_roles=(role.value,),
        reason=reason,
    )


def _strip_memory_prefix(text: str) -> str:
    normalized = " ".join(text.strip().split())
    lowered = normalized.lower()
    for prefix in ("remember that ", "remember ", "note that "):
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def _should_ignore_sentence(text: str, *, role: MessageRole) -> bool:
    if len(text) < 8:
        return True
    lowered = text.lower()
    if role == MessageRole.USER and (text.endswith("?") or lowered.startswith(_QUESTION_PREFIXES)):
        return True
    return False


def _looks_sensitive(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)


def _looks_preference(text: str) -> bool:
    lowered = text.lower()
    if _has_transient_qualifier(lowered):
        return False
    return lowered.startswith(
        (
            "i prefer ",
            "please keep ",
            "call me ",
            "my name is ",
            "always answer ",
            "never answer ",
        )
    )


def _looks_transient_task(text: str) -> bool:
    lowered = text.lower()
    has_action_word = any(word in lowered for word in _TRANSIENT_ACTION_WORDS)
    if any(lowered.startswith(prefix) for prefix in _TRANSIENT_PREFIXES):
        return has_action_word
    if _has_transient_qualifier(lowered):
        return has_action_word
    if any(marker in lowered for marker in _TRANSIENT_TEMPORAL_MARKERS):
        return has_action_word
    return False


def _looks_session_thread(text: str, *, role: MessageRole) -> bool:
    lowered = text.lower()
    if role == MessageRole.ASSISTANT and text.endswith("?"):
        return True
    return any(marker in lowered for marker in _SESSION_THREAD_MARKERS)


def _looks_session_continuity(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SESSION_CONTINUITY_MARKERS)


def _looks_agent_workflow(text: str, *, role: MessageRole, agent_name: str) -> bool:
    lowered = text.lower()
    command = _extract_workflow_command(text)
    if command is None:
        return False
    if f"agent {agent_name}" in lowered or f"{agent_name} agent" in lowered:
        return True
    if "agent" in lowered and any(marker in lowered for marker in _AGENT_WORKFLOW_MARKERS):
        return True
    return role == MessageRole.ASSISTANT and any(marker in lowered for marker in _AGENT_WORKFLOW_MARKERS)


def _looks_project_convention(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _PROJECT_MARKERS):
        return True
    if any(marker in lowered for marker in ("project should", "repo should", "repository should")):
        return True
    return False


def _looks_workflow_command(text: str) -> bool:
    lowered = text.lower()
    command = _extract_workflow_command(text)
    if command is None:
        return False
    if any(marker in lowered for marker in _PROJECT_MARKERS):
        return False
    return True


def _looks_noise(text: str) -> bool:
    lowered = text.lower().strip(" .!?")
    if lowered in _SMALLTALK:
        return True
    return len(re.findall(r"[a-z0-9]+", lowered)) < 3


def _extract_command(text: str) -> str | None:
    match = _BACKTICK_COMMAND_PATTERN.search(text)
    if match is not None:
        return " ".join(match.group(1).strip().split())
    match = _COMMAND_PATTERN.search(text)
    if match is None:
        return None
    candidate = match.group(1).strip().rstrip(".,")
    if len(candidate) < 3:
        return None
    return " ".join(candidate.split())


def _extract_workflow_command(text: str) -> str | None:
    command = _extract_command(text)
    if command is None:
        return None
    if not _looks_cli_command(command):
        return None
    return command


def _looks_cli_command(command: str) -> bool:
    tokens = [token.lower() for token in command.split() if token.strip()]
    if not tokens:
        return False
    if tokens[0] in _CLI_COMMAND_HEADS:
        return True
    if len(tokens) >= 2 and (tokens[0], tokens[1]) in _CLI_COMMAND_PAIRS:
        return True
    if "/" in tokens[0] or tokens[0].endswith((".py", ".sh")):
        return True
    return any(token.startswith("-") for token in tokens[1:])


def _has_transient_qualifier(lowered: str) -> bool:
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


def _infer_tags(text: str) -> tuple[str, ...]:
    tags: list[str] = []
    for tag, pattern in _TAG_PATTERNS:
        if pattern.search(text):
            tags.append(tag)
    return tuple(dict.fromkeys(tags))


def _conflict_key(fact_type: str, text: str, *, agent_name: str | None = None) -> str:
    command = _extract_workflow_command(text) or _extract_command(text)
    if command is not None:
        key = normalize_memory_segment(command, default=fact_type)
    else:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        key = normalize_memory_segment("-".join(tokens[:4]), default=fact_type)
    if fact_type in {"agent_workflow", "agent_note"} and agent_name is not None:
        return f"{fact_type}.{agent_name}.{key}"
    return f"{fact_type}.{key}"


def _normalize_content(text: str) -> str:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return normalized
    return normalized[0].upper() + normalized[1:]


def _title_for_fact(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)[:6]
    if not words:
        return "Memory note"
    return " ".join(words)
