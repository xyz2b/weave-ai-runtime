from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from ..contracts import MessageRole, RuntimeMessage
from ..definitions import AgentDefinition, MemoryScope
from ..tasking import TaskManager, TaskStatus
from .extraction import (
    MemoryExtractionDecision,
    extract_memory_decisions,
    synthesize_background_memory_decisions,
)
from .models import (
    MemoryDocument,
    MemoryEmbeddingShortlistProvider,
    MemoryEntry,
    MemoryRerankProvider,
    MemoryRetrievalCandidate,
    MemoryRetrievalPolicy,
    MemoryRetrievalRankedHit,
    MemoryTurnResult,
    MemoryWriteReceipt,
    ResolvedMemoryScope,
    normalize_memory_segment,
)
from .providers import FileMemoryProvider, MemoryProvider

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "do",
    "for",
    "from",
    "how",
    "here",
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
    "run",
    "should",
    "the",
    "there",
    "this",
    "to",
    "use",
    "we",
    "what",
}


@dataclass(slots=True)
class _ScoredManifestCandidate:
    doc_id: str
    path: str
    title: str
    summary: str
    metadata: dict[str, Any]
    lexical_score: float
    combined_score: float
    boosts: tuple[str, ...] = ()
    decays: tuple[str, ...] = ()
    embedding_score: float | None = None

    def as_retrieval_candidate(self) -> MemoryRetrievalCandidate:
        return MemoryRetrievalCandidate(
            doc_id=self.doc_id,
            path=self.path,
            title=self.title,
            summary=self.summary,
            tags=tuple(str(tag) for tag in self.metadata.get("tags", ())),
            metadata=dict(self.metadata),
            lexical_score=self.lexical_score,
            combined_score=self.combined_score,
        )


@dataclass(slots=True)
class _BackgroundExtractionPayload:
    session_id: str
    agent: AgentDefinition
    cwd: Path
    messages: tuple[RuntimeMessage, ...]
    task_manager: TaskManager | None = None


@dataclass(slots=True)
class LongTermMemory:
    provider: MemoryProvider = field(default_factory=FileMemoryProvider)
    project_root: Path | None = None
    user_root: Path = field(default_factory=lambda: Path.home() / ".claude")
    default_scope: MemoryScope = MemoryScope.PROJECT
    retrieval_limit: int = 3
    retrieval_policy: MemoryRetrievalPolicy = field(default_factory=MemoryRetrievalPolicy)
    embedding_shortlist_provider: MemoryEmbeddingShortlistProvider | None = None
    rerank_provider: MemoryRerankProvider | None = None
    _session_defaults: dict[str, ResolvedMemoryScope] = field(default_factory=dict, init=False)
    _background_pending: dict[str, _BackgroundExtractionPayload] = field(default_factory=dict, init=False)
    _background_tasks_by_key: dict[str, asyncio.Task[MemoryTurnResult]] = field(default_factory=dict, init=False)
    _background_tasks_by_id: dict[str, asyncio.Task[MemoryTurnResult]] = field(default_factory=dict, init=False)
    _background_task_ids: dict[str, str] = field(default_factory=dict, init=False)

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
        return self.record_turn_with_receipts(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
        ).persisted_documents

    def record_turn_with_receipts(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> MemoryTurnResult:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        decisions = extract_memory_decisions(messages, agent_name=agent.name)
        persisted_documents: list[MemoryDocument] = []
        receipts: list[MemoryWriteReceipt] = []

        for decision in decisions:
            receipt, written = self._apply_extraction_decision(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
            )
            receipts.append(receipt)
            persisted_documents.extend(written)

        return MemoryTurnResult(
            persisted_documents=tuple(persisted_documents),
            receipts=tuple(receipts),
        )

    def schedule_background_extraction(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
        task_manager: TaskManager | None = None,
    ) -> str | None:
        key = self._background_key(session_id=session_id, agent=agent, cwd=cwd)
        payload = _BackgroundExtractionPayload(
            session_id=session_id,
            agent=agent,
            cwd=Path(cwd).resolve(),
            messages=tuple(messages),
            task_manager=task_manager,
        )
        existing = self._background_pending.get(key)
        if existing is not None:
            payload = _merge_background_payload(existing, payload)
        self._background_pending[key] = payload

        task_id = self._background_task_ids.get(key)
        if task_id is None:
            task_id = uuid4().hex
            self._background_task_ids[key] = task_id
            if task_manager is not None:
                task_manager.create(
                    task_id,
                    title=f"memory-extraction:{normalize_memory_segment(agent.name, default='agent')}",
                    metadata={
                        "session_id": session_id,
                        "agent": agent.name,
                        "kind": "background_memory_extraction",
                    },
                )
        elif task_manager is not None:
            task = task_manager.get(task_id)
            if task is not None:
                task_manager.update(
                    task_id,
                    metadata={
                        "queued_merge": True,
                        "queued_message_count": len(payload.messages),
                    },
                )

        if key not in self._background_tasks_by_key:
            background_task = asyncio.create_task(self._run_background_extraction_queue(key))
            self._background_tasks_by_key[key] = background_task
            self._background_tasks_by_id[task_id] = background_task
        return task_id

    async def wait_for_background_extraction(self, task_id: str) -> MemoryTurnResult:
        task = self._background_tasks_by_id.get(task_id)
        if task is None:
            return MemoryTurnResult()
        try:
            return await task
        finally:
            self._background_tasks_by_id.pop(task_id, None)

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
        boosts: list[str] = []
        decays: list[str] = []
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
        boosts.extend(shortlist_trace.get("boosts", ()))
        decays.extend(shortlist_trace.get("decays", ()))
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

        session_open_threads = self._load_session_open_threads_document(context)
        selected_open_threads: tuple[MemoryDocument, ...] = ()
        if session_open_threads is not None and session_open_threads.path not in seen_paths:
            selected_open_threads = (session_open_threads,)
            materialized.append(session_open_threads)
            seen_paths.add(session_open_threads.path)
            applied_filters.append("layer:session_open_threads")
            selected_doc_ids.append(str(session_open_threads.path.relative_to(context.memory_root)))
        budget_decisions.append(
            {
                "layer": "session_open_threads",
                "budget": 1,
                "available": 1 if session_open_threads is not None else 0,
                "selected": len(selected_open_threads),
            }
        )

        trace = {
            "applied_filters": tuple(dict.fromkeys(applied_filters)),
            "boosts": tuple(dict.fromkeys(boosts)),
            "decays": tuple(dict.fromkeys(decays)),
            "selected_doc_ids": tuple(selected_doc_ids),
            "budget_decisions": tuple(budget_decisions),
        }
        if "candidate_doc_ids" in shortlist_trace:
            trace["candidate_doc_ids"] = shortlist_trace["candidate_doc_ids"]
        if "lexical_doc_ids" in shortlist_trace:
            trace["lexical_doc_ids"] = shortlist_trace["lexical_doc_ids"]
        if "embedding_doc_ids" in shortlist_trace:
            trace["embedding_doc_ids"] = shortlist_trace["embedding_doc_ids"]
        if "divergence" in shortlist_trace:
            trace["divergence"] = shortlist_trace["divergence"]
        if "rerank" in shortlist_trace:
            trace["rerank"] = shortlist_trace["rerank"]
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
                "boosts": (),
                "decays": (),
                "selected_doc_ids": (),
                "candidate_doc_ids": (),
                "lexical_doc_ids": (),
                "embedding_doc_ids": (),
                "divergence": {
                    "detected": False,
                    "lexical_only": (),
                    "embedding_only": (),
                    "order_changed": False,
                },
                "rerank": {
                    "triggered": False,
                    "status": "skipped",
                    "reasons": (),
                    "candidate_count": 0,
                },
                "budget": {"layer": "shared_long_term", "budget": self.retrieval_limit, "available": 0, "selected": 0},
            }

        policy = self.retrieval_policy
        pool_limit = _candidate_pool_limit(self.retrieval_limit, policy)
        filter_reasons: list[str] = []
        boost_names: list[str] = []
        decay_names: list[str] = []
        lexical_candidates: list[_ScoredManifestCandidate] = []
        candidate_index: dict[str, _ScoredManifestCandidate] = {}

        for entry in raw_entries:
            if not isinstance(entry, dict):
                filter_reasons.append("invalid_manifest_entry")
                continue
            candidate, excluded_reason = self._score_manifest_entry(
                context=context,
                entry=entry,
                query_tokens=query_tokens,
            )
            if excluded_reason is not None:
                filter_reasons.append(excluded_reason)
                continue
            if candidate is None:
                continue
            candidate_index[candidate.doc_id] = candidate
            boost_names.extend(candidate.boosts)
            decay_names.extend(candidate.decays)
            if candidate.lexical_score >= policy.minimum_lexical_score:
                lexical_candidates.append(candidate)

        lexical_candidates.sort(key=lambda item: (-item.combined_score, item.path, item.doc_id))
        lexical_pool = tuple(lexical_candidates[:pool_limit])
        lexical_doc_ids = tuple(candidate.doc_id for candidate in lexical_pool)

        embedding_doc_ids: tuple[str, ...] = ()
        if self.embedding_shortlist_provider is not None and candidate_index:
            embedding_hits = tuple(
                self.embedding_shortlist_provider.shortlist(
                    query=query,
                    candidates=tuple(
                        candidate.as_retrieval_candidate()
                        for candidate in sorted(
                            candidate_index.values(),
                            key=lambda item: (-item.combined_score, item.path, item.doc_id),
                        )
                    ),
                    limit=policy.embedding_shortlist_limit or pool_limit,
                )
            )
            valid_embedding_hits = tuple(
                hit for hit in embedding_hits if isinstance(hit, MemoryRetrievalRankedHit) and hit.doc_id in candidate_index
            )
            if valid_embedding_hits:
                for hit in valid_embedding_hits:
                    candidate = candidate_index[hit.doc_id]
                    candidate.embedding_score = float(hit.score)
                    candidate.combined_score = candidate.lexical_score + (
                        policy.embedding_score_weight * float(hit.score)
                    )
                embedding_doc_ids = tuple(hit.doc_id for hit in valid_embedding_hits)
                filter_reasons.append("embedding_shortlist")

        divergence = _detect_shortlist_divergence(lexical_doc_ids, embedding_doc_ids)
        candidate_pool = self._merge_candidate_pool(
            lexical_doc_ids=lexical_doc_ids,
            embedding_doc_ids=embedding_doc_ids,
            candidate_index=candidate_index,
            pool_limit=pool_limit,
        )
        combined_candidates = sorted(
            candidate_pool,
            key=lambda item: (-item.combined_score, item.path, item.doc_id),
        )
        candidate_doc_ids = tuple(candidate.doc_id for candidate in combined_candidates)

        rerank_trace = self._rerank_candidates(
            query=query,
            query_tokens=query_tokens,
            candidates=combined_candidates,
            lexical_doc_ids=lexical_doc_ids,
            divergence=divergence,
        )
        selected_candidates = tuple(rerank_trace.get("selected_candidates", combined_candidates[: self.retrieval_limit]))
        documents = self.provider.materialize_documents(context, [candidate.path for candidate in selected_candidates])

        applied_filters = ["manifest_header_prefilter", "lexical_shortlist", "hard_filter+boost+decay"]
        for reason in dict.fromkeys(filter_reasons):
            if reason not in applied_filters:
                applied_filters.append(reason)
        if rerank_trace["status"] == "success":
            applied_filters.append("llm_rerank")

        return documents, {
            "applied_filters": tuple(applied_filters),
            "boosts": tuple(dict.fromkeys(boost_names)),
            "decays": tuple(dict.fromkeys(decay_names)),
            "selected_doc_ids": tuple(candidate.doc_id for candidate in selected_candidates),
            "candidate_doc_ids": candidate_doc_ids,
            "lexical_doc_ids": lexical_doc_ids,
            "embedding_doc_ids": embedding_doc_ids,
            "divergence": divergence,
            "rerank": {
                key: value
                for key, value in rerank_trace.items()
                if key != "selected_candidates"
            },
            "budget": {
                "layer": "shared_long_term",
                "budget": self.retrieval_limit,
                "available": len(combined_candidates),
                "selected": len(selected_candidates),
            },
        }

    def _score_manifest_entry(
        self,
        *,
        context: ResolvedMemoryScope,
        entry: Mapping[str, Any],
        query_tokens: set[str],
    ) -> tuple[_ScoredManifestCandidate | None, str | None]:
        path = entry.get("path")
        title = entry.get("title")
        summary = entry.get("summary")
        if not isinstance(path, str) or not path.strip() or not isinstance(title, str) or not title.strip():
            return None, "invalid_manifest_entry"

        scope = entry.get("scope")
        if isinstance(scope, str) and scope.strip() and scope.strip() != context.scope.value:
            return None, "scope_mismatch"

        retention = str(entry.get("retention") or "").strip()
        if retention == "drop":
            return None, "retention_drop"

        policy = self.retrieval_policy
        confidence = _coerce_confidence(entry.get("confidence"))
        if confidence is not None and policy.minimum_confidence is not None and confidence < policy.minimum_confidence:
            return None, "confidence_below_threshold"

        boosts: list[str] = []
        decays: list[str] = []
        lexical_tokens = _tokenize(f"{title} {summary or ''} {' '.join(str(tag) for tag in entry.get('tags', ())) }")
        overlap = len(query_tokens & lexical_tokens)
        title_overlap = len(query_tokens & _tokenize(title))
        tag_overlap = len(query_tokens & set(str(tag).lower() for tag in entry.get("tags", ())))

        lexical_score = float(overlap)
        if title_overlap > 0:
            lexical_score += float(title_overlap)
            boosts.append("title_overlap")
        if tag_overlap > 0:
            lexical_score += 0.5 * float(tag_overlap)
            boosts.append("explicit_tag")
        if _recent_confirmation(
            entry.get("last_confirmed_at"),
            window_days=policy.recent_confirmation_window_days,
        ):
            lexical_score += policy.recent_confirmation_boost
            boosts.append("recent_confirmation")

        combined_score = lexical_score
        contested = entry.get("contested") is True
        if contested:
            if policy.contested_policy == "block":
                return None, "contested_policy:block"
            if policy.contested_policy == "decay":
                combined_score -= policy.contested_decay_penalty
                decays.append("contested_entry")

        if _stale_entry(entry.get("stale_after")):
            combined_score -= policy.stale_decay_penalty
            decays.append("stale_beyond_threshold")

        if confidence is not None and confidence < policy.low_confidence_decay_start:
            decay = (policy.low_confidence_decay_start - confidence) * policy.low_confidence_decay_penalty
            combined_score -= decay
            decays.append("low_confidence_memory")

        return _ScoredManifestCandidate(
            doc_id=str(entry.get("doc_id") or path),
            path=path.strip(),
            title=title.strip(),
            summary=str(summary or "").strip(),
            metadata=dict(entry),
            lexical_score=lexical_score,
            combined_score=combined_score,
            boosts=tuple(boosts),
            decays=tuple(decays),
        ), None

    def _merge_candidate_pool(
        self,
        *,
        lexical_doc_ids: Sequence[str],
        embedding_doc_ids: Sequence[str],
        candidate_index: Mapping[str, _ScoredManifestCandidate],
        pool_limit: int,
    ) -> tuple[_ScoredManifestCandidate, ...]:
        ordered_ids: list[str] = []
        for doc_id in (*lexical_doc_ids, *embedding_doc_ids):
            if doc_id in candidate_index and doc_id not in ordered_ids:
                ordered_ids.append(doc_id)
            if len(ordered_ids) >= pool_limit:
                break
        return tuple(candidate_index[doc_id] for doc_id in ordered_ids)

    def _rerank_candidates(
        self,
        *,
        query: str,
        query_tokens: set[str],
        candidates: Sequence[_ScoredManifestCandidate],
        lexical_doc_ids: Sequence[str],
        divergence: Mapping[str, Any],
    ) -> dict[str, Any]:
        reasons = _rerank_trigger_reasons(
            query=query,
            query_tokens=query_tokens,
            candidates=candidates,
            lexical_doc_ids=lexical_doc_ids,
            divergence=divergence,
            policy=self.retrieval_policy,
        )
        fallback = tuple(candidates[: self.retrieval_limit])
        if not reasons:
            return {
                "triggered": False,
                "status": "skipped",
                "reasons": (),
                "candidate_count": len(candidates),
                "selected_candidates": fallback,
            }
        if self.rerank_provider is None:
            return {
                "triggered": False,
                "status": "provider_unavailable",
                "reasons": reasons,
                "candidate_count": len(candidates),
                "selected_candidates": fallback,
            }
        if not self.retrieval_policy.rerank_budget_available:
            return {
                "triggered": False,
                "status": "budget_denied",
                "reasons": reasons,
                "candidate_count": len(candidates),
                "selected_candidates": fallback,
            }

        rerank_limit = self.retrieval_policy.rerank_max_candidates or len(candidates)
        rerank_candidates = tuple(candidates[:rerank_limit])
        reranked_hits = tuple(
            hit
            for hit in self.rerank_provider.rerank(
                query=query,
                candidates=tuple(candidate.as_retrieval_candidate() for candidate in rerank_candidates),
                limit=self.retrieval_limit,
            )
            if isinstance(hit, MemoryRetrievalRankedHit)
        )
        reranked_by_id = {candidate.doc_id: candidate for candidate in rerank_candidates}
        ordered: list[_ScoredManifestCandidate] = []
        for hit in reranked_hits:
            candidate = reranked_by_id.get(hit.doc_id)
            if candidate is None or candidate in ordered:
                continue
            ordered.append(candidate)
        for candidate in candidates:
            if candidate not in ordered:
                ordered.append(candidate)
        return {
            "triggered": bool(reranked_hits),
            "status": "success" if reranked_hits else "skipped",
            "reasons": reasons,
            "candidate_count": len(candidates),
            "selected_candidates": tuple(ordered[: self.retrieval_limit]) if ordered else fallback,
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
            return ()

        scored: list[tuple[float, MemoryDocument]] = []
        for document in documents:
            score = _document_query_score(query_tokens, document)
            if score <= 0:
                continue
            scored.append((score, document))
        if not scored:
            return ()

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

    def _load_session_open_threads_document(self, context: ResolvedMemoryScope) -> MemoryDocument | None:
        open_threads_path = context.session_open_threads_path()
        if not open_threads_path.exists() or not open_threads_path.is_file():
            return None
        relative_path = open_threads_path.relative_to(context.memory_root).as_posix()
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

    def _background_key(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> str:
        normalized_agent = normalize_memory_segment(agent.name, default="agent")
        return f"{session_id}:{normalized_agent}:{Path(cwd).resolve()}"

    async def _run_background_extraction_queue(self, key: str) -> MemoryTurnResult:
        task_id = self._background_task_ids[key]
        aggregate = MemoryTurnResult()
        task_manager = self._background_pending[key].task_manager
        if task_manager is not None:
            task_manager.update(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={"status": "running"},
            )

        try:
            while key in self._background_pending:
                payload = self._background_pending.pop(key)
                task_manager = payload.task_manager or task_manager
                await asyncio.sleep(0)
                result = self._execute_background_extraction(payload)
                aggregate = _merge_turn_results(aggregate, result)
                if task_manager is not None and key in self._background_pending:
                    task_manager.update(
                        task_id,
                        status=TaskStatus.RUNNING,
                        metadata={
                            "queued_merge": True,
                            "queued_message_count": len(self._background_pending[key].messages),
                        },
                    )

            if task_manager is not None:
                task_manager.update(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    result={
                        "persisted_count": len(aggregate.persisted_documents),
                        "receipt_count": len(aggregate.receipts),
                    },
                    metadata={"status": "completed"},
                )
            return aggregate
        except Exception as exc:  # pragma: no cover - defensive boundary
            if task_manager is not None:
                task_manager.update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(exc),
                    metadata={"status": "failed"},
                )
            raise
        finally:
            self._background_tasks_by_key.pop(key, None)
            self._background_task_ids.pop(key, None)

    def _execute_background_extraction(self, payload: _BackgroundExtractionPayload) -> MemoryTurnResult:
        decisions = synthesize_background_memory_decisions(payload.messages, agent_name=payload.agent.name)
        if not decisions:
            return MemoryTurnResult()

        context = self.resolve_context(
            session_id=payload.session_id,
            agent=payload.agent,
            cwd=payload.cwd,
        )
        persisted_documents: list[MemoryDocument] = []
        receipts: list[MemoryWriteReceipt] = []
        for decision in decisions:
            receipt, written = self._apply_background_extraction_decision(
                context=context,
                session_id=payload.session_id,
                agent=payload.agent,
                cwd=payload.cwd,
                decision=decision,
            )
            receipts.append(receipt)
            persisted_documents.extend(written)
        return MemoryTurnResult(
            persisted_documents=tuple(persisted_documents),
            receipts=tuple(receipts),
        )

    def _apply_background_extraction_decision(
        self,
        *,
        context: ResolvedMemoryScope,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        decision: MemoryExtractionDecision,
    ) -> tuple[MemoryWriteReceipt, tuple[MemoryDocument, ...]]:
        conflict_key = decision.metadata.get("conflict_key")
        if isinstance(conflict_key, str) and conflict_key.strip():
            existing = self._find_conflict_key_document(
                context=context,
                namespace=decision.namespace,
                conflict_key=conflict_key.strip(),
            )
            if existing is not None and _normalize_document_content(existing.content) != _normalize_document_content(decision.content):
                return (
                    MemoryWriteReceipt(
                        fact_type=decision.fact_type,
                        action="skipped_conflict",
                        scope=context.scope.value,
                        target_layer=decision.target_layer,
                        namespace=decision.namespace,
                        retention=decision.retention,
                        merge_policy=decision.merge_policy,
                        title=decision.title,
                        path=existing.path,
                        reason="merge_safe_conflict_key",
                        source_message_ids=decision.source_message_ids,
                        source_roles=decision.source_roles,
                    ),
                    (),
                )
        return self._apply_extraction_decision(
            context=context,
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            decision=decision,
        )

    def _find_conflict_key_document(
        self,
        *,
        context: ResolvedMemoryScope,
        namespace: str,
        conflict_key: str,
    ) -> MemoryDocument | None:
        if namespace.startswith("agent:"):
            agent_name = namespace.partition(":")[2].strip()
            documents = self._load_agent_namespace_documents(context, agent_name)
        else:
            documents = self.provider.list_documents(context)
        for document in documents:
            candidate_conflict_key = document.metadata.get("conflict_key")
            if isinstance(candidate_conflict_key, str) and candidate_conflict_key.strip() == conflict_key:
                return document
        return None

    def _apply_extraction_decision(
        self,
        *,
        context: ResolvedMemoryScope,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        decision: MemoryExtractionDecision,
    ) -> tuple[MemoryWriteReceipt, tuple[MemoryDocument, ...]]:
        if decision.target_layer in {"shared_long_term", "agent_namespace"}:
            written = self.persist_entries(
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                entries=(decision.to_entry(),),
            )
            if written:
                document = written[0]
                return (
                    MemoryWriteReceipt(
                        fact_type=decision.fact_type,
                        action="persisted",
                        scope=context.scope.value,
                        target_layer=decision.target_layer,
                        namespace=decision.namespace,
                        retention=decision.retention,
                        merge_policy=decision.merge_policy,
                        title=document.title,
                        path=document.path,
                        source_message_ids=decision.source_message_ids,
                        source_roles=decision.source_roles,
                    ),
                    written,
                )
            return (
                MemoryWriteReceipt(
                    fact_type=decision.fact_type,
                    action="skipped_duplicate",
                    scope=context.scope.value,
                    target_layer=decision.target_layer,
                    namespace=decision.namespace,
                    retention=decision.retention,
                    merge_policy=decision.merge_policy,
                    title=decision.title,
                    reason="duplicate_content",
                    source_message_ids=decision.source_message_ids,
                    source_roles=decision.source_roles,
                ),
                (),
            )

        if decision.target_layer == "session_summary":
            return (
                MemoryWriteReceipt(
                    fact_type=decision.fact_type,
                    action="session_routed",
                    scope=context.scope.value,
                    target_layer=decision.target_layer,
                    namespace=decision.namespace,
                    retention=decision.retention,
                    merge_policy=decision.merge_policy,
                    title=decision.title,
                    path=context.session_summary_path(),
                    reason=decision.reason or "session_memory_managed",
                    source_message_ids=decision.source_message_ids,
                    source_roles=decision.source_roles,
                ),
                (),
            )

        if decision.target_layer == "session_open_threads":
            return (
                MemoryWriteReceipt(
                    fact_type=decision.fact_type,
                    action="session_routed",
                    scope=context.scope.value,
                    target_layer=decision.target_layer,
                    namespace=decision.namespace,
                    retention=decision.retention,
                    merge_policy=decision.merge_policy,
                    title=decision.title,
                    path=context.session_open_threads_path(),
                    reason=decision.reason or "session_memory_managed",
                    source_message_ids=decision.source_message_ids,
                    source_roles=decision.source_roles,
                ),
                (),
            )

        return (
            MemoryWriteReceipt(
                fact_type=decision.fact_type,
                action="dropped",
                scope=context.scope.value,
                target_layer=decision.target_layer,
                namespace=decision.namespace,
                retention=decision.retention,
                merge_policy=decision.merge_policy,
                title=decision.title,
                reason=decision.reason or "do_not_persist",
                source_message_ids=decision.source_message_ids,
                source_roles=decision.source_roles,
            ),
            (),
        )


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
        retrieval_policy: MemoryRetrievalPolicy | None = None,
        embedding_shortlist_provider: MemoryEmbeddingShortlistProvider | None = None,
        rerank_provider: MemoryRerankProvider | None = None,
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
            retrieval_policy=retrieval_policy or MemoryRetrievalPolicy(),
            embedding_shortlist_provider=embedding_shortlist_provider,
            rerank_provider=rerank_provider,
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

    async def record_turn_with_receipts(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> MemoryTurnResult:
        return self.manager.record_turn_with_receipts(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
        )

    async def schedule_background_extraction(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
        task_manager: TaskManager | None = None,
    ) -> str | None:
        return self.manager.schedule_background_extraction(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
            task_manager=task_manager,
        )

    async def wait_for_background_extraction(self, task_id: str) -> MemoryTurnResult:
        return await self.manager.wait_for_background_extraction(task_id)

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


def _coerce_confidence(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _merge_background_payload(
    existing: _BackgroundExtractionPayload,
    incoming: _BackgroundExtractionPayload,
) -> _BackgroundExtractionPayload:
    merged_messages: list[RuntimeMessage] = []
    seen_message_ids: set[str] = set()
    for message in (*existing.messages, *incoming.messages):
        if message.message_id in seen_message_ids:
            continue
        seen_message_ids.add(message.message_id)
        merged_messages.append(message)
    return _BackgroundExtractionPayload(
        session_id=incoming.session_id,
        agent=incoming.agent,
        cwd=incoming.cwd,
        messages=tuple(merged_messages),
        task_manager=incoming.task_manager or existing.task_manager,
    )


def _merge_turn_results(existing: MemoryTurnResult, new_result: MemoryTurnResult) -> MemoryTurnResult:
    persisted_by_path = {document.path: document for document in existing.persisted_documents}
    persisted_by_path.update({document.path: document for document in new_result.persisted_documents})
    receipts = existing.receipts + new_result.receipts
    return MemoryTurnResult(
        persisted_documents=tuple(persisted_by_path.values()),
        receipts=receipts,
    )


def _normalize_document_content(content: str) -> str:
    return " ".join(content.strip().split()).lower()


def _candidate_pool_limit(retrieval_limit: int, policy: MemoryRetrievalPolicy) -> int:
    multiplier = max(1, policy.candidate_pool_multiplier)
    return max(
        retrieval_limit,
        retrieval_limit * multiplier,
        policy.rerank_candidate_threshold + 1,
        policy.embedding_shortlist_limit or 0,
        policy.rerank_max_candidates or 0,
    )


def _detect_shortlist_divergence(
    lexical_doc_ids: Sequence[str],
    embedding_doc_ids: Sequence[str],
) -> dict[str, Any]:
    lexical = tuple(lexical_doc_ids)
    embedding = tuple(embedding_doc_ids)
    lexical_set = set(lexical)
    embedding_set = set(embedding)
    lexical_only = tuple(doc_id for doc_id in lexical if doc_id not in embedding_set)
    embedding_only = tuple(doc_id for doc_id in embedding if doc_id not in lexical_set)
    overlap = tuple(doc_id for doc_id in lexical if doc_id in embedding_set)
    order_changed = tuple(doc_id for doc_id in lexical if doc_id in embedding_set) != tuple(
        doc_id for doc_id in embedding if doc_id in lexical_set
    )
    return {
        "detected": bool(embedding and (lexical_only or embedding_only or order_changed)),
        "lexical_only": lexical_only,
        "embedding_only": embedding_only,
        "overlap": overlap,
        "order_changed": order_changed,
    }


def _rerank_trigger_reasons(
    *,
    query: str,
    query_tokens: set[str],
    candidates: Sequence[_ScoredManifestCandidate],
    lexical_doc_ids: Sequence[str],
    divergence: Mapping[str, Any],
    policy: MemoryRetrievalPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(candidates) > policy.rerank_candidate_threshold:
        reasons.append("candidate_count_exceeds_threshold")
    if len(candidates) >= 2 and abs(candidates[0].combined_score - candidates[1].combined_score) <= policy.rerank_score_margin_threshold:
        reasons.append("top_scores_too_close")
    if divergence.get("detected") is True:
        reasons.append("lexical_embedding_divergence")
    if len(candidates) >= 2 and _is_vague_query(query, query_tokens, policy):
        reasons.append("query_semantically_vague")
    if not lexical_doc_ids and candidates:
        reasons.append("lexical_confidence_insufficient")
    return tuple(dict.fromkeys(reasons))


def _is_vague_query(query: str, query_tokens: set[str], policy: MemoryRetrievalPolicy) -> bool:
    vague_markers = {"again", "same", "similar", "that", "thing", "issue", "problem", "question"}
    if len(query_tokens) <= max(1, policy.rerank_vague_query_token_threshold):
        return True
    return any(marker in query.lower() for marker in vague_markers)


def _recent_confirmation(value: object, *, window_days: int) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        confirmed_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return confirmed_at >= datetime.now(confirmed_at.tzinfo) - timedelta(days=max(1, window_days))


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
