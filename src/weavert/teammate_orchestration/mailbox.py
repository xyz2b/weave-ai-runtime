from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .models import (
    MailboxEnvelope,
    MailboxTerminalState,
    TeammateStateSnapshot,
)


@dataclass(frozen=True, slots=True)
class TeammateMailboxPaths:
    root: Path
    inbox: Path
    claimed: Path
    done: Path
    failed: Path
    retry: Path
    state: Path


class TeammateMailboxStore(Protocol):
    @property
    def root(self) -> Path: ...

    def scan_teammates(self) -> tuple[tuple[str, str], ...]: ...

    def ensure_paths(self, team_id: str, teammate_id: str) -> TeammateMailboxPaths: ...

    def read_state(self, team_id: str, teammate_id: str) -> TeammateStateSnapshot | None: ...

    def write_state(self, snapshot: TeammateStateSnapshot) -> TeammateStateSnapshot: ...

    def publish(self, envelope: MailboxEnvelope) -> MailboxEnvelope: ...

    def claim_next(
        self,
        team_id: str,
        teammate_id: str,
        *,
        claimer_identity: str,
        claim_lease_ms: int | None = None,
        now: datetime | None = None,
    ) -> MailboxEnvelope | None: ...

    def update_claim(self, envelope: MailboxEnvelope) -> MailboxEnvelope: ...

    def heartbeat(
        self,
        team_id: str,
        teammate_id: str,
        *,
        message_id: str,
        claim_id: str,
        now: datetime | None = None,
    ) -> MailboxEnvelope: ...

    def list_claimed(self, team_id: str, teammate_id: str) -> tuple[MailboxEnvelope, ...]: ...

    def has_pending_inbox(self, team_id: str, teammate_id: str) -> bool: ...

    def delete_teammate(self, team_id: str, teammate_id: str) -> None: ...

    def delete_team(self, team_id: str) -> None: ...

    def complete_done(
        self,
        envelope: MailboxEnvelope,
        *,
        reason: str | None = None,
    ) -> MailboxEnvelope: ...

    def fail_or_retry(
        self,
        envelope: MailboxEnvelope,
        *,
        reason: str,
        retry_max_attempts: int | None = None,
    ) -> tuple[MailboxEnvelope, MailboxEnvelope | None]: ...

    def stale_claim(
        self,
        envelope: MailboxEnvelope,
        *,
        active_run_linked: bool,
        waiting_permission: bool,
        now: datetime | None = None,
    ) -> bool: ...


class InMemoryTeammateMailbox:
    def __init__(
        self,
        *,
        default_claim_lease_ms: int,
        default_retry_max_attempts: int,
        retry_backoff_ms: int = 0,
        root: Path | None = None,
    ) -> None:
        self._root = (root or (Path.cwd() / ".weavert-in-memory" / "teammates")).resolve()
        self._default_claim_lease_ms = default_claim_lease_ms
        self._default_retry_max_attempts = default_retry_max_attempts
        self._retry_backoff_ms = max(retry_backoff_ms, 0)
        self._states: dict[tuple[str, str], TeammateStateSnapshot] = {}
        self._inbox: dict[tuple[str, str], dict[str, MailboxEnvelope]] = {}
        self._claimed: dict[tuple[str, str], dict[tuple[str, str], MailboxEnvelope]] = {}
        self._done: dict[tuple[str, str], dict[tuple[str, str], MailboxEnvelope]] = {}
        self._failed: dict[tuple[str, str], dict[tuple[str, str], MailboxEnvelope]] = {}
        self._retry: dict[tuple[str, str], dict[tuple[str, str], MailboxEnvelope]] = {}

    @property
    def root(self) -> Path:
        return self._root

    def scan_teammates(self) -> tuple[tuple[str, str], ...]:
        keys = set(self._states)
        keys.update(self._inbox)
        keys.update(self._claimed)
        keys.update(self._done)
        keys.update(self._failed)
        keys.update(self._retry)
        return tuple(sorted(keys))

    def ensure_paths(self, team_id: str, teammate_id: str) -> TeammateMailboxPaths:
        root = self._root / "teams" / team_id / "teammates" / teammate_id
        return TeammateMailboxPaths(
            root=root,
            inbox=root / "inbox",
            claimed=root / "claimed",
            done=root / "done",
            failed=root / "failed",
            retry=root / "retry",
            state=root / "state.json",
        )

    def read_state(self, team_id: str, teammate_id: str) -> TeammateStateSnapshot | None:
        return self._states.get((str(team_id), str(teammate_id)))

    def write_state(self, snapshot: TeammateStateSnapshot) -> TeammateStateSnapshot:
        self._states[(snapshot.team_id, snapshot.teammate_id)] = snapshot
        return snapshot

    def publish(self, envelope: MailboxEnvelope) -> MailboxEnvelope:
        inbox = self._inbox.setdefault((envelope.team_id, envelope.teammate_id), {})
        if envelope.message_id in inbox:
            raise FileExistsError(envelope.message_id)
        inbox[envelope.message_id] = envelope
        return envelope

    def claim_next(
        self,
        team_id: str,
        teammate_id: str,
        *,
        claimer_identity: str,
        claim_lease_ms: int | None = None,
        now: datetime | None = None,
    ) -> MailboxEnvelope | None:
        key = (str(team_id), str(teammate_id))
        inbox = self._inbox.setdefault(key, {})
        timestamp = now or datetime.now(timezone.utc)
        for message_id in sorted(inbox):
            envelope = inbox[message_id]
            if not envelope.retry_ready(timestamp):
                continue
            claim_id = uuid4().hex
            claimed = envelope.with_claim(
                claim_id=claim_id,
                claimer_identity=claimer_identity,
                claim_lease_ms=claim_lease_ms or envelope.claim_lease_ms or self._default_claim_lease_ms,
                claimed_at=timestamp,
            )
            del inbox[message_id]
            self._claimed.setdefault(key, {})[(claimed.message_id, claim_id)] = claimed
            return claimed
        return None

    def update_claim(self, envelope: MailboxEnvelope) -> MailboxEnvelope:
        key = (envelope.team_id, envelope.teammate_id)
        claim_key = self._claim_key(envelope.message_id, envelope.claim_id)
        claims = self._claimed.setdefault(key, {})
        if claim_key not in claims:
            raise FileNotFoundError(
                f"No claimed envelope found for {envelope.team_id}/{envelope.teammate_id}:{envelope.message_id}"
            )
        claims[claim_key] = envelope
        return envelope

    def heartbeat(
        self,
        team_id: str,
        teammate_id: str,
        *,
        message_id: str,
        claim_id: str,
        now: datetime | None = None,
    ) -> MailboxEnvelope:
        envelope = self.read_claim(team_id, teammate_id, message_id=message_id, claim_id=claim_id)
        return self.update_claim(envelope.with_heartbeat(now))

    def read_claim(
        self,
        team_id: str,
        teammate_id: str,
        *,
        message_id: str,
        claim_id: str | None,
    ) -> MailboxEnvelope:
        claims = self._claimed.setdefault((str(team_id), str(teammate_id)), {})
        if claim_id is not None:
            envelope = claims.get((str(message_id), str(claim_id)))
            if envelope is None:
                raise FileNotFoundError(
                    f"No claimed envelope found for {team_id}/{teammate_id}:{message_id}"
                )
            return envelope
        for candidate_key in sorted(claims):
            if candidate_key[0] == str(message_id):
                return claims[candidate_key]
        raise FileNotFoundError(f"No claimed envelope found for {team_id}/{teammate_id}:{message_id}")

    def list_claimed(self, team_id: str, teammate_id: str) -> tuple[MailboxEnvelope, ...]:
        claims = self._claimed.setdefault((str(team_id), str(teammate_id)), {})
        return tuple(
            claims[key]
            for key in sorted(claims, key=lambda item: (item[0], item[1]))
        )

    def has_pending_inbox(self, team_id: str, teammate_id: str) -> bool:
        return bool(self._inbox.get((str(team_id), str(teammate_id)), {}))

    def delete_teammate(self, team_id: str, teammate_id: str) -> None:
        key = (str(team_id), str(teammate_id))
        self._states.pop(key, None)
        self._inbox.pop(key, None)
        self._claimed.pop(key, None)
        self._done.pop(key, None)
        self._failed.pop(key, None)
        self._retry.pop(key, None)

    def delete_team(self, team_id: str) -> None:
        normalized_team_id = str(team_id)
        for key in tuple(self.scan_teammates()):
            if key[0] == normalized_team_id:
                self.delete_teammate(*key)

    def complete_done(
        self,
        envelope: MailboxEnvelope,
        *,
        reason: str | None = None,
    ) -> MailboxEnvelope:
        terminal = envelope.with_terminal(MailboxTerminalState.DONE, reason=reason)
        return self._move_claim_to_terminal(terminal, bucket=MailboxTerminalState.DONE)

    def fail_or_retry(
        self,
        envelope: MailboxEnvelope,
        *,
        reason: str,
        retry_max_attempts: int | None = None,
    ) -> tuple[MailboxEnvelope, MailboxEnvelope | None]:
        ceiling = retry_max_attempts or envelope.retry_max_attempts or self._default_retry_max_attempts
        if envelope.attempt >= ceiling:
            terminal = envelope.with_terminal(MailboxTerminalState.FAILED, reason=reason)
            return self._move_claim_to_terminal(terminal, bucket=MailboxTerminalState.FAILED), None

        retry_archive = envelope.with_terminal(MailboxTerminalState.RETRY, reason=reason)
        archived = self._move_claim_to_terminal(retry_archive, bucket=MailboxTerminalState.RETRY)
        next_retry_after = None
        if self._retry_backoff_ms > 0:
            next_retry_after = datetime.utcnow().replace(tzinfo=archived.created_at.tzinfo) + timedelta(
                milliseconds=self._retry_backoff_ms
            )
        requeued = archived.for_retry(reason=reason, next_retry_after=next_retry_after)
        self.publish(requeued)
        return archived, requeued

    def stale_claim(
        self,
        envelope: MailboxEnvelope,
        *,
        active_run_linked: bool,
        waiting_permission: bool,
        now: datetime | None = None,
    ) -> bool:
        if envelope.terminal_state is not None:
            return False
        if waiting_permission or active_run_linked:
            return False
        return envelope.lease_expired(now)

    def _move_claim_to_terminal(
        self,
        envelope: MailboxEnvelope,
        *,
        bucket: MailboxTerminalState,
    ) -> MailboxEnvelope:
        key = (envelope.team_id, envelope.teammate_id)
        claim_key = self._claim_key(envelope.message_id, envelope.claim_id)
        claims = self._claimed.setdefault(key, {})
        if claim_key not in claims:
            raise FileNotFoundError(
                f"No claimed envelope found for {envelope.team_id}/{envelope.teammate_id}:{envelope.message_id}"
            )
        del claims[claim_key]
        target = {
            MailboxTerminalState.DONE: self._done,
            MailboxTerminalState.FAILED: self._failed,
            MailboxTerminalState.RETRY: self._retry,
        }[bucket]
        target.setdefault(key, {})[claim_key] = envelope
        return envelope

    @staticmethod
    def _claim_key(message_id: str, claim_id: str | None) -> tuple[str, str]:
        if claim_id is None:
            raise FileNotFoundError(f"No claimed envelope found for {message_id}")
        return str(message_id), str(claim_id)


class FileBackedTeammateMailbox:
    def __init__(
        self,
        root: Path,
        *,
        default_claim_lease_ms: int,
        default_retry_max_attempts: int,
        retry_backoff_ms: int = 0,
    ) -> None:
        self._root = Path(root).resolve()
        self._default_claim_lease_ms = default_claim_lease_ms
        self._default_retry_max_attempts = default_retry_max_attempts
        self._retry_backoff_ms = max(retry_backoff_ms, 0)

    @property
    def root(self) -> Path:
        return self._root

    def scan_teammates(self) -> tuple[tuple[str, str], ...]:
        teams_root = self._root / "teams"
        if not teams_root.exists():
            return ()
        discovered: list[tuple[str, str]] = []
        for team_dir in sorted(path for path in teams_root.iterdir() if path.is_dir()):
            teammates_dir = team_dir / "teammates"
            if not teammates_dir.exists():
                continue
            for teammate_dir in sorted(path for path in teammates_dir.iterdir() if path.is_dir()):
                discovered.append((team_dir.name, teammate_dir.name))
        return tuple(discovered)

    def ensure_paths(self, team_id: str, teammate_id: str) -> TeammateMailboxPaths:
        root = self._root / "teams" / team_id / "teammates" / teammate_id
        inbox = root / "inbox"
        claimed = root / "claimed"
        done = root / "done"
        failed = root / "failed"
        retry = root / "retry"
        for directory in (inbox, claimed, done, failed, retry):
            directory.mkdir(parents=True, exist_ok=True)
        return TeammateMailboxPaths(
            root=root,
            inbox=inbox,
            claimed=claimed,
            done=done,
            failed=failed,
            retry=retry,
            state=root / "state.json",
        )

    def read_state(self, team_id: str, teammate_id: str) -> TeammateStateSnapshot | None:
        paths = self.ensure_paths(team_id, teammate_id)
        if not paths.state.exists():
            return None
        return TeammateStateSnapshot.from_dict(_read_json(paths.state))

    def write_state(self, snapshot: TeammateStateSnapshot) -> TeammateStateSnapshot:
        paths = self.ensure_paths(snapshot.team_id, snapshot.teammate_id)
        _atomic_write_json(paths.state, snapshot.to_dict(), replace_existing=True)
        return snapshot

    def publish(self, envelope: MailboxEnvelope) -> MailboxEnvelope:
        paths = self.ensure_paths(envelope.team_id, envelope.teammate_id)
        target = paths.inbox / f"{envelope.message_id}.json"
        payload = envelope.to_dict()
        temp = paths.inbox / f".tmp-{envelope.message_id}-{uuid4().hex}.json"
        _atomic_write_json(temp, payload, replace_existing=True)
        if target.exists():
            raise FileExistsError(target)
        temp.replace(target)
        return envelope

    def claim_next(
        self,
        team_id: str,
        teammate_id: str,
        *,
        claimer_identity: str,
        claim_lease_ms: int | None = None,
        now: datetime | None = None,
    ) -> MailboxEnvelope | None:
        paths = self.ensure_paths(team_id, teammate_id)
        timestamp = now or datetime.now(timezone.utc)
        for source in sorted(paths.inbox.glob("*.json")):
            try:
                envelope = MailboxEnvelope.from_dict(_read_json(source))
            except FileNotFoundError:
                continue
            if not envelope.retry_ready(timestamp):
                continue
            claim_id = uuid4().hex
            destination = paths.claimed / f"{envelope.message_id}--{claim_id}.json"
            try:
                source.replace(destination)
            except FileNotFoundError:
                continue
            claimed = envelope.with_claim(
                claim_id=claim_id,
                claimer_identity=claimer_identity,
                claim_lease_ms=claim_lease_ms or envelope.claim_lease_ms or self._default_claim_lease_ms,
                claimed_at=timestamp,
            )
            _atomic_write_json(destination, claimed.to_dict(), replace_existing=True)
            return claimed
        return None

    def update_claim(self, envelope: MailboxEnvelope) -> MailboxEnvelope:
        path = self.claim_path(
            envelope.team_id,
            envelope.teammate_id,
            message_id=envelope.message_id,
            claim_id=envelope.claim_id,
        )
        _atomic_write_json(path, envelope.to_dict(), replace_existing=True)
        return envelope

    def heartbeat(
        self,
        team_id: str,
        teammate_id: str,
        *,
        message_id: str,
        claim_id: str,
        now: datetime | None = None,
    ) -> MailboxEnvelope:
        envelope = self.read_claim(team_id, teammate_id, message_id=message_id, claim_id=claim_id)
        updated = envelope.with_heartbeat(now)
        return self.update_claim(updated)

    def read_claim(
        self,
        team_id: str,
        teammate_id: str,
        *,
        message_id: str,
        claim_id: str | None,
    ) -> MailboxEnvelope:
        path = self.claim_path(team_id, teammate_id, message_id=message_id, claim_id=claim_id)
        return MailboxEnvelope.from_dict(_read_json(path))

    def claim_path(
        self,
        team_id: str,
        teammate_id: str,
        *,
        message_id: str,
        claim_id: str | None,
    ) -> Path:
        paths = self.ensure_paths(team_id, teammate_id)
        if claim_id:
            candidate = paths.claimed / f"{message_id}--{claim_id}.json"
            if candidate.exists():
                return candidate
        matches = sorted(paths.claimed.glob(f"{message_id}--*.json"))
        if not matches:
            raise FileNotFoundError(f"No claimed envelope found for {team_id}/{teammate_id}:{message_id}")
        return matches[0]

    def list_claimed(self, team_id: str, teammate_id: str) -> tuple[MailboxEnvelope, ...]:
        paths = self.ensure_paths(team_id, teammate_id)
        return tuple(
            MailboxEnvelope.from_dict(_read_json(path))
            for path in sorted(paths.claimed.glob("*.json"))
        )

    def has_pending_inbox(self, team_id: str, teammate_id: str) -> bool:
        paths = self.ensure_paths(team_id, teammate_id)
        return any(paths.inbox.glob("*.json"))

    def delete_teammate(self, team_id: str, teammate_id: str) -> None:
        shutil.rmtree(self.ensure_paths(team_id, teammate_id).root, ignore_errors=True)

    def delete_team(self, team_id: str) -> None:
        shutil.rmtree(self._root / "teams" / team_id, ignore_errors=True)

    def complete_done(
        self,
        envelope: MailboxEnvelope,
        *,
        reason: str | None = None,
    ) -> MailboxEnvelope:
        terminal = envelope.with_terminal(MailboxTerminalState.DONE, reason=reason)
        return self._move_claim_to_terminal(terminal, bucket=MailboxTerminalState.DONE)

    def fail_or_retry(
        self,
        envelope: MailboxEnvelope,
        *,
        reason: str,
        retry_max_attempts: int | None = None,
    ) -> tuple[MailboxEnvelope, MailboxEnvelope | None]:
        ceiling = retry_max_attempts or envelope.retry_max_attempts or self._default_retry_max_attempts
        if envelope.attempt >= ceiling:
            terminal = envelope.with_terminal(MailboxTerminalState.FAILED, reason=reason)
            return self._move_claim_to_terminal(terminal, bucket=MailboxTerminalState.FAILED), None

        retry_archive = envelope.with_terminal(MailboxTerminalState.RETRY, reason=reason)
        archived = self._move_claim_to_terminal(retry_archive, bucket=MailboxTerminalState.RETRY)
        next_retry_after = None
        if self._retry_backoff_ms > 0:
            next_retry_after = datetime.utcnow().replace(tzinfo=archived.created_at.tzinfo) + timedelta(
                milliseconds=self._retry_backoff_ms
            )
        requeued = archived.for_retry(reason=reason, next_retry_after=next_retry_after)
        self.publish(requeued)
        return archived, requeued

    def stale_claim(
        self,
        envelope: MailboxEnvelope,
        *,
        active_run_linked: bool,
        waiting_permission: bool,
        now: datetime | None = None,
    ) -> bool:
        if envelope.terminal_state is not None:
            return False
        if waiting_permission or active_run_linked:
            return False
        return envelope.lease_expired(now)

    def _move_claim_to_terminal(
        self,
        envelope: MailboxEnvelope,
        *,
        bucket: MailboxTerminalState,
    ) -> MailboxEnvelope:
        source = self.claim_path(
            envelope.team_id,
            envelope.teammate_id,
            message_id=envelope.message_id,
            claim_id=envelope.claim_id,
        )
        _atomic_write_json(source, envelope.to_dict(), replace_existing=True)
        paths = self.ensure_paths(envelope.team_id, envelope.teammate_id)
        target_root = {
            MailboxTerminalState.DONE: paths.done,
            MailboxTerminalState.FAILED: paths.failed,
            MailboxTerminalState.RETRY: paths.retry,
        }[bucket]
        target = target_root / source.name
        source.replace(target)
        return envelope


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(
    path: Path,
    payload: dict[str, object],
    *,
    replace_existing: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path if path.name.startswith(".tmp-") else path.with_name(f".tmp-{path.name}-{uuid4().hex}")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if path == temp:
        return
    if path.exists() and not replace_existing:
        temp.unlink(missing_ok=True)
        raise FileExistsError(path)
    temp.replace(path)


__all__ = [
    "FileBackedTeammateMailbox",
    "InMemoryTeammateMailbox",
    "TeammateMailboxStore",
    "TeammateMailboxPaths",
]
