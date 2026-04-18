from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from ..contracts import MessageRole, RuntimeMessage
from ..definitions import AgentDefinition, MemoryScope
from ..runtime_services import SidecarContributionResult
from ..tasking import TaskManager, TaskStatus
from .config import (
    MemoryRuntimeConfig,
    ResolvedMemoryConfig,
    describe_memory_config,
    resolve_memory_config,
)
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
_DEFAULT_CAPTURE_ROUTING_TARGETS = {
    "agent_workflow": "agent_namespace",
    "preference": "long_term.preferences",
    "project_convention": "long_term.conventions",
    "session_continuity": "session",
    "session_thread": "session",
    "topic_memory": "long_term.topics",
    "workflow_command": "long_term.conventions",
}
_MISSING = object()


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
class _BackgroundConsolidationPayload:
    session_id: str
    agent: AgentDefinition
    cwd: Path
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
    memory_config: Mapping[str, Any] | MemoryRuntimeConfig | None = None
    _session_defaults: dict[str, ResolvedMemoryScope] = field(default_factory=dict, init=False)
    _background_pending: dict[str, _BackgroundExtractionPayload] = field(default_factory=dict, init=False)
    _background_tasks_by_key: dict[str, asyncio.Task[MemoryTurnResult]] = field(default_factory=dict, init=False)
    _background_tasks_by_id: dict[str, asyncio.Task[MemoryTurnResult]] = field(default_factory=dict, init=False)
    _background_task_ids: dict[str, str] = field(default_factory=dict, init=False)
    _consolidation_pending: dict[str, _BackgroundConsolidationPayload] = field(default_factory=dict, init=False)
    _consolidation_tasks_by_key: dict[str, concurrent.futures.Future[MemoryTurnResult]] = field(
        default_factory=dict,
        init=False,
    )
    _consolidation_tasks_by_id: dict[str, concurrent.futures.Future[MemoryTurnResult]] = field(
        default_factory=dict,
        init=False,
    )
    _consolidation_task_ids: dict[str, str] = field(default_factory=dict, init=False)
    _consolidation_state_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _consolidation_executor: concurrent.futures.ThreadPoolExecutor = field(
        default_factory=lambda: concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory-cons"),
        init=False,
        repr=False,
    )

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
            consolidation_lock_path=consolidations_dir / "active.lock.json",
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

    def resolve_config(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> ResolvedMemoryConfig:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        return self._resolve_memory_config(context)

    def session_summary_thresholds(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> dict[str, int]:
        resolved = self.resolve_config(session_id=session_id, agent=agent, cwd=cwd)
        refresh = resolved.config.session_memory.refresh
        return {
            "token_growth_threshold": refresh.token_growth_threshold,
            "tool_call_threshold": refresh.tool_call_threshold,
            "turn_threshold": refresh.turn_threshold,
        }

    def _resolve_memory_config(self, context: ResolvedMemoryScope) -> ResolvedMemoryConfig:
        return resolve_memory_config(memory_root=context.memory_root, override=self.memory_config)

    def collect(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        messages: Sequence[RuntimeMessage],
    ) -> tuple[str, ...]:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        resolved_config = self._resolve_memory_config(context)
        entrypoint = self.provider.load_entrypoint(context)
        query = _latest_user_text(messages)
        relevant, _ = self._collect_layered_retrieval(
            context=context,
            agent=agent,
            query=query,
            resolved_config=resolved_config,
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
        resolved_config = self._resolve_memory_config(context)
        decisions = tuple(
            adjusted
            for decision in extract_memory_decisions(messages, agent_name=agent.name)
            if (adjusted := self._apply_configured_extraction_policy(
                context=context,
                agent=agent,
                decision=decision,
                resolved_config=resolved_config,
            )) is not None
        )
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
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        resolved_config = self._resolve_memory_config(context)
        if resolved_config.config.extraction.background_synthesis is False:
            return None
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

    def schedule_background_consolidation(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        task_manager: TaskManager | None = None,
    ) -> str | None:
        context = self.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
        resolved_config = self._resolve_memory_config(context)
        self._refresh_consolidation_manifest(context)
        if resolved_config.config.consolidation.enable_background is False:
            return None
        key = self._consolidation_key(context)
        payload = _BackgroundConsolidationPayload(
            session_id=session_id,
            agent=agent,
            cwd=Path(cwd).resolve(),
            task_manager=task_manager,
        )
        with self._consolidation_state_lock:
            existing = self._consolidation_tasks_by_key.get(key)
            if existing is not None and existing.done():
                self._consolidation_tasks_by_key.pop(key, None)
                finished_task_id = self._consolidation_task_ids.pop(key, None)
                if finished_task_id is not None:
                    self._consolidation_tasks_by_id.pop(finished_task_id, None)
                existing = None

            self._consolidation_pending[key] = payload
            task_id = self._consolidation_task_ids.get(key)
            if task_id is None:
                task_id = uuid4().hex
                self._consolidation_task_ids[key] = task_id
                if task_manager is not None:
                    task_manager.create(
                        task_id,
                        title=f"memory-consolidation:{context.scope.value}",
                        metadata={
                            "session_id": session_id,
                            "agent": agent.name,
                            "kind": "background_memory_consolidation",
                        },
                    )
            elif task_manager is not None:
                task = task_manager.get(task_id)
                if task is not None:
                    task_manager.update(
                        task_id,
                        metadata={"queued_merge": True, "trigger_session_id": session_id},
                    )

            if existing is None:
                background_task = self._consolidation_executor.submit(
                    self._run_background_consolidation_queue,
                    key,
                    task_id,
                )
                self._consolidation_tasks_by_key[key] = background_task
                self._consolidation_tasks_by_id[task_id] = background_task
        return task_id

    async def wait_for_background_consolidation(self, task_id: str) -> MemoryTurnResult:
        with self._consolidation_state_lock:
            task = self._consolidation_tasks_by_id.get(task_id)
        if task is None:
            return MemoryTurnResult()
        try:
            return await asyncio.wrap_future(task)
        finally:
            with self._consolidation_state_lock:
                current = self._consolidation_tasks_by_id.get(task_id)
                if current is task and task.done():
                    self._consolidation_tasks_by_id.pop(task_id, None)

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
        resolved_config = self._resolve_memory_config(context)
        entrypoint = self.provider.load_entrypoint(context)
        relevant, trace = self._collect_layered_retrieval(
            context=context,
            agent=agent,
            query=_latest_user_text(messages),
            resolved_config=resolved_config,
        )
        fragments: list[str] = []
        if entrypoint is not None and entrypoint.content.strip():
            fragments.append(entrypoint.render())
        fragments.extend(document.render() for document in relevant)
        deduped = tuple(dict.fromkeys(fragment for fragment in fragments if fragment.strip()))
        trace["turn_id"] = turn_id
        trace["config"] = describe_memory_config(resolved_config)
        return deduped, trace

    def _collect_layered_retrieval(
        self,
        *,
        context: ResolvedMemoryScope,
        agent: AgentDefinition,
        query: str,
        resolved_config: ResolvedMemoryConfig,
    ) -> tuple[tuple[MemoryDocument, ...], dict[str, Any]]:
        retrieval_limit = self._retrieval_limit_for_config(resolved_config)
        applied_filters: list[str] = []
        boosts: list[str] = []
        decays: list[str] = []
        selected_doc_ids: list[str] = []
        budget_decisions: list[dict[str, Any]] = []
        materialized: list[MemoryDocument] = []
        seen_paths: set[Path] = set()

        agent_documents = self._load_agent_namespace_documents(context, agent.name)
        selected_agent_documents, agent_trace = self._shortlist_agent_namespace_documents(
            context=context,
            documents=agent_documents,
            query=query,
            resolved_config=resolved_config,
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
            boosts.append("active_agent_namespace")
        applied_filters.extend(agent_trace["applied_filters"])
        decays.extend(agent_trace["decays"])
        selected_doc_ids.extend(agent_trace["selected_doc_ids"])

        shortlist, shortlist_trace = self._shortlist_long_term_documents(
            context=context,
            query=query,
            resolved_config=resolved_config,
        )
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
        resolved_config: ResolvedMemoryConfig,
    ) -> tuple[tuple[MemoryDocument, ...], dict[str, Any]]:
        manifest = self.provider.load_long_term_manifest(context) or {}
        raw_entries = manifest.get("entries", ())
        if not isinstance(raw_entries, list):
            raw_entries = []
        query_tokens = _tokenize(query)
        retrieval_limit = self._retrieval_limit_for_config(resolved_config)
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
                "budget": {"layer": "shared_long_term", "budget": retrieval_limit, "available": 0, "selected": 0},
            }

        policy = self._retrieval_policy_for_config(resolved_config)
        pool_limit = _candidate_pool_limit(retrieval_limit, policy)
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
                resolved_config=resolved_config,
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
        embedding_provider = self._embedding_provider_for_config(resolved_config)
        if embedding_provider is not None and candidate_index:
            embedding_hits = tuple(
                embedding_provider.shortlist(
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
            embedding_scores: dict[str, float] = {}
            ordered_embedding_doc_ids: list[str] = []
            for hit in embedding_hits:
                if not isinstance(hit, MemoryRetrievalRankedHit) or hit.doc_id not in candidate_index:
                    continue
                if hit.doc_id not in embedding_scores:
                    ordered_embedding_doc_ids.append(hit.doc_id)
                    embedding_scores[hit.doc_id] = float(hit.score)
                    continue
                embedding_scores[hit.doc_id] = max(embedding_scores[hit.doc_id], float(hit.score))
            if ordered_embedding_doc_ids:
                for doc_id in ordered_embedding_doc_ids:
                    candidate = candidate_index[doc_id]
                    candidate.embedding_score = embedding_scores[doc_id]
                    candidate.combined_score += policy.embedding_score_weight * embedding_scores[doc_id]
                embedding_doc_ids = tuple(ordered_embedding_doc_ids)
                filter_reasons.append("embedding_shortlist")

        divergence = _detect_shortlist_divergence(lexical_doc_ids, embedding_doc_ids)
        candidate_pool = self._merge_candidate_pool(
            lexical_doc_ids=lexical_doc_ids,
            embedding_doc_ids=embedding_doc_ids,
            candidate_index=candidate_index,
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
            resolved_config=resolved_config,
        )
        selected_candidates = tuple(rerank_trace.get("selected_candidates", combined_candidates[:retrieval_limit]))
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
                "budget": retrieval_limit,
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
        resolved_config: ResolvedMemoryConfig,
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

        policy = self._retrieval_policy_for_config(resolved_config)
        confidence = _coerce_confidence(entry.get("confidence"))
        if confidence is not None and policy.minimum_confidence is not None and confidence < policy.minimum_confidence:
            return None, "confidence_below_threshold"

        boosts: list[str] = []
        decays: list[str] = []
        config_tags = resolved_config.config.retrieval
        lexical_tokens = _tokenize(f"{title} {summary or ''} {' '.join(str(tag) for tag in entry.get('tags', ())) }")
        overlap = len(query_tokens & lexical_tokens)
        title_overlap = len(query_tokens & _tokenize(title))
        normalized_tags = {str(tag).lower() for tag in entry.get("tags", ())}
        tag_overlap = len(query_tokens & normalized_tags)

        lexical_score = float(overlap)
        if title_overlap > 0:
            lexical_score += float(title_overlap)
            boosts.append("title_overlap")
        if tag_overlap > 0:
            lexical_score += 0.5 * float(tag_overlap)
            boosts.append("explicit_tag")
        preferred_tags = {tag.lower() for tag in config_tags.prefer_tags}
        if preferred_tags and normalized_tags & preferred_tags:
            lexical_score += 0.5 * float(len(normalized_tags & preferred_tags))
            boosts.append("config_preferred_tag")
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

        stale_reason = _stale_decay_reason(
            stale_after=entry.get("stale_after"),
            last_confirmed_at=entry.get("last_confirmed_at"),
            created_at=entry.get("created_at"),
            window_days=config_tags.stale_decay_days,
        )
        if stale_reason is not None:
            combined_score -= policy.stale_decay_penalty
            decays.append(stale_reason)

        if entry.get("superseded") is True:
            combined_score -= policy.superseded_decay_penalty
            decays.append("superseded_artifact")

        if confidence is not None and confidence < policy.low_confidence_decay_start:
            decay = (policy.low_confidence_decay_start - confidence) * policy.low_confidence_decay_penalty
            combined_score -= decay
            decays.append("low_confidence_memory")
        suppressed_tags = {tag.lower() for tag in config_tags.suppress_tags}
        if suppressed_tags and normalized_tags & suppressed_tags:
            combined_score -= 0.75 * float(len(normalized_tags & suppressed_tags))
            decays.append("config_suppressed_tag")

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
    ) -> tuple[_ScoredManifestCandidate, ...]:
        ordered_ids: list[str] = []
        for doc_id in (*lexical_doc_ids, *embedding_doc_ids):
            if doc_id in candidate_index and doc_id not in ordered_ids:
                ordered_ids.append(doc_id)
        return tuple(candidate_index[doc_id] for doc_id in ordered_ids)

    def _rerank_candidates(
        self,
        *,
        query: str,
        query_tokens: set[str],
        candidates: Sequence[_ScoredManifestCandidate],
        lexical_doc_ids: Sequence[str],
        divergence: Mapping[str, Any],
        resolved_config: ResolvedMemoryConfig,
    ) -> dict[str, Any]:
        policy = self._retrieval_policy_for_config(resolved_config)
        retrieval_limit = self._retrieval_limit_for_config(resolved_config)
        reasons = _rerank_trigger_reasons(
            query=query,
            query_tokens=query_tokens,
            candidates=candidates,
            lexical_doc_ids=lexical_doc_ids,
            divergence=divergence,
            policy=policy,
        )
        fallback = tuple(candidates[:retrieval_limit])
        if not reasons:
            return {
                "triggered": False,
                "status": "skipped",
                "reasons": (),
                "candidate_count": len(candidates),
                "selected_candidates": fallback,
            }
        rerank_provider = self._rerank_provider_for_config(resolved_config)
        if rerank_provider is None:
            return {
                "triggered": False,
                "status": "provider_unavailable",
                "reasons": reasons,
                "candidate_count": len(candidates),
                "selected_candidates": fallback,
            }
        if not policy.rerank_budget_available:
            return {
                "triggered": False,
                "status": "budget_denied",
                "reasons": reasons,
                "candidate_count": len(candidates),
                "selected_candidates": fallback,
            }

        rerank_limit = policy.rerank_max_candidates or len(candidates)
        rerank_candidates = tuple(candidates[:rerank_limit])
        reranked_hits = tuple(
            hit
            for hit in rerank_provider.rerank(
                query=query,
                candidates=tuple(candidate.as_retrieval_candidate() for candidate in rerank_candidates),
                limit=retrieval_limit,
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
            "selected_candidates": tuple(ordered[:retrieval_limit]) if ordered else fallback,
        }

    def _shortlist_agent_namespace_documents(
        self,
        *,
        context: ResolvedMemoryScope,
        documents: Sequence[MemoryDocument],
        query: str,
        resolved_config: ResolvedMemoryConfig,
    ) -> tuple[tuple[MemoryDocument, ...], dict[str, Any]]:
        if not documents:
            return (), {"applied_filters": (), "decays": (), "selected_doc_ids": ()}
        query_tokens = _tokenize(query)
        if not query_tokens:
            return (), {"applied_filters": ("query_tokens:none",), "decays": (), "selected_doc_ids": ()}

        policy = self._retrieval_policy_for_config(resolved_config)
        preferred_tags = {tag.lower() for tag in resolved_config.config.retrieval.prefer_tags}
        suppressed_tags = {tag.lower() for tag in resolved_config.config.retrieval.suppress_tags}
        superseded_paths = _superseded_document_paths(context, documents)
        scored: list[tuple[float, MemoryDocument]] = []
        applied_filters: list[str] = []
        decays: list[str] = []
        for document in documents:
            score = _document_query_score(query_tokens, document)
            if score <= 0:
                continue
            normalized_tags = {str(tag).lower() for tag in document.metadata.get("tags", ())}
            if preferred_tags and normalized_tags & preferred_tags:
                score += 0.5 * float(len(normalized_tags & preferred_tags))
            if suppressed_tags and normalized_tags & suppressed_tags:
                score -= 0.75 * float(len(normalized_tags & suppressed_tags))
                decays.append("config_suppressed_tag")
            retention = str(document.metadata.get("retention") or "").strip()
            if retention == "drop":
                applied_filters.append("retention_drop")
                continue
            confidence = _coerce_confidence(document.metadata.get("confidence"))
            if confidence is not None and policy.minimum_confidence is not None and confidence < policy.minimum_confidence:
                applied_filters.append("confidence_below_threshold")
                continue
            if document.metadata.get("contested") is True:
                if policy.contested_policy == "block":
                    applied_filters.append("contested_policy:block")
                    continue
                if policy.contested_policy == "decay":
                    score -= policy.contested_decay_penalty
                    decays.append("contested_entry")
            stale_reason = _stale_decay_reason(
                stale_after=document.metadata.get("stale_after"),
                last_confirmed_at=document.metadata.get("last_confirmed_at"),
                created_at=document.metadata.get("created_at"),
                window_days=resolved_config.config.retrieval.stale_decay_days,
            )
            if stale_reason is not None:
                score -= policy.stale_decay_penalty
                decays.append(stale_reason)
            if confidence is not None and confidence < policy.low_confidence_decay_start:
                score -= (policy.low_confidence_decay_start - confidence) * policy.low_confidence_decay_penalty
                decays.append("low_confidence_memory")
            relative_path = document.path.relative_to(context.memory_root).as_posix()
            if relative_path in superseded_paths:
                score -= policy.superseded_decay_penalty
                decays.append("superseded_artifact")
            if score <= 0:
                continue
            scored.append((score, document))
        if not scored:
            return (), {
                "applied_filters": tuple(dict.fromkeys(applied_filters)),
                "decays": tuple(dict.fromkeys(decays)),
                "selected_doc_ids": (),
            }

        scored.sort(key=lambda item: (-item[0], item[1].path.as_posix()))
        selected = tuple(document for _, document in scored[:1])
        return selected, {
            "applied_filters": tuple(dict.fromkeys(applied_filters)),
            "decays": tuple(dict.fromkeys(decays)),
            "selected_doc_ids": tuple(
                document.path.relative_to(context.memory_root).as_posix()
                for document in selected
            ),
        }

    def _retrieval_limit_for_config(self, resolved_config: ResolvedMemoryConfig) -> int:
        configured = resolved_config.config.retrieval.max_results
        return configured if configured is not None else self.retrieval_limit

    def _retrieval_policy_for_config(self, resolved_config: ResolvedMemoryConfig) -> MemoryRetrievalPolicy:
        return self.retrieval_policy

    def _embedding_provider_for_config(
        self,
        resolved_config: ResolvedMemoryConfig,
    ) -> MemoryEmbeddingShortlistProvider | None:
        enabled = resolved_config.config.retrieval.embedding_enabled
        if enabled is False:
            return None
        return self.embedding_shortlist_provider

    def _rerank_provider_for_config(
        self,
        resolved_config: ResolvedMemoryConfig,
    ) -> MemoryRerankProvider | None:
        mode = resolved_config.config.retrieval.llm_rerank
        if mode == "disabled":
            return None
        return self.rerank_provider

    def _apply_configured_extraction_policy(
        self,
        *,
        context: ResolvedMemoryScope,
        agent: AgentDefinition,
        decision: MemoryExtractionDecision,
        resolved_config: ResolvedMemoryConfig,
    ) -> MemoryExtractionDecision | None:
        extraction = resolved_config.config.extraction
        always_capture = decision.fact_type in extraction.always_capture
        if always_capture:
            metadata = dict(decision.metadata)
            metadata["config_always_capture"] = True
            decision = replace(decision, metadata=metadata)

        if not always_capture and decision.fact_type in extraction.never_capture:
            metadata = dict(decision.metadata)
            metadata["config_never_capture"] = True
            metadata["namespace"] = "none"
            return replace(
                decision,
                target_layer="do_not_persist",
                namespace="none",
                retention="drop",
                merge_policy="no_write",
                metadata=metadata,
                reason="config_never_capture",
            )

        routing_target = extraction.routing.get(decision.fact_type)
        if routing_target is None and always_capture and decision.target_layer == "do_not_persist":
            routing_target = _DEFAULT_CAPTURE_ROUTING_TARGETS.get(decision.fact_type)
        if routing_target is None:
            return decision

        metadata = dict(decision.metadata)
        if routing_target == "agent_namespace":
            agent_name = normalize_memory_segment(agent.name, default="agent")
            metadata["agent_namespace"] = agent_name
            metadata["namespace"] = f"agent:{agent_name}"
            return replace(
                decision,
                target_layer="agent_namespace",
                namespace=f"agent:{agent_name}",
                metadata=metadata,
            )

        if routing_target == "session":
            metadata["namespace"] = "session"
            target_layer = "session_open_threads" if decision.fact_type == "session_thread" else "session_summary"
            return replace(decision, target_layer=target_layer, namespace="session", metadata=metadata)

        metadata["namespace"] = "shared"
        if routing_target == "long_term.preferences":
            metadata["memory_kind"] = "preference"
        elif routing_target == "long_term.conventions":
            metadata.setdefault("memory_kind", decision.fact_type)
        elif routing_target == "long_term.topics":
            metadata["memory_kind"] = "topic_memory"
        return replace(
            decision,
            target_layer="shared_long_term",
            namespace="shared",
            metadata=metadata,
        )

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
        context = self.resolve_context(
            session_id=payload.session_id,
            agent=payload.agent,
            cwd=payload.cwd,
        )
        resolved_config = self._resolve_memory_config(context)
        decisions = tuple(
            adjusted
            for decision in synthesize_background_memory_decisions(payload.messages, agent_name=payload.agent.name)
            if (adjusted := self._apply_configured_extraction_policy(
                context=context,
                agent=payload.agent,
                decision=decision,
                resolved_config=resolved_config,
            )) is not None
        )
        if not decisions:
            return MemoryTurnResult()

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
        return self._apply_extraction_decision(
            context=context,
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            decision=decision,
        )

    def _consolidation_key(self, context: ResolvedMemoryScope) -> str:
        return str(context.memory_root)

    def _run_background_consolidation_queue(self, key: str, task_id: str) -> MemoryTurnResult:
        aggregate = MemoryTurnResult()
        with self._consolidation_state_lock:
            pending = self._consolidation_pending.get(key)
        task_manager = pending.task_manager if pending is not None else None
        if task_manager is not None:
            task_manager.update(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={"status": "running"},
            )

        while True:
            with self._consolidation_state_lock:
                payload = self._consolidation_pending.pop(key, None)
            if payload is None:
                break
            task_manager = payload.task_manager or task_manager
            try:
                result = self._execute_background_consolidation(payload)
            except Exception as exc:  # pragma: no cover - defensive boundary
                if task_manager is not None:
                    task_manager.update(
                        task_id,
                        status=TaskStatus.FAILED,
                        error=str(exc),
                        metadata={"status": "failed"},
                    )
                break
            aggregate = _merge_turn_results(aggregate, result)
            with self._consolidation_state_lock:
                has_pending = key in self._consolidation_pending
            if task_manager is not None and has_pending:
                task_manager.update(
                    task_id,
                    status=TaskStatus.RUNNING,
                    metadata={"queued_merge": True, "trigger_session_id": payload.session_id},
                )

        if task_manager is not None and task_manager.get(task_id) is not None:
            task = task_manager.get(task_id)
            if task is not None and task.status != TaskStatus.FAILED:
                task_manager.update(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    result={
                        "persisted_count": len(aggregate.persisted_documents),
                        "receipt_count": len(aggregate.receipts),
                    },
                    metadata={"status": "completed"},
                )
        with self._consolidation_state_lock:
            self._consolidation_tasks_by_key.pop(key, None)
            if self._consolidation_task_ids.get(key) == task_id:
                self._consolidation_task_ids.pop(key, None)
        return aggregate

    def _read_consolidation_lock(self, context: ResolvedMemoryScope) -> dict[str, str] | None:
        payload = _read_json_path(context.consolidation_lock_path)
        if not isinstance(payload, dict):
            return None
        run_id = str(payload.get("run_id") or "").strip()
        acquired_at = str(payload.get("acquired_at") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        if not run_id or not acquired_at:
            return None
        lock_payload = {"run_id": run_id, "acquired_at": acquired_at}
        if session_id:
            lock_payload["session_id"] = session_id
        return lock_payload

    def _acquire_consolidation_lock(
        self,
        context: ResolvedMemoryScope,
        *,
        run_id: str,
        session_id: str,
    ) -> dict[str, str] | None:
        payload = {
            "run_id": run_id,
            "acquired_at": _utc_now_iso(),
            "session_id": session_id,
        }
        raw_payload = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        context.consolidations_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(
                    context.consolidation_lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                existing = self._read_consolidation_lock(context)
                if existing is not None or attempt == 1:
                    return None
                try:
                    context.consolidation_lock_path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    return None
                continue
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw_payload)
            return payload
        return None

    def _release_consolidation_lock(self, context: ResolvedMemoryScope, *, run_id: str) -> None:
        active_lock = self._read_consolidation_lock(context)
        if active_lock is not None and active_lock.get("run_id") != run_id:
            return
        try:
            context.consolidation_lock_path.unlink()
        except FileNotFoundError:
            return

    def _execute_background_consolidation(
        self,
        payload: _BackgroundConsolidationPayload,
    ) -> MemoryTurnResult:
        context = self.resolve_context(
            session_id=payload.session_id,
            agent=payload.agent,
            cwd=payload.cwd,
        )
        resolved_config = self._resolve_memory_config(context)
        manifest = self._refresh_consolidation_manifest(context)
        if not self._should_run_consolidation(context, resolved_config, manifest):
            return MemoryTurnResult()

        run_id = datetime.now(timezone.utc).strftime("cons-%Y%m%d-%H%M%S-") + uuid4().hex[:6]
        active_lock = self._acquire_consolidation_lock(
            context,
            run_id=run_id,
            session_id=payload.session_id,
        )
        if active_lock is None:
            self._refresh_consolidation_manifest(context)
            return MemoryTurnResult()
        manifest = self._refresh_consolidation_manifest(context, active_lock=active_lock)

        pending_sessions = self._pending_consolidation_sessions(context)
        checkpoint_path = context.consolidation_checkpoints_dir / f"{run_id}.json"
        staging_path = context.consolidation_staging_dir / f"{run_id}.json"
        log_path = context.consolidation_logs_dir / f"{run_id}.md"
        proposals = self._build_consolidation_proposals(context, pending_sessions)
        checkpoint_payload = {
            "run_id": run_id,
            "status": "staged",
            "session_ids": [session["session_id"] for session in pending_sessions],
            "proposal_count": len(proposals),
            "staging_path": staging_path.relative_to(context.memory_root).as_posix(),
            "log_path": log_path.relative_to(context.memory_root).as_posix(),
            "created_at": _utc_now_iso(),
        }
        _write_json_path(staging_path, {
            "run_id": run_id,
            "session_ids": [session["session_id"] for session in pending_sessions],
            "proposals": [self._serialize_consolidation_decision(decision) for decision in proposals],
        })
        _write_json_path(checkpoint_path, checkpoint_payload)

        log_lines = [
            f"# Consolidation Run {run_id}",
            "",
            f"- Status: staged",
            f"- Pending sessions: {len(pending_sessions)}",
            f"- Proposals: {len(proposals)}",
            "",
        ]
        log_path.write_text("\n".join(log_lines), encoding="utf-8")

        snapshot = self._snapshot_long_term_documents(context)
        try:
            result = self._merge_consolidation_proposals(
                context=context,
                agent=payload.agent,
                cwd=payload.cwd,
                decisions=proposals,
            )
        except Exception as exc:
            self._restore_long_term_snapshot(context, snapshot)
            checkpoint_payload["status"] = "failed"
            checkpoint_payload["error"] = str(exc)
            checkpoint_payload["failed_at"] = _utc_now_iso()
            _write_json_path(checkpoint_path, checkpoint_payload)
            log_path.write_text(
                "\n".join(
                    [
                        *log_lines,
                        f"- Final status: failed",
                        f"- Error: {exc}",
                    ]
                ),
                encoding="utf-8",
            )
            self._release_consolidation_lock(context, run_id=run_id)
            self._refresh_consolidation_manifest(
                context,
                active_lock=None,
                append_run={
                    "run_id": run_id,
                    "status": "failed",
                    "checkpoint_path": checkpoint_path.relative_to(context.memory_root).as_posix(),
                    "log_path": log_path.relative_to(context.memory_root).as_posix(),
                    "session_ids": [session["session_id"] for session in pending_sessions],
                },
            )
            raise

        completed_at = _utc_now_iso()
        self._mark_sessions_consolidated(
            context=context,
            session_ids=[session["session_id"] for session in pending_sessions],
            completed_at=completed_at,
        )
        checkpoint_payload["status"] = "success"
        checkpoint_payload["completed_at"] = completed_at
        checkpoint_payload["persisted_count"] = len(result.persisted_documents)
        checkpoint_payload["receipt_count"] = len(result.receipts)
        _write_json_path(checkpoint_path, checkpoint_payload)
        log_path.write_text(
            "\n".join(
                [
                    *log_lines,
                    f"- Final status: success",
                    f"- Persisted documents: {len(result.persisted_documents)}",
                    f"- Receipts: {len(result.receipts)}",
                ]
            ),
            encoding="utf-8",
        )
        self._release_consolidation_lock(context, run_id=run_id)
        self._refresh_consolidation_manifest(
            context,
            active_lock=None,
            append_run={
                "run_id": run_id,
                "status": "success",
                "checkpoint_path": checkpoint_path.relative_to(context.memory_root).as_posix(),
                "log_path": log_path.relative_to(context.memory_root).as_posix(),
                "session_ids": [session["session_id"] for session in pending_sessions],
            },
            last_successful_run_at=completed_at,
        )
        return result

    def _should_run_consolidation(
        self,
        context: ResolvedMemoryScope,
        resolved_config: ResolvedMemoryConfig,
        manifest: Mapping[str, Any],
    ) -> bool:
        if manifest.get("active_lock"):
            return False
        config = resolved_config.config.consolidation
        backlog = manifest.get("backlog", {}) if isinstance(manifest.get("backlog"), dict) else {}
        pending_count = int(backlog.get("closed_session_count", 0))
        if pending_count < config.min_closed_sessions:
            return False
        if pending_count < config.backlog_threshold:
            return False
        last_successful = _parse_iso_timestamp(manifest.get("last_successful_run_at"))
        if last_successful is None:
            return True
        hours_since = (datetime.now(timezone.utc) - last_successful).total_seconds() / 3600.0
        return hours_since >= float(config.min_hours_since_last_run)

    def _pending_consolidation_sessions(
        self,
        context: ResolvedMemoryScope,
    ) -> list[dict[str, Any]]:
        manifest = _read_json_path(context.session_manifest_path) or {}
        raw_sessions = manifest.get("sessions", ())
        session_records = raw_sessions if isinstance(raw_sessions, list) else ()
        pending: list[dict[str, Any]] = []
        for record in session_records:
            if not isinstance(record, dict):
                continue
            if record.get("ready_for_consolidation") is not True:
                continue
            session_id = str(record.get("session_id") or "").strip()
            if not session_id:
                continue
            metadata = _read_json_path(context.session_metadata_path(session_id)) or {}
            if metadata.get("status") in {"active", "waiting"}:
                continue
            last_consolidated_at = _parse_iso_timestamp(metadata.get("last_consolidated_at"))
            updated_at = _parse_iso_timestamp(metadata.get("updated_at") or metadata.get("created_at"))
            if last_consolidated_at is not None and updated_at is not None and last_consolidated_at >= updated_at:
                continue
            summary_path = context.session_summary_path(session_id)
            summary_text = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
            pending.append(
                {
                    "session_id": session_id,
                    "summary_text": summary_text,
                    "metadata": metadata,
                    "updated_at": metadata.get("updated_at"),
                }
            )
        pending.sort(key=lambda item: str(item.get("updated_at") or ""))
        return pending

    def _refresh_consolidation_manifest(
        self,
        context: ResolvedMemoryScope,
        *,
        active_lock: object = _MISSING,
        append_run: Mapping[str, Any] | None = None,
        last_successful_run_at: object = _MISSING,
    ) -> dict[str, Any]:
        existing = _read_json_path(context.consolidation_manifest_path) or {}
        recent_runs = existing.get("recent_runs", [])
        if not isinstance(recent_runs, list):
            recent_runs = []
        normalized_runs = [run for run in recent_runs if isinstance(run, dict)]
        if append_run is not None:
            normalized_runs.append(dict(append_run))
            normalized_runs = normalized_runs[-10:]

        pending_sessions = self._pending_consolidation_sessions(context)
        runs_payload = [
            {
                "run_id": str(run.get("run_id") or ""),
                "status": str(run.get("status") or "unknown"),
                "checkpoint_path": str(run.get("checkpoint_path") or ""),
                "log_path": str(run.get("log_path") or ""),
            }
            for run in normalized_runs
            if str(run.get("run_id") or "").strip()
        ]
        manifest = {
            "schema_version": "memory.v2",
            "manifest_kind": "consolidation",
            "boundary_scope": context.scope.value,
            "generated_at": _utc_now_iso(),
            "stats": {"entry_count": len(runs_payload), "stale_entry_count": 0},
            "runs": runs_payload,
            "backlog": {
                "closed_session_count": len(pending_sessions),
                "pending_session_ids": [session["session_id"] for session in pending_sessions],
            },
            "recent_runs": normalized_runs,
            "last_successful_run_at": (
                existing.get("last_successful_run_at")
                if last_successful_run_at is _MISSING
                else last_successful_run_at
            ),
            "active_lock": self._read_consolidation_lock(context) if active_lock is _MISSING else active_lock,
        }
        _write_json_path(context.consolidation_manifest_path, manifest)
        return manifest

    def _build_consolidation_proposals(
        self,
        context: ResolvedMemoryScope,
        pending_sessions: Sequence[Mapping[str, Any]],
    ) -> tuple[MemoryExtractionDecision, ...]:
        preference_groups: dict[str, dict[str, Any]] = {}
        convention_groups: dict[str, dict[str, Any]] = {}
        topic_sessions: dict[str, set[str]] = {}
        topic_examples: dict[str, list[str]] = {}

        for session in pending_sessions:
            session_id = str(session.get("session_id") or "")
            summary_text = _normalize_summary_text(str(session.get("summary_text") or ""))
            if summary_text:
                for token in _topic_tokens(summary_text):
                    topic_sessions.setdefault(token, set()).add(session_id)
                    examples = topic_examples.setdefault(token, [])
                    if len(examples) < 2:
                        examples.append(summary_text)

            metadata = session.get("metadata", {})
            deltas = metadata.get("durable_memory_deltas", ()) if isinstance(metadata, dict) else ()
            for delta in deltas if isinstance(deltas, list) else ():
                if not isinstance(delta, dict):
                    continue
                relative_path = delta.get("path")
                if not isinstance(relative_path, str) or not relative_path.strip():
                    continue
                documents = self.provider.materialize_documents(context, (relative_path,))
                if not documents:
                    continue
                document = documents[0]
                conflict_key = str(
                    delta.get("conflict_key")
                    or document.metadata.get("conflict_key")
                    or document.title
                ).strip()
                key = conflict_key or _normalize_document_content(document.content)
                bucket: dict[str, dict[str, Any]]
                if document.kind == "preference":
                    bucket = preference_groups
                elif document.kind in {"project_convention", "workflow_command"}:
                    bucket = convention_groups
                else:
                    for token in _topic_tokens(document.content):
                        topic_sessions.setdefault(token, set()).add(session_id)
                        examples = topic_examples.setdefault(token, [])
                        if len(examples) < 2:
                            examples.append(_summarize_memory_text(document.content))
                    continue
                group = bucket.setdefault(
                    key,
                    {
                        "document": document,
                        "session_ids": set(),
                    },
                )
                group["session_ids"].add(session_id)

        proposals: list[MemoryExtractionDecision] = []
        for group in preference_groups.values():
            session_ids = sorted(group["session_ids"])
            if len(session_ids) < 2:
                continue
            document = group["document"]
            metadata = dict(document.metadata)
            metadata["source_pathway"] = "consolidation"
            metadata["summary"] = _summarize_memory_text(document.content)
            proposals.append(
                MemoryExtractionDecision(
                    fact_type="preference",
                    title=document.title,
                    content=document.content,
                    target_layer="shared_long_term",
                    namespace="shared",
                    retention="durable_until_superseded",
                    merge_policy="require_multi_source_confirmation",
                    metadata=metadata,
                    source_message_ids=tuple(session_ids),
                    source_roles=("consolidation",),
                    reason="cross_session_preference",
                )
            )

        for group in convention_groups.values():
            session_ids = sorted(group["session_ids"])
            if len(session_ids) < 2:
                continue
            document = group["document"]
            metadata = dict(document.metadata)
            metadata["source_pathway"] = "consolidation"
            metadata["summary"] = _summarize_memory_text(document.content)
            merge_policy = "merge_with_last_confirmed_at" if document.kind == "workflow_command" else "merge_with_provenance"
            proposals.append(
                MemoryExtractionDecision(
                    fact_type=document.kind,
                    title=document.title,
                    content=document.content,
                    target_layer="shared_long_term",
                    namespace="shared",
                    retention="durable_until_revoked",
                    merge_policy=merge_policy,
                    metadata=metadata,
                    source_message_ids=tuple(session_ids),
                    source_roles=("consolidation",),
                    reason="cross_session_convention",
                )
            )

        ranked_topics = sorted(
            ((token, sessions) for token, sessions in topic_sessions.items() if len(sessions) >= 2),
            key=lambda item: (-len(item[1]), item[0]),
        )
        if ranked_topics:
            token, sessions = ranked_topics[0]
            examples = topic_examples.get(token, [])[:2]
            content = f"Cross-session discussion repeatedly centered on {token}. {' '.join(examples)}".strip()
            proposals.append(
                MemoryExtractionDecision(
                    fact_type="topic_memory",
                    title=f"Topic Memory {token.title()}",
                    content=content,
                    target_layer="shared_long_term",
                    namespace="shared",
                    retention="durable_until_superseded",
                    merge_policy="synthesize_then_merge",
                    metadata={
                        "memory_kind": "topic_memory",
                        "namespace": "shared",
                        "retention": "durable_until_superseded",
                        "merge_policy": "synthesize_then_merge",
                        "source_pathway": "consolidation",
                        "source_message_ids": sorted(sessions),
                        "source_roles": ["consolidation"],
                        "tags": [token],
                        "summary": _summarize_memory_text(content),
                        "conflict_key": f"topic_memory.{normalize_memory_segment(token, default='topic')}",
                        "confidence": min(0.95, 0.55 + (0.1 * len(sessions))),
                    },
                    source_message_ids=tuple(sorted(sessions)),
                    source_roles=("consolidation",),
                    reason="cross_session_topic",
                )
            )

        return tuple(proposals)

    def _merge_consolidation_proposals(
        self,
        *,
        context: ResolvedMemoryScope,
        agent: AgentDefinition,
        cwd: str | Path,
        decisions: Sequence[MemoryExtractionDecision],
    ) -> MemoryTurnResult:
        persisted_documents: list[MemoryDocument] = []
        receipts: list[MemoryWriteReceipt] = []
        for decision in decisions:
            receipt, written = self._apply_durable_extraction_decision(
                context=context,
                session_id=context.session_id,
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

    def _serialize_consolidation_decision(self, decision: MemoryExtractionDecision) -> dict[str, Any]:
        return {
            "fact_type": decision.fact_type,
            "title": decision.title,
            "content": decision.content,
            "target_layer": decision.target_layer,
            "namespace": decision.namespace,
            "retention": decision.retention,
            "merge_policy": decision.merge_policy,
            "metadata": dict(decision.metadata),
            "source_message_ids": list(decision.source_message_ids),
            "source_roles": list(decision.source_roles),
            "reason": decision.reason,
        }

    def _snapshot_long_term_documents(self, context: ResolvedMemoryScope) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for path in sorted(context.documents_dir.rglob("*.md")):
            if not path.is_file():
                continue
            snapshot[path.relative_to(context.memory_root).as_posix()] = path.read_text(encoding="utf-8")
        return snapshot

    def _restore_long_term_snapshot(self, context: ResolvedMemoryScope, snapshot: Mapping[str, str]) -> None:
        current_paths = {
            path.relative_to(context.memory_root).as_posix(): path
            for path in context.documents_dir.rglob("*.md")
            if path.is_file()
        }
        for relative_path, content in snapshot.items():
            path = context.memory_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for relative_path, path in current_paths.items():
            if relative_path not in snapshot:
                path.unlink()
        self.provider.prepare_context(context)

    def _mark_sessions_consolidated(
        self,
        *,
        context: ResolvedMemoryScope,
        session_ids: Sequence[str],
        completed_at: str,
    ) -> None:
        for session_id in session_ids:
            metadata_path = context.session_metadata_path(session_id)
            metadata = _read_json_path(metadata_path) or {}
            metadata["last_consolidated_at"] = completed_at
            _write_json_path(metadata_path, metadata)
        self._refresh_consolidation_manifest(context)

    def _find_conflict_key_documents(
        self,
        *,
        context: ResolvedMemoryScope,
        namespace: str,
        conflict_key: str,
        active_only: bool = False,
    ) -> tuple[MemoryDocument, ...]:
        documents = self._list_namespace_documents(context, namespace)
        matches: list[MemoryDocument] = []
        for document in documents:
            candidate_conflict_key = document.metadata.get("conflict_key")
            if isinstance(candidate_conflict_key, str) and candidate_conflict_key.strip() == conflict_key:
                matches.append(document)
        if not active_only:
            return tuple(matches)
        superseded_paths = _superseded_document_paths(context, matches)
        return tuple(
            document
            for document in matches
            if document.path.relative_to(context.memory_root).as_posix() not in superseded_paths
        )

    def _list_namespace_documents(
        self,
        context: ResolvedMemoryScope,
        namespace: str,
    ) -> tuple[MemoryDocument, ...]:
        if namespace.startswith("agent:"):
            agent_name = namespace.partition(":")[2].strip()
            return self._load_agent_namespace_documents(context, agent_name)
        return self.provider.list_documents(context)

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
            return self._apply_durable_extraction_decision(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
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
            self._build_write_receipt(
                context=context,
                decision=decision,
                action="dropped",
                title=decision.title,
                reason=decision.reason or "do_not_persist",
            ),
            (),
        )

    def _apply_durable_extraction_decision(
        self,
        *,
        context: ResolvedMemoryScope,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        decision: MemoryExtractionDecision,
    ) -> tuple[MemoryWriteReceipt, tuple[MemoryDocument, ...]]:
        if decision.retention == "drop" or decision.merge_policy == "no_write":
            return (
                self._build_write_receipt(
                    context=context,
                    decision=decision,
                    action="dropped",
                    title=decision.title,
                    reason=decision.reason or "do_not_persist",
                ),
                (),
            )

        conflict_key = decision.metadata.get("conflict_key")
        if not isinstance(conflict_key, str) or not conflict_key.strip():
            return self._persist_durable_entry(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
            )

        active_documents = self._find_conflict_key_documents(
            context=context,
            namespace=decision.namespace,
            conflict_key=conflict_key.strip(),
            active_only=True,
        )
        matching_document = next(
            (
                document
                for document in active_documents
                if _normalize_document_content(document.content) == _normalize_document_content(decision.content)
            ),
            None,
        )
        merge_policy = decision.merge_policy

        if merge_policy in {
            "merge_with_provenance",
            "merge_with_last_confirmed_at",
            "require_multi_source_confirmation",
            "synthesize_then_merge",
        }:
            if matching_document is not None:
                return self._merge_existing_durable_document(
                    context=context,
                    decision=decision,
                    document=matching_document,
                )
            if active_documents:
                return self._stage_contested_durable_entry(
                    context=context,
                    session_id=session_id,
                    agent=agent,
                    cwd=cwd,
                    decision=decision,
                    reason="guarded_conflict",
                )
            return self._persist_durable_entry(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
            )

        if merge_policy == "append_with_dedupe":
            if matching_document is not None:
                return self._merge_existing_durable_document(
                    context=context,
                    decision=decision,
                    document=matching_document,
                )
            if active_documents:
                merged_document = active_documents[0]
                return self._merge_existing_durable_document(
                    context=context,
                    decision=decision,
                    document=merged_document,
                    content=_append_distinct_content(merged_document.content, decision.content),
                    reason="append_with_dedupe",
                )
            return self._persist_durable_entry(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
            )

        if merge_policy in {"overwrite_on_newer_confirmation", "overwrite_inside_namespace"}:
            if matching_document is not None:
                return self._merge_existing_durable_document(
                    context=context,
                    decision=decision,
                    document=matching_document,
                )
            supersedes = tuple(
                document.path.relative_to(context.memory_root).as_posix()
                for document in active_documents
                if not document.metadata.get("contested")
            )
            return self._persist_durable_entry(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
                metadata_overrides={"supersedes": list(supersedes)} if supersedes else None,
                reason="superseded_existing" if supersedes else None,
                supersedes=supersedes,
            )

        if matching_document is not None:
            return self._merge_existing_durable_document(
                context=context,
                decision=decision,
                document=matching_document,
            )
        if active_documents:
            return self._stage_contested_durable_entry(
                context=context,
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                decision=decision,
                reason="unsupported_merge_policy_conflict",
            )
        return self._persist_durable_entry(
            context=context,
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            decision=decision,
        )

    def _persist_durable_entry(
        self,
        *,
        context: ResolvedMemoryScope,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        decision: MemoryExtractionDecision,
        metadata_overrides: Mapping[str, Any] | None = None,
        reason: str | None = None,
        supersedes: Sequence[str] = (),
    ) -> tuple[MemoryWriteReceipt, tuple[MemoryDocument, ...]]:
        written = self.persist_entries(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            entries=(self._decision_entry(decision, metadata_overrides=metadata_overrides),),
        )
        if written:
            document = written[0]
            return (
                self._build_write_receipt(
                    context=context,
                    decision=decision,
                    action="persisted",
                    title=document.title,
                    path=document.path,
                    reason=reason,
                    supersedes=supersedes,
                ),
                written,
            )
        return (
            self._build_write_receipt(
                context=context,
                decision=decision,
                action="skipped_duplicate",
                title=decision.title,
                reason="duplicate_content",
                supersedes=supersedes,
            ),
            (),
        )

    def _merge_existing_durable_document(
        self,
        *,
        context: ResolvedMemoryScope,
        decision: MemoryExtractionDecision,
        document: MemoryDocument,
        content: str | None = None,
        reason: str | None = None,
        metadata_overrides: Mapping[str, Any] | None = None,
    ) -> tuple[MemoryWriteReceipt, tuple[MemoryDocument, ...]]:
        merged_content = content or document.content
        merged_metadata = _merged_memory_metadata(
            document=document,
            decision=decision,
            content=merged_content,
            metadata_overrides=metadata_overrides,
        )
        updated = self.provider.update_document(
            context,
            document,
            title=document.title,
            content=merged_content,
            metadata_updates=merged_metadata,
        )
        if updated is None:
            return (
                self._build_write_receipt(
                    context=context,
                    decision=decision,
                    action="dropped",
                    title=document.title,
                    path=document.path,
                    reason="merge_update_failed",
                ),
                (),
            )
        return (
            self._build_write_receipt(
                context=context,
                decision=decision,
                action="merged",
                title=updated.title,
                path=updated.path,
                reason=reason or decision.merge_policy,
            ),
            (updated,),
        )

    def _stage_contested_durable_entry(
        self,
        *,
        context: ResolvedMemoryScope,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        decision: MemoryExtractionDecision,
        reason: str,
    ) -> tuple[MemoryWriteReceipt, tuple[MemoryDocument, ...]]:
        metadata_overrides = {
            "contested": True,
            "retention": "review_required",
            "tags": list(_merge_string_values(decision.metadata.get("tags", ()), ("contested",))),
        }
        written = self.persist_entries(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            entries=(
                self._decision_entry(
                    decision,
                    title=f"Contested {decision.title}".strip(),
                    metadata_overrides=metadata_overrides,
                ),
            ),
        )
        if written:
            document = written[0]
            return (
                self._build_write_receipt(
                    context=context,
                    decision=decision,
                    action="staged_contested",
                    title=document.title,
                    path=document.path,
                    reason=reason,
                    contested=True,
                ),
                written,
            )
        return (
            self._build_write_receipt(
                context=context,
                decision=decision,
                action="skipped_duplicate",
                title=f"Contested {decision.title}".strip(),
                reason="duplicate_contested_content",
                contested=True,
            ),
            (),
        )

    def _decision_entry(
        self,
        decision: MemoryExtractionDecision,
        *,
        title: str | None = None,
        content: str | None = None,
        metadata_overrides: Mapping[str, Any] | None = None,
    ) -> MemoryEntry:
        metadata = dict(decision.metadata)
        metadata.setdefault("namespace", decision.namespace)
        metadata.setdefault("retention", decision.retention)
        metadata.setdefault("merge_policy", decision.merge_policy)
        metadata.setdefault("source_message_ids", list(decision.source_message_ids))
        metadata.setdefault("source_roles", list(decision.source_roles))
        if metadata_overrides is not None:
            metadata.update(dict(metadata_overrides))
        return MemoryEntry(
            title=title or decision.title,
            content=content or decision.content,
            metadata=metadata,
        )

    def _build_write_receipt(
        self,
        *,
        context: ResolvedMemoryScope,
        decision: MemoryExtractionDecision,
        action: str,
        title: str | None = None,
        path: Path | None = None,
        reason: str | None = None,
        contested: bool | None = None,
        supersedes: Sequence[str] = (),
    ) -> MemoryWriteReceipt:
        conflict_key = decision.metadata.get("conflict_key")
        source_pathway = decision.metadata.get("source_pathway")
        return MemoryWriteReceipt(
            fact_type=decision.fact_type,
            action=action,
            scope=context.scope.value,
            target_layer=decision.target_layer,
            namespace=decision.namespace,
            retention=decision.retention,
            merge_policy=decision.merge_policy,
            title=title,
            path=path,
            reason=reason,
            source_pathway=source_pathway if isinstance(source_pathway, str) and source_pathway.strip() else None,
            conflict_key=conflict_key if isinstance(conflict_key, str) and conflict_key.strip() else None,
            contested=decision.metadata.get("contested") is True if contested is None else contested,
            source_message_ids=decision.source_message_ids,
            source_roles=decision.source_roles,
            supersedes=tuple(str(item) for item in supersedes),
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
        memory_config: Mapping[str, Any] | MemoryRuntimeConfig | None = None,
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
            memory_config=memory_config,
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
    ) -> SidecarContributionResult:
        _ = runtime_context
        fragments, trace = self.manager.collect_with_trace(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
        )
        return SidecarContributionResult(
            prompt_fragments=fragments,
            diagnostics={
                "memory_retrieval": trace,
                "memory_diagnostics": {"retrieval": trace},
            },
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

    async def schedule_background_consolidation(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
        task_manager: TaskManager | None = None,
    ) -> str | None:
        return self.manager.schedule_background_consolidation(
            session_id=session_id,
            agent=agent,
            cwd=cwd,
            task_manager=task_manager,
        )

    async def wait_for_background_consolidation(self, task_id: str) -> MemoryTurnResult:
        return await self.manager.wait_for_background_consolidation(task_id)

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

    def resolve_config(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> ResolvedMemoryConfig:
        return self.manager.resolve_config(session_id=session_id, agent=agent, cwd=cwd)

    def session_summary_thresholds(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str | Path,
    ) -> dict[str, int]:
        return self.manager.session_summary_thresholds(session_id=session_id, agent=agent, cwd=cwd)

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


def _append_distinct_content(existing: str, incoming: str) -> str:
    normalized_existing = " ".join(existing.strip().split())
    normalized_incoming = " ".join(incoming.strip().split())
    if not normalized_existing:
        return normalized_incoming
    if not normalized_incoming or _normalize_document_content(normalized_incoming) in _normalize_document_content(normalized_existing):
        return normalized_existing
    if normalized_existing[-1] in ".!?":
        return f"{normalized_existing} {normalized_incoming}"
    return f"{normalized_existing}. {normalized_incoming}"


def _merge_string_values(*values: object) -> tuple[str, ...]:
    merged: list[str] = []
    for value in values:
        if isinstance(value, str):
            candidate_values = (value,)
        elif isinstance(value, (list, tuple)):
            candidate_values = tuple(value)
        else:
            continue
        for candidate in candidate_values:
            if not isinstance(candidate, str):
                continue
            normalized = candidate.strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return tuple(merged)


def _merged_memory_metadata(
    *,
    document: MemoryDocument,
    decision: MemoryExtractionDecision,
    content: str,
    metadata_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(document.metadata)
    metadata.update(dict(decision.metadata))
    metadata["retention"] = decision.retention
    metadata["merge_policy"] = decision.merge_policy
    metadata["namespace"] = decision.namespace
    metadata["last_confirmed_at"] = _utc_now_iso()
    metadata["source_message_ids"] = list(
        _merge_string_values(document.metadata.get("source_message_ids", ()), decision.source_message_ids)
    )
    metadata["source_roles"] = list(_merge_string_values(document.metadata.get("source_roles", ()), decision.source_roles))
    metadata["tags"] = list(_merge_string_values(document.metadata.get("tags", ()), decision.metadata.get("tags", ())))
    metadata["summary"] = _summarize_memory_text(content)
    if metadata_overrides is not None:
        metadata.update(dict(metadata_overrides))
    return metadata


def _superseded_document_paths(
    context: ResolvedMemoryScope,
    documents: Sequence[MemoryDocument],
) -> set[str]:
    known_paths = {document.path.relative_to(context.memory_root).as_posix() for document in documents}
    superseded: set[str] = set()
    for document in documents:
        for reference in document.metadata.get("supersedes", ()):
            if isinstance(reference, str) and reference in known_paths:
                superseded.add(reference)
    return superseded


def _summarize_memory_text(text: str, *, limit: int = 160) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_path(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_path(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2) + "\n", encoding="utf-8")


def _parse_iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_summary_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return " ".join(lines)


def _topic_tokens(text: str) -> tuple[str, ...]:
    tokens = [
        token
        for token in _tokenize(text)
        if token not in _STOPWORDS and token not in {"session", "memory", "issue", "problem", "summary"}
    ]
    return tuple(dict.fromkeys(tokens))


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


def _stale_decay_reason(
    *,
    stale_after: object,
    last_confirmed_at: object,
    created_at: object,
    window_days: int | None,
) -> str | None:
    if _stale_entry(stale_after):
        return "stale_beyond_threshold"
    if window_days is None:
        return None
    if _stale_entry(
        None,
        last_confirmed_at=last_confirmed_at,
        created_at=created_at,
        window_days=window_days,
    ):
        return "config_stale_window"
    return None


def _stale_entry(
    value: object,
    *,
    last_confirmed_at: object = None,
    created_at: object = None,
    window_days: int | None = None,
) -> bool:
    stale_at = _parse_iso_timestamp(value)
    if stale_at is not None:
        return stale_at <= datetime.now(timezone.utc)
    if window_days is None:
        return False
    anchor = _parse_iso_timestamp(last_confirmed_at) or _parse_iso_timestamp(created_at)
    if anchor is None:
        return False
    return anchor <= datetime.now(timezone.utc) - timedelta(days=max(1, window_days))
