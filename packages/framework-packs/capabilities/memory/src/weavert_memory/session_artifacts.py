from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from weavert.contracts import MessageRole, RuntimeMessage, TextBlock, ToolResultBlock, ToolUseBlock
from .models import MemoryDocument, MemoryWriteReceipt, normalize_memory_segment
from .schema import SESSION_MANIFEST_KIND, build_manifest_envelope

_SESSION_SUMMARY_TURN_THRESHOLD = 6
_SESSION_SUMMARY_CHAR_THRESHOLD = 4000
_SESSION_SUMMARY_TOOL_CALL_THRESHOLD = 8


def ensure_session_artifacts(
    *,
    context: Any,
    session_id: str,
    status: str,
) -> None:
    session_root = context.session_root()
    checkpoints_dir = session_root / "checkpoints"
    session_root.mkdir(parents=True, exist_ok=True)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    if not context.session_open_threads_path().exists():
        context.session_open_threads_path().write_text("# Open Threads\n\n", encoding="utf-8")

    metadata = _default_session_metadata(session_id=session_id, status=status)
    existing_metadata = _read_json_file(context.session_metadata_path())
    if isinstance(existing_metadata, dict):
        metadata.update(existing_metadata)
    metadata["status"] = status
    metadata["updated_at"] = _utc_now_iso()
    metadata["open_thread_count"] = _count_open_threads(context.session_open_threads_path())
    _write_json_file(context.session_metadata_path(), metadata)
    _upsert_session_manifest(context, metadata)


def update_session_status(
    *,
    context: Any,
    session_id: str,
    status: str,
) -> None:
    ensure_session_artifacts(context=context, session_id=session_id, status=status)
    metadata = _read_json_file(context.session_metadata_path())
    if not isinstance(metadata, dict):
        metadata = _default_session_metadata(session_id=session_id, status=status)
    metadata["status"] = status
    metadata["updated_at"] = _utc_now_iso()
    metadata["open_thread_count"] = _count_open_threads(context.session_open_threads_path())
    _write_json_file(context.session_metadata_path(), metadata)
    _upsert_session_manifest(context, metadata)


def record_session_compaction(
    *,
    context: Any,
    session_id: str,
) -> None:
    metadata = _read_json_file(context.session_metadata_path())
    if not isinstance(metadata, dict):
        metadata = _default_session_metadata(session_id=session_id, status="active")
    metadata["last_compaction_at"] = _utc_now_iso()
    metadata["updated_at"] = metadata["last_compaction_at"]
    metadata["open_thread_count"] = _count_open_threads(context.session_open_threads_path())
    _write_json_file(context.session_metadata_path(), metadata)
    _upsert_session_manifest(context, metadata)


def refresh_session_artifacts(
    *,
    context: Any,
    session_id: str,
    agent_name: str,
    turn_id: str | None,
    messages: Sequence[RuntimeMessage],
    session_messages: Sequence[RuntimeMessage],
    status: str,
    prior_status: str | None,
    refresh_thresholds: dict[str, int],
    terminal: Any,
) -> None:
    ensure_session_artifacts(context=context, session_id=session_id, status=status)
    metadata = _read_json_file(context.session_metadata_path())
    if not isinstance(metadata, dict):
        metadata = _default_session_metadata(session_id=session_id, status="active")

    metadata["status"] = status
    updated_at = _utc_now_iso()
    metadata["updated_at"] = updated_at
    metadata["turns_since_summary"] = int(metadata.get("turns_since_summary", 0)) + 1
    metadata["chars_since_summary"] = int(metadata.get("chars_since_summary", 0)) + sum(
        len(message.text.strip()) for message in messages if message.text.strip()
    )
    metadata["tool_calls_since_summary"] = int(metadata.get("tool_calls_since_summary", 0)) + _count_tool_events(messages)

    open_threads_path = context.session_open_threads_path()
    existing_threads = _read_open_threads(open_threads_path)
    open_threads = _reconcile_open_threads(
        path=open_threads_path,
        existing_threads=existing_threads,
        candidate=_session_thread_candidate(
            messages=tuple(messages),
            agent_name=agent_name,
            terminal=terminal,
        ),
        agent_name=agent_name,
        prior_status=prior_status,
        prompt_text=_primary_user_prompt_text(tuple(messages)),
    )
    open_threads_changed = open_threads != existing_threads
    metadata["open_thread_count"] = len(open_threads)

    if _should_refresh_session_summary(
        context,
        metadata,
        refresh_thresholds=refresh_thresholds,
        open_threads_changed=open_threads_changed,
        prior_status=prior_status,
    ):
        context.session_summary_path().write_text(
            _render_session_summary(
                session_id=session_id,
                agent_name=agent_name,
                turn_id=turn_id,
                messages=list(session_messages),
                open_threads=open_threads,
                status=metadata["status"],
                updated_at=updated_at,
            ),
            encoding="utf-8",
        )
        metadata["summary_version"] = int(metadata.get("summary_version", 0)) + 1
        metadata["last_summary_refresh_at"] = updated_at
        metadata["turns_since_summary"] = 0
        metadata["chars_since_summary"] = 0
        metadata["tool_calls_since_summary"] = 0

    _write_json_file(context.session_metadata_path(), metadata)
    _upsert_session_manifest(context, metadata)


def record_session_memory_deltas(
    *,
    context: Any,
    session_id: str,
    persisted: Sequence[MemoryDocument],
    receipts: Sequence[MemoryWriteReceipt],
) -> None:
    if not persisted:
        return
    metadata = _read_json_file(context.session_metadata_path())
    if not isinstance(metadata, dict):
        metadata = _default_session_metadata(session_id=session_id, status="active")
    existing = metadata.get("durable_memory_deltas", [])
    durable_deltas = [entry for entry in existing if isinstance(entry, dict)] if isinstance(existing, list) else []
    known_paths = {
        str(entry.get("path"))
        for entry in durable_deltas
        if isinstance(entry.get("path"), str)
    }
    receipts_by_path = {
        str(receipt.path): receipt
        for receipt in receipts
        if receipt.path is not None
    }
    for document in persisted:
        if not document.path.is_relative_to(context.documents_dir):
            continue
        path = str(document.path)
        if path in known_paths:
            continue
        receipt = receipts_by_path.get(path)
        durable_deltas.append(
            {
                "path": document.path.relative_to(context.memory_root).as_posix(),
                "memory_kind": document.kind,
                "title": document.title,
                "conflict_key": document.metadata.get("conflict_key"),
                "source_pathway": (
                    receipt.source_pathway
                    if receipt is not None
                    else document.metadata.get("source_pathway")
                ),
            }
        )
        known_paths.add(path)
    metadata["durable_memory_deltas"] = durable_deltas
    metadata["durable_memory_delta_count"] = len(durable_deltas)
    _write_json_file(context.session_metadata_path(), metadata)
    _upsert_session_manifest(context, metadata)


def serialize_write_receipts(receipts: Sequence[MemoryWriteReceipt]) -> tuple[dict[str, object], ...]:
    return tuple(_memory_write_receipt_payload(receipt) for receipt in receipts)


def default_session_summary_thresholds() -> dict[str, int]:
    return {
        "token_growth_threshold": _SESSION_SUMMARY_CHAR_THRESHOLD,
        "tool_call_threshold": _SESSION_SUMMARY_TOOL_CALL_THRESHOLD,
        "turn_threshold": _SESSION_SUMMARY_TURN_THRESHOLD,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_session_metadata(*, session_id: str, status: str) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "session_id": session_id,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "summary_version": 0,
        "open_thread_count": 0,
        "last_compaction_at": None,
        "last_summary_refresh_at": None,
        "last_consolidated_at": None,
        "turns_since_summary": 0,
        "chars_since_summary": 0,
        "tool_calls_since_summary": 0,
        "durable_memory_delta_count": 0,
        "durable_memory_deltas": [],
    }


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _upsert_session_manifest(context: Any, metadata: dict[str, Any]) -> None:
    existing_manifest = _read_json_file(context.session_manifest_path) or {}
    raw_sessions = existing_manifest.get("sessions", ())
    sessions = [entry for entry in raw_sessions if isinstance(entry, dict)] if isinstance(raw_sessions, list) else []
    session_root = context.session_root()
    checkpoint_count = len(list((session_root / "checkpoints").glob("*.json")))
    open_thread_count = _count_open_threads(context.session_open_threads_path())
    record = {
        "session_id": metadata.get("session_id", context.session_id),
        "status": metadata.get("status", "active"),
        "path": session_root.relative_to(context.memory_root).as_posix() + "/",
        "has_summary": context.session_summary_path().exists(),
        "has_open_threads": open_thread_count > 0,
        "open_thread_count": open_thread_count,
        "checkpoint_count": checkpoint_count,
        "last_updated_at": metadata.get("updated_at") or _utc_now_iso(),
        "ready_for_consolidation": metadata.get("status") not in {"active", "waiting"},
        "durable_memory_delta_count": int(metadata.get("durable_memory_delta_count", 0)),
    }
    if metadata.get("last_compaction_at"):
        record["last_compaction_at"] = metadata["last_compaction_at"]
    if metadata.get("last_consolidated_at"):
        record["last_consolidated_at"] = metadata["last_consolidated_at"]
    deduped = [entry for entry in sessions if entry.get("session_id") != record["session_id"]]
    deduped.append(record)
    deduped.sort(key=lambda entry: str(entry.get("session_id", "")))
    manifest = build_manifest_envelope(
        manifest_kind=SESSION_MANIFEST_KIND,
        boundary_scope=context.scope,
        payload_key="sessions",
        payload=deduped,
    )
    _write_json_file(context.session_manifest_path, manifest)


def _count_open_threads(path: Path) -> int:
    return len(_read_open_threads(path))


def _count_tool_events(messages: Sequence[RuntimeMessage]) -> int:
    total = 0
    for message in messages:
        total += sum(1 for block in message.content if isinstance(block, (ToolUseBlock, ToolResultBlock)))
    return total


def _should_refresh_session_summary(
    context: Any,
    metadata: dict[str, Any],
    *,
    refresh_thresholds: dict[str, int],
    open_threads_changed: bool = False,
    prior_status: str | None = None,
) -> bool:
    if not context.session_summary_path().exists():
        return True
    if open_threads_changed:
        return True
    if prior_status == "waiting" and metadata.get("status") != "waiting":
        return True
    return (
        int(metadata.get("turns_since_summary", 0)) >= int(refresh_thresholds.get("turn_threshold", _SESSION_SUMMARY_TURN_THRESHOLD))
        or int(metadata.get("chars_since_summary", 0)) >= int(refresh_thresholds.get("token_growth_threshold", _SESSION_SUMMARY_CHAR_THRESHOLD))
        or int(metadata.get("tool_calls_since_summary", 0)) >= int(refresh_thresholds.get("tool_call_threshold", _SESSION_SUMMARY_TOOL_CALL_THRESHOLD))
    )


def _render_session_summary(
    *,
    session_id: str,
    agent_name: str,
    turn_id: str | None,
    messages: list[RuntimeMessage],
    open_threads: list[dict[str, str]],
    status: str,
    updated_at: str,
) -> str:
    objective = _latest_message_text(messages, role=MessageRole.USER) or "Continue the active session."
    assistant_update = _latest_message_text(messages, role=MessageRole.ASSISTANT) or "No assistant response recorded yet."
    decisions = _session_decisions(messages)
    current_state = [
        f"Session status: {status}.",
        f"Messages recorded: {len(messages)}.",
        f"Open threads: {len(open_threads)} active.",
        f"Latest assistant update: {_truncate_text(assistant_update)}",
    ]
    if open_threads:
        current_state.append(f"Most urgent thread: {_truncate_text(open_threads[0]['summary'])}")
    constraints = _session_constraints(messages, agent_name=agent_name, open_threads=open_threads)
    important_outcomes = _session_recent_outcomes(messages, open_threads=open_threads)
    next_steps = _session_next_steps(
        messages,
        status=status,
        open_threads=open_threads,
    )
    source_turn_id = turn_id or "unknown"
    return (
        "# Session Summary\n\n"
        "## Current Objective\n"
        f"- {_truncate_text(objective)}\n\n"
        "## Current State\n"
        + "".join(f"- {line}\n" for line in current_state)
        + "\n## Key Decisions\n"
        + "".join(f"- {line}\n" for line in decisions)
        + "\n## Active Constraints\n"
        + "".join(f"- {line}\n" for line in constraints)
        + "\n## Important Recent Outcomes\n"
        + "".join(f"- {line}\n" for line in important_outcomes)
        + "\n## Likely Next Steps\n"
        + "".join(f"- {line}\n" for line in next_steps)
        + "\n## Provenance\n"
        f"- session_id: {session_id}\n"
        f"- updated_at: {updated_at}\n"
        "- source_turn_ids:\n"
        f"  - {source_turn_id}\n"
    )


def _session_decisions(messages: list[RuntimeMessage]) -> list[str]:
    decisions = _collect_recent_message_texts(
        messages,
        roles=(MessageRole.NOTIFICATION, MessageRole.ASSISTANT),
        limit=3,
        include_questions=False,
    )
    return decisions or ["Continue from the latest confirmed turn output."]


def _session_constraints(
    messages: list[RuntimeMessage],
    *,
    agent_name: str,
    open_threads: list[dict[str, str]],
) -> list[str]:
    constraints = [f"Current agent: {agent_name}.", "Session continuity is tracked separately from transcript compaction."]
    constraints.extend(_recent_user_constraints(messages))
    if open_threads:
        constraints.append(f"Keep {len(open_threads)} open thread(s) in sync with follow-up turns.")
    return _dedupe_ordered(constraints)


def _session_recent_outcomes(
    messages: list[RuntimeMessage],
    *,
    open_threads: list[dict[str, str]],
) -> list[str]:
    outcomes = _collect_recent_message_texts(
        messages,
        roles=(MessageRole.NOTIFICATION, MessageRole.ASSISTANT),
        limit=3,
    )
    if open_threads:
        outcomes.append(f"Outstanding thread: {_truncate_text(open_threads[0]['summary'])}")
    return _dedupe_ordered(outcomes) or ["No assistant response recorded yet."]


def _session_next_steps(
    messages: list[RuntimeMessage],
    *,
    status: str,
    open_threads: list[dict[str, str]],
) -> list[str]:
    if open_threads:
        return _dedupe_ordered(
            [_truncate_text(thread["next_action"]) for thread in open_threads if thread.get("next_action")]
        ) or ["Resolve the active open thread before expanding scope."]
    if status == "waiting":
        return ["Wait for the blocker to clear or for new user input before continuing."]
    assistant_update = _latest_message_text(messages, role=MessageRole.ASSISTANT)
    if assistant_update.endswith("?"):
        return ["Wait for the user to answer the outstanding question."]
    return ["Continue the active objective from the latest confirmed state."]


def _collect_recent_message_texts(
    messages: list[RuntimeMessage],
    *,
    roles: tuple[MessageRole, ...],
    limit: int,
    include_questions: bool = True,
) -> list[str]:
    collected: list[str] = []
    seen: set[str] = set()
    for message in reversed(messages):
        if message.role not in roles or not message.text.strip():
            continue
        text = _truncate_text(message.text.strip())
        if not include_questions and text.endswith("?"):
            continue
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        collected.append(text)
        if len(collected) >= limit:
            break
    collected.reverse()
    return collected


def _recent_user_constraints(messages: list[RuntimeMessage]) -> list[str]:
    markers = ("prefer", "keep", "avoid", "use ", "must", "always", "never", "don't", "do not", "remember")
    constraints: list[str] = []
    for message in reversed(messages):
        if message.role != MessageRole.USER or not message.text.strip():
            continue
        text = " ".join(message.text.strip().split())
        lowered = text.lower()
        if any(marker in lowered for marker in markers):
            constraints.append(_truncate_text(text))
        if len(constraints) >= 2:
            break
    constraints.reverse()
    return constraints


def _dedupe_ordered(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(normalized)
    return deduped


def _latest_message_text(messages: list[RuntimeMessage], *, role: MessageRole) -> str:
    for message in reversed(messages):
        if message.role == role and message.text.strip():
            return message.text.strip()
    return ""


def _truncate_text(value: str, *, limit: int = 180) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _write_open_threads(path: Path, threads: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_open_threads(threads), encoding="utf-8")


def _reconcile_open_threads(
    *,
    path: Path,
    existing_threads: list[dict[str, str]],
    candidate: dict[str, str] | None,
    agent_name: str,
    prior_status: str | None,
    prompt_text: str,
) -> list[dict[str, str]]:
    owner = normalize_memory_segment(agent_name, default="agent")
    prompt_subject = _thread_subject(prompt_text) if prompt_text else None
    candidate_subject = _thread_subject_from_key(candidate["thread_key"]) if candidate is not None else None
    resolved_keys: set[str] = set()
    for thread in existing_threads:
        if thread.get("owner") != owner:
            continue
        thread_key = thread.get("thread_key", "")
        if candidate is not None:
            if (
                candidate_subject is not None
                and _thread_subject_from_key(thread_key) == candidate_subject
                and thread_key != candidate["thread_key"]
            ):
                resolved_keys.add(thread_key)
            continue
        if thread.get("status") == "waiting_user":
            resolved_keys.add(thread_key)
            continue
        if prior_status == "waiting" and thread.get("status") == "blocked":
            resolved_keys.add(thread_key)
            continue
        if prompt_subject is not None and _thread_subject_from_key(thread_key) == prompt_subject:
            resolved_keys.add(thread_key)
    threads = [thread for thread in existing_threads if thread.get("thread_key") not in resolved_keys]
    if candidate is not None:
        threads = [thread for thread in threads if thread.get("thread_key") != candidate["thread_key"]]
        threads.append(candidate)
    threads.sort(key=lambda entry: entry["thread_key"])
    _write_open_threads(path, threads)
    return threads


def _thread_subject_from_key(thread_key: str) -> str | None:
    parts = thread_key.split(":", 2)
    if len(parts) != 3:
        return None
    return parts[1] or None


def _read_open_threads(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.is_file():
        return []
    threads: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if raw_line.startswith("## Thread: "):
            if current is not None and _valid_open_thread(current):
                threads.append(current)
            current = {"thread_key": raw_line.removeprefix("## Thread: ").strip()}
            continue
        if current is None or not line.startswith("- "):
            continue
        if line.startswith("- Status: "):
            current["status"] = line.removeprefix("- Status: ").strip()
        elif line.startswith("- Owner: "):
            current["owner"] = line.removeprefix("- Owner: ").strip()
        elif line.startswith("- Summary: "):
            current["summary"] = line.removeprefix("- Summary: ").strip()
        elif line.startswith("- Next Action: "):
            current["next_action"] = line.removeprefix("- Next Action: ").strip()
        elif line.startswith("- Unblock Condition: "):
            current["unblock_condition"] = line.removeprefix("- Unblock Condition: ").strip()
    if current is not None and _valid_open_thread(current):
        threads.append(current)
    return threads


def _render_open_threads(threads: list[dict[str, str]]) -> str:
    sections = ["# Open Threads", ""]
    for thread in threads:
        sections.extend(
            [
                f"## Thread: {thread['thread_key']}",
                f"- Status: {thread['status']}",
                f"- Owner: {thread['owner']}",
                f"- Summary: {thread['summary']}",
                f"- Next Action: {thread['next_action']}",
                f"- Unblock Condition: {thread['unblock_condition']}",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def _valid_open_thread(thread: dict[str, str]) -> bool:
    required = ("thread_key", "status", "owner", "summary", "next_action")
    return all(isinstance(thread.get(field), str) and thread[field].strip() for field in required)


def _session_thread_candidate(
    *,
    messages: tuple[RuntimeMessage, ...],
    agent_name: str,
    terminal: Any,
) -> dict[str, str] | None:
    prompt_text = _primary_user_prompt_text(messages)
    assistant_text = _latest_message_text(list(messages), role=MessageRole.ASSISTANT)
    owner = normalize_memory_segment(agent_name, default="agent")
    if terminal is not None and getattr(terminal, "stop_reason", None) == "blocked":
        subject = _thread_subject(prompt_text or assistant_text)
        return {
            "thread_key": f"blocker:{subject}:{owner}",
            "status": "blocked",
            "owner": owner,
            "summary": _truncate_text(assistant_text or prompt_text or "The current turn is blocked."),
            "next_action": "Resume the session after the blocker is cleared.",
            "unblock_condition": "Receive follow-up input or clear the blocking condition.",
        }
    if assistant_text.endswith("?"):
        subject = _thread_subject(prompt_text or assistant_text)
        return {
            "thread_key": f"user_input:{subject}:{owner}",
            "status": "waiting_user",
            "owner": owner,
            "summary": _truncate_text(assistant_text),
            "next_action": "Wait for the user to answer the outstanding question.",
            "unblock_condition": "The user provides the requested information.",
        }
    return None


def _primary_user_prompt_text(messages: tuple[RuntimeMessage, ...]) -> str:
    for message in messages:
        if message.role != MessageRole.USER or not message.text.strip():
            continue
        if any(isinstance(block, TextBlock) for block in message.content):
            return message.text.strip()
    return ""


def _thread_subject(text: str) -> str:
    normalized = normalize_memory_segment(text, default="session-thread")
    parts = [segment for segment in normalized.split("-") if segment]
    if not parts:
        return "session-thread"
    return "-".join(parts[:6])


def _memory_write_receipt_payload(receipt: MemoryWriteReceipt) -> dict[str, object]:
    payload: dict[str, object] = {
        "fact_type": receipt.fact_type,
        "action": receipt.action,
        "scope": receipt.scope,
        "target_layer": receipt.target_layer,
        "namespace": receipt.namespace,
        "retention": receipt.retention,
        "merge_policy": receipt.merge_policy,
        "source_message_ids": list(receipt.source_message_ids),
        "source_roles": list(receipt.source_roles),
    }
    if receipt.title is not None:
        payload["title"] = receipt.title
    if receipt.path is not None:
        payload["path"] = str(receipt.path)
    if receipt.reason is not None:
        payload["reason"] = receipt.reason
    if receipt.source_pathway is not None:
        payload["source_pathway"] = receipt.source_pathway
    if receipt.conflict_key is not None:
        payload["conflict_key"] = receipt.conflict_key
    if receipt.contested:
        payload["contested"] = True
    if receipt.supersedes:
        payload["supersedes"] = list(receipt.supersedes)
    return payload


__all__ = [
    "default_session_summary_thresholds",
    "ensure_session_artifacts",
    "record_session_compaction",
    "record_session_memory_deltas",
    "refresh_session_artifacts",
    "serialize_write_receipts",
    "update_session_status",
]
