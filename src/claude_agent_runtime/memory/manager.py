from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..contracts import MessageRole, RuntimeMessage
from ..definitions import AgentDefinition, MemoryScope
from .models import MemoryDocument, MemoryEntry, ResolvedMemoryScope
from .providers import FileMemoryProvider, MemoryProvider

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "the",
    "this",
    "to",
    "use",
    "we",
    "what",
}


@dataclass(slots=True)
class MemoryManager:
    provider: MemoryProvider = field(default_factory=FileMemoryProvider)
    project_root: Path | None = None
    user_root: Path = field(default_factory=lambda: Path.home() / ".claude")
    default_scope: MemoryScope = MemoryScope.PROJECT
    retrieval_limit: int = 3
    _session_defaults: dict[str, ResolvedMemoryScope] = field(default_factory=dict, init=False)

    def initialize_session(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        set_default: bool = True,
    ) -> ResolvedMemoryScope:
        if set_default:
            context = self.context_for_scope(
                session_id=session_id,
                scope=agent.memory or self.default_scope,
                cwd=cwd,
            )
            self._session_defaults[session_id] = context
        else:
            context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
            if session_id not in self._session_defaults:
                self._session_defaults[session_id] = context
        _ = self.provider.load_entrypoint(context)
        return context

    def resolve_context(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> ResolvedMemoryScope:
        scope = agent.memory
        if scope is None:
            default_context = self._session_defaults.get(session_id)
            if default_context is not None:
                return default_context
            scope = self.default_scope
        return self.context_for_scope(session_id=session_id, scope=scope, cwd=cwd)

    def context_for_scope(
        self,
        *,
        session_id: str,
        scope: MemoryScope,
        cwd: str | Path,
    ) -> ResolvedMemoryScope:
        working_dir = Path(cwd).resolve()
        if scope == MemoryScope.USER:
            boundary_root = self.user_root.resolve()
            memory_root = boundary_root / "memory"
        elif scope == MemoryScope.PROJECT:
            boundary_root = (self.project_root or working_dir).resolve()
            memory_root = boundary_root / ".claude" / "memory"
        else:
            boundary_root = working_dir
            memory_root = boundary_root / ".claude" / "memory"
        return ResolvedMemoryScope(
            session_id=session_id,
            scope=scope,
            boundary_root=boundary_root,
            memory_root=memory_root,
            entrypoint_path=memory_root / "MEMORY.md",
            documents_dir=memory_root / "documents",
        )

    def guarded_roots(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> tuple[Path, ...]:
        roots: list[Path] = []
        for scope in (MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.LOCAL):
            context = self.context_for_scope(session_id=session_id, scope=scope, cwd=cwd)
            if context.memory_root not in roots:
                roots.append(context.memory_root)
        active = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd).memory_root
        if active not in roots:
            roots.append(active)
        return tuple(roots)

    def collect(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> tuple[str, ...]:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        entrypoint = self.provider.load_entrypoint(context)
        documents = self.provider.list_documents(context)
        relevant = self._retrieve_relevant(_latest_user_text(messages), documents)
        fragments: list[str] = []
        if entrypoint is not None and entrypoint.content.strip():
            fragments.append(entrypoint.render())
        fragments.extend(document.render() for document in relevant)
        return tuple(dict.fromkeys(fragment for fragment in fragments if fragment.strip()))

    def record_turn(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> tuple[MemoryDocument, ...]:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        entries = self._extract_entries(messages)
        return self.provider.persist_entries(context, entries)

    def _retrieve_relevant(
        self,
        query: str,
        documents: Sequence[MemoryDocument],
    ) -> tuple[MemoryDocument, ...]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return ()

        scored: list[tuple[int, MemoryDocument]] = []
        for document in documents:
            document_tokens = _tokenize(f"{document.title} {document.content}")
            if not document_tokens:
                continue
            overlap = len(query_tokens & document_tokens)
            if overlap <= 0:
                continue
            scored.append((overlap, document))

        scored.sort(key=lambda item: (-item[0], item[1].path.name))
        return tuple(document for _, document in scored[: self.retrieval_limit])

    def _extract_entries(self, messages: Sequence[RuntimeMessage]) -> tuple[MemoryEntry, ...]:
        extracted: list[MemoryEntry] = []
        seen: set[str] = set()
        for message in messages:
            if message.role != MessageRole.USER:
                continue
            for sentence in _split_sentences(message.text):
                fact = _extract_fact(sentence)
                if fact is None or fact.lower() in seen:
                    continue
                seen.add(fact.lower())
                extracted.append(
                    MemoryEntry(
                        title=_title_for_fact(fact),
                        content=fact,
                        metadata={"source": "post_turn_extraction"},
                    )
                )
        return tuple(extracted[:3])


@dataclass(slots=True)
class MemoryManagerService:
    manager: MemoryManager = field(default_factory=MemoryManager)

    def __init__(
        self,
        *,
        provider: MemoryProvider | None = None,
        project_root: Path | None = None,
        user_root: Path | None = None,
        default_scope: MemoryScope = MemoryScope.PROJECT,
        retrieval_limit: int = 3,
        manager: MemoryManager | None = None,
    ) -> None:
        if manager is not None:
            self.manager = manager
            return
        self.manager = MemoryManager(
            provider=provider or FileMemoryProvider(),
            project_root=project_root,
            user_root=user_root or (Path.home() / ".claude"),
            default_scope=default_scope,
            retrieval_limit=retrieval_limit,
        )

    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        runtime_context: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        _ = turn_id, runtime_context
        return self.manager.collect(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
        )

    async def start_session(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        set_default: bool = True,
    ) -> ResolvedMemoryScope:
        return self.manager.initialize_session(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            set_default=set_default,
        )

    async def record_turn(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> tuple[MemoryDocument, ...]:
        return self.manager.record_turn(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
        )

    def resolve_context(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> ResolvedMemoryScope:
        return self.manager.resolve_context(session_id=session_id, agent=agent, cwd=cwd)

    def context_for_scope(
        self,
        *,
        session_id: str,
        scope: MemoryScope,
        cwd: str | Path,
    ) -> ResolvedMemoryScope:
        return self.manager.context_for_scope(session_id=session_id, scope=scope, cwd=cwd)

    def guarded_roots(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> tuple[Path, ...]:
        return self.manager.guarded_roots(session_id=session_id, agent=agent, cwd=cwd)


def _latest_user_text(messages: Sequence[RuntimeMessage]) -> str:
    for message in reversed(messages):
        if message.role == MessageRole.USER and message.text.strip():
            return message.text
    return ""


def _split_sentences(text: str) -> Iterable[str]:
    for chunk in re.split(r"[.!?\n]+", text):
        normalized = " ".join(chunk.strip().split())
        if normalized:
            yield normalized


def _extract_fact(sentence: str) -> str | None:
    lowered = sentence.lower()
    if len(sentence) < 12:
        return None
    for prefix in ("remember that ", "remember ", "note that "):
        if lowered.startswith(prefix):
            return _normalize_fact(sentence[len(prefix) :])
    if lowered.startswith(
        (
            "i prefer ",
            "my project uses ",
            "the project uses ",
            "our project uses ",
            "we use ",
            "our repo uses ",
            "my name is ",
            "call me ",
            "always ",
            "never ",
        )
    ):
        return _normalize_fact(sentence)
    return None


def _normalize_fact(value: str) -> str:
    normalized = " ".join(value.strip(" -:").split())
    if not normalized:
        return normalized
    return normalized[0].upper() + normalized[1:]


def _title_for_fact(fact: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", fact)[:6]
    if not words:
        return "Memory note"
    return " ".join(words)


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    }
