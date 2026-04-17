from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..contracts import MessageRole, RuntimeMessage
from ..definitions import AgentDefinition, MemoryScope
from .models import MemoryDocument, MemoryEntry, ResolvedMemoryScope, normalize_memory_segment
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
class LongTermMemory:
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
        self.provider.prepare_context(context)
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
        documents_dir = memory_root / "documents"
        manifests_dir = memory_root / "manifests"
        agents_dir = memory_root / "agents"
        sessions_dir = memory_root / "sessions"
        consolidations_dir = memory_root / "consolidations"
        return ResolvedMemoryScope(
            session_id=session_id,
            scope=scope,
            boundary_root=boundary_root,
            memory_root=memory_root,
            entrypoint_path=memory_root / "MEMORY.md",
            documents_dir=documents_dir,
            shared_documents_dir=documents_dir / "shared",
            preferences_documents_dir=documents_dir / "preferences",
            conventions_documents_dir=documents_dir / "conventions",
            topics_documents_dir=documents_dir / "topics",
            manifests_dir=manifests_dir,
            long_term_manifest_path=manifests_dir / "long-term-manifest.json",
            agent_manifest_path=manifests_dir / "agent-manifest.json",
            session_manifest_path=manifests_dir / "session-manifest.json",
            consolidation_manifest_path=manifests_dir / "consolidation-manifest.json",
            agents_dir=agents_dir,
            sessions_dir=sessions_dir,
            consolidations_dir=consolidations_dir,
            consolidation_checkpoints_dir=consolidations_dir / "checkpoints",
            consolidation_logs_dir=consolidations_dir / "logs",
            consolidation_staging_dir=consolidations_dir / "staging",
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
        query = _latest_user_text(messages)
        relevant, _ = self._collect_layered_retrieval(
            context=context,
            agent=agent,
            query=query,
        )
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
        entries = self._extract_entries(messages)
        return self.persist_entries(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            entries=entries,
        )

    def persist_entries(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        return self.provider.persist_entries(context, entries)

    def persist_agent_namespace_entries(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]:
        normalized_agent = normalize_memory_segment(agent.name, default="agent")
        bound_entries = tuple(_bind_entry_to_agent_namespace(entry, normalized_agent) for entry in entries)
        return self.persist_entries(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            entries=bound_entries,
        )

    def collect_with_trace(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        entrypoint = self.provider.load_entrypoint(context)
        relevant, trace = self._collect_layered_retrieval(
            context=context,
            agent=agent,
            query=_latest_user_text(messages),
        )
        fragments: list[str] = []
        if entrypoint is not None and entrypoint.content.strip():
            fragments.append(entrypoint.render())
        fragments.extend(document.render() for document in relevant)
        deduped = tuple(dict.fromkeys(fragment for fragment in fragments if fragment.strip()))
        trace["turn_id"] = turn_id
        return deduped, trace

    def _collect_layered_retrieval(
        self,
        *,
        context: ResolvedMemoryScope,
        agent: AgentDefinition,
        query: str,
    ) -> tuple[tuple[MemoryDocument, ...], dict[str, Any]]:
        applied_filters: list[str] = []
        selected_doc_ids: list[str] = []
        budget_decisions: list[dict[str, Any]] = []
        materialized: list[MemoryDocument] = []
        seen_paths: set[Path] = set()

        agent_documents = self._load_agent_namespace_documents(context, agent.name)
        selected_agent_documents = self._shortlist_agent_namespace_documents(
            documents=agent_documents,
            query=query,
        )
        materialized.extend(selected_agent_documents)
        seen_paths.update(document.path for document in selected_agent_documents)
        budget_decisions.append(
            {
                "layer": "agent_namespace",
                "budget": 1,
                "available": len(agent_documents),
                "selected": len(selected_agent_documents),
            }
        )
        if selected_agent_documents:
            applied_filters.append("layer:agent_namespace")
            selected_doc_ids.extend(str(document.path.relative_to(context.memory_root)) for document in selected_agent_documents)

        shortlist, shortlist_trace = self._shortlist_long_term_documents(context=context, query=query)
        selected_long_term: list[MemoryDocument] = []
        for document in shortlist:
            if document.path in seen_paths:
                continue
            selected_long_term.append(document)
            seen_paths.add(document.path)
        materialized.extend(selected_long_term)
        applied_filters.extend(shortlist_trace["applied_filters"])
        selected_doc_ids.extend(shortlist_trace["selected_doc_ids"])
        budget_decisions.append(shortlist_trace["budget"])

        session_summary = self._load_session_summary_document(context)
        selected_session: tuple[MemoryDocument, ...] = ()
        if session_summary is not None and session_summary.path not in seen_paths:
            selected_session = (session_summary,)
            materialized.append(session_summary)
            seen_paths.add(session_summary.path)
            applied_filters.append("layer:session_summary")
            selected_doc_ids.append(str(session_summary.path.relative_to(context.memory_root)))
        budget_decisions.append(
            {
                "layer": "session_summary",
                "budget": 1,
                "available": 1 if session_summary is not None else 0,
                "selected": len(selected_session),
            }
        )

        trace = {
            "applied_filters": tuple(dict.fromkeys(applied_filters)),
            "selected_doc_ids": tuple(selected_doc_ids),
            "budget_decisions": tuple(budget_decisions),
        }
        return tuple(materialized), trace

    def _shortlist_long_term_documents(
        self,
        *,
        context: ResolvedMemoryScope,
        query: str,
    ) -> tuple[tuple[MemoryDocument, ...], dict[str, Any]]:
        manifest = self.provider.load_long_term_manifest(context) or {}
        raw_entries = manifest.get("entries", ())
        if not isinstance(raw_entries, list):
            raw_entries = []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return (), {
                "applied_filters": ("query_tokens:none",),
                "selected_doc_ids": (),
                "budget": {"layer": "shared_long_term", "budget": self.retrieval_limit, "available": 0, "selected": 0},
            }

        scored: list[tuple[float, str, str]] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("contested") is True:
                continue
            path = entry.get("path")
            title = entry.get("title")
            summary = entry.get("summary")
            if not isinstance(path, str) or not isinstance(title, str):
                continue
            lexical_tokens = _tokenize(f"{title} {summary or ''} {' '.join(entry.get('tags', ())) }")
            overlap = len(query_tokens & lexical_tokens)
            if overlap <= 0:
                continue
            title_overlap = len(query_tokens & _tokenize(title))
            tag_overlap = len(query_tokens & set(str(tag).lower() for tag in entry.get("tags", ())))
            stale_penalty = 0.5 if _stale_entry(entry.get("stale_after")) else 0.0
            score = float(overlap) + float(title_overlap) + (0.5 * float(tag_overlap)) - stale_penalty
            scored.append((score, path, str(entry.get("doc_id") or path)))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[: self.retrieval_limit]
        documents = self.provider.materialize_documents(context, [path for _, path, _ in selected])
        return documents, {
            "applied_filters": ("manifest_header_prefilter", "lexical_shortlist", "hard_filter+boost+decay"),
            "selected_doc_ids": tuple(doc_id for _, _, doc_id in selected),
            "budget": {
                "layer": "shared_long_term",
                "budget": self.retrieval_limit,
                "available": len(scored),
                "selected": len(selected),
            },
        }

    def _shortlist_agent_namespace_documents(
        self,
        *,
        documents: Sequence[MemoryDocument],
        query: str,
    ) -> tuple[MemoryDocument, ...]:
        if not documents:
            return ()
        query_tokens = _tokenize(query)
        if not query_tokens:
            return tuple(documents[:1])

        scored: list[tuple[float, MemoryDocument]] = []
        for document in documents:
            score = _document_query_score(query_tokens, document)
            if score <= 0:
                continue
            scored.append((score, document))
        if not scored:
            return tuple(documents[:1])

        scored.sort(key=lambda item: (-item[0], item[1].path.as_posix()))
        return tuple(document for _, document in scored[:1])

    def _load_agent_namespace_documents(
        self,
        context: ResolvedMemoryScope,
        agent_name: str,
    ) -> tuple[MemoryDocument, ...]:
        namespace_dir = context.agent_namespace_documents_dir(agent_name)
        if not namespace_dir.exists():
            return ()
        documents: list[MemoryDocument] = []
        for path in sorted(namespace_dir.rglob("*.md")):
            relative_path = path.relative_to(context.memory_root).as_posix()
            materialized = self.provider.materialize_documents(context, (relative_path,))
            documents.extend(materialized)
        return tuple(documents)

    def _load_session_summary_document(self, context: ResolvedMemoryScope) -> MemoryDocument | None:
        summary_path = context.session_summary_path()
        if not summary_path.exists() or not summary_path.is_file():
            return None
        relative_path = summary_path.relative_to(context.memory_root).as_posix()
        documents = self.provider.materialize_documents(context, (relative_path,))
        return documents[0] if documents else None

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
class LongTermMemoryService:
    manager: LongTermMemory = field(default_factory=LongTermMemory)

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
        self.manager = LongTermMemory(
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
        fragments, trace = self.manager.collect_with_trace(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
        )
        if isinstance(runtime_context, dict):
            runtime_context["memory_retrieval"] = trace
        return fragments

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

    async def persist_entries(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]:
        return self.manager.persist_entries(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            entries=entries,
        )

    async def persist_agent_namespace_entries(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]:
        return self.manager.persist_agent_namespace_entries(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            entries=entries,
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


MemoryManager = LongTermMemory
MemoryManagerService = LongTermMemoryService


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


def _bind_entry_to_agent_namespace(entry: MemoryEntry, agent_name: str) -> MemoryEntry:
    metadata = dict(entry.metadata)
    metadata["namespace"] = f"agent:{agent_name}"
    metadata["agent_namespace"] = agent_name
    metadata.setdefault("memory_kind", "agent_note")
    metadata.setdefault("retention", "durable_reviewable")
    return MemoryEntry(
        title=entry.title,
        content=entry.content,
        metadata=metadata,
    )


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _document_query_score(query_tokens: set[str], document: MemoryDocument) -> float:
    title_tokens = _tokenize(document.title)
    tag_tokens = {
        token
        for tag in document.metadata.get("tags", ())
        for token in _tokenize(str(tag))
    }
    lexical_tokens = _tokenize(
        f"{document.title} {document.metadata.get('summary', '')} {' '.join(str(tag) for tag in document.metadata.get('tags', ())) } {document.content}"
    )
    overlap = len(query_tokens & lexical_tokens)
    if overlap <= 0:
        return 0.0
    title_overlap = len(query_tokens & title_tokens)
    tag_overlap = len(query_tokens & tag_tokens)
    stale_penalty = 0.5 if _stale_entry(document.metadata.get("stale_after")) else 0.0
    return float(overlap) + float(title_overlap) + (0.5 * float(tag_overlap)) - stale_penalty


def _stale_entry(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")) <= datetime.now().astimezone()
    except ValueError:
        return False
