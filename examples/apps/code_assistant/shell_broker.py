from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BROKER_READY_TIMEOUT_SECONDS = 5.0
_BROKER_POLL_INTERVAL_SECONDS = 0.05
_BROKER_IDLE_SHUTDOWN_SECONDS = 1.0
_SESSION_OUTPUT_MAX_CHARS = 12_000
_SESSION_OUTPUT_MAX_CHUNKS = 256
_READ_CHUNK_SIZE = 512
_STOP_GRACE_SECONDS = 0.5
_PREVIEW_MAX_CHARS = 600
_PREVIEW_MAX_LINES = 12
_UNIX_SOCKET_PATH_LIMIT = 96
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def shell_state_root(workspace_root: Path) -> Path:
    return workspace_root / ".weavert" / "shell"


def broker_metadata_path(workspace_root: Path) -> Path:
    return shell_state_root(workspace_root) / "broker.json"


def broker_socket_path(workspace_root: Path) -> Path:
    return shell_state_root(workspace_root) / "broker.sock"


def session_sidecar_dir(workspace_root: Path, shell_session_id: str) -> Path:
    return shell_state_root(workspace_root) / "sessions" / shell_session_id


def background_sidecar_dir(workspace_root: Path, job_id: str) -> Path:
    return shell_state_root(workspace_root) / "background" / job_id


def list_shell_sidecars(workspace_root: Path) -> tuple[dict[str, Any], ...]:
    state_root = shell_state_root(workspace_root)
    if not state_root.exists():
        return ()
    entries: list[dict[str, Any]] = []
    for path in sorted(state_root.glob("**/session.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload.setdefault("sidecar_dir", str(path.parent))
            payload.setdefault("metadata_path", str(path))
            entries.append(payload)
    entries.sort(key=lambda item: (str(item.get("kind") or ""), str(item.get("entry_id") or "")))
    return tuple(entries)


async def ensure_shell_broker(workspace_root: Path) -> dict[str, Any]:
    metadata = _read_broker_metadata(workspace_root)
    if metadata is not None:
        try:
            await broker_request(workspace_root, {"op": "ping"}, ensure=False)
            return metadata
        except Exception:
            pass
    state_root = shell_state_root(workspace_root)
    state_root.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "examples.apps.code_assistant.shell_broker",
            "--workspace-root",
            str(workspace_root),
        ],
        cwd=str(_PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + _BROKER_READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        metadata = _read_broker_metadata(workspace_root)
        if metadata is not None:
            try:
                await broker_request(workspace_root, {"op": "ping"}, ensure=False)
                return metadata
            except Exception as exc:
                last_error = exc
        await asyncio.sleep(_BROKER_POLL_INTERVAL_SECONDS)
    if last_error is not None:
        raise RuntimeError(f"Shell broker failed to start: {last_error}") from last_error
    raise RuntimeError("Shell broker failed to start.")


async def stop_shell_broker(workspace_root: Path) -> None:
    metadata = _read_broker_metadata(workspace_root)
    if metadata is None:
        return
    try:
        await broker_request(workspace_root, {"op": "shutdown"}, ensure=False)
    except Exception:
        pid = metadata.get("pid")
        if isinstance(pid, int) and pid > 0:
            _terminate_pid(pid)
    await asyncio.sleep(0.05)
    _cleanup_stale_broker_files(workspace_root)


async def broker_request(
    workspace_root: Path,
    payload: dict[str, Any],
    *,
    ensure: bool = True,
) -> dict[str, Any]:
    metadata = await ensure_shell_broker(workspace_root) if ensure else _read_broker_metadata(workspace_root)
    if metadata is None:
        raise RuntimeError("Shell broker metadata is unavailable.")
    transport = str(metadata.get("transport") or "unix")
    if transport == "tcp":
        host = str(metadata.get("host") or "127.0.0.1")
        port = int(metadata.get("port") or 0)
        reader, writer = await asyncio.open_connection(host, port)
    else:
        socket_path = str(metadata.get("socket_path") or broker_socket_path(workspace_root))
        reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))
        await writer.drain()
        raw = await reader.readline()
    finally:
        writer.close()
        await writer.wait_closed()
    if not raw:
        raise RuntimeError("Shell broker closed the connection without a response.")
    response = json.loads(raw.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("Shell broker returned an invalid response.")
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or "Shell broker request failed."))
    return response


def broker_request_sync(workspace_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    metadata = _read_broker_metadata(workspace_root)
    if metadata is None:
        raise RuntimeError("Shell broker metadata is unavailable.")
    transport = str(metadata.get("transport") or "unix")
    encoded = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
    if transport == "tcp":
        host = str(metadata.get("host") or "127.0.0.1")
        port = int(metadata.get("port") or 0)
        with socket.create_connection((host, port), timeout=0.5) as connection:
            connection.sendall(encoded)
            with connection.makefile("rb") as handle:
                raw = handle.readline()
    else:
        socket_path = str(metadata.get("socket_path") or broker_socket_path(workspace_root))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            connection.connect(socket_path)
            connection.sendall(encoded)
            with connection.makefile("rb") as handle:
                raw = handle.readline()
    if not raw:
        raise RuntimeError("Shell broker closed the connection without a response.")
    response = json.loads(raw.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("Shell broker returned an invalid response.")
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or "Shell broker request failed."))
    return response


def _read_broker_metadata(workspace_root: Path) -> dict[str, Any] | None:
    path = broker_metadata_path(workspace_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cleanup_stale_broker_files(workspace_root: Path) -> None:
    metadata_path = broker_metadata_path(workspace_root)
    socket_path = broker_socket_path(workspace_root)
    for path in (metadata_path, socket_path):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _terminate_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True, slots=True)
class ShellOutputChunk:
    sequence: int
    stream: str
    text: str


@dataclass(slots=True)
class BrokerEntry:
    entry_id: str
    kind: str
    command: str
    shell: str
    cwd: Path
    workspace_root: Path
    session_mode: str
    session_profile: str
    terminal_mode: str
    shell_session_id: str | None
    job_id: str | None
    description: str | None
    classification: str
    sidecar_dir: Path
    metadata_path: Path
    output_path: Path
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "running"
    recovery_state: str = "attached"
    exit_code: int | None = None
    pid: int | None = None
    stop_requested: bool = False
    interrupt_requested: bool = False
    live_handle: bool = False
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    output_chunks: list[ShellOutputChunk] = field(default_factory=list)
    next_sequence: int = 1
    output_sequence: int = 0
    recent_output: str = ""
    recent_stream: str | None = None
    process: asyncio.subprocess.Process | subprocess.Popen[bytes] | None = None
    stdin_writer: asyncio.StreamWriter | None = None
    master_fd: int | None = None
    reader_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    wait_task: asyncio.Task[None] | None = None


class ShellBroker:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.state_root = shell_state_root(self.workspace_root)
        self.metadata_path = broker_metadata_path(self.workspace_root)
        self.default_socket_path = broker_socket_path(self.workspace_root)
        self.transport = "unix"
        self.entries: dict[str, BrokerEntry] = {}
        self.server: asyncio.AbstractServer | None = None
        self._shutdown_event = asyncio.Event()
        self._idle_task: asyncio.Task[None] | None = None

    async def serve(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._load_existing_entries()
        self.server = await self._start_server()
        self._persist_broker_metadata()
        self._schedule_idle_shutdown()
        await self._shutdown_event.wait()
        await self._shutdown()

    async def _start_server(self) -> asyncio.AbstractServer:
        if os.name == "nt" or len(str(self.default_socket_path)) > _UNIX_SOCKET_PATH_LIMIT:
            self.transport = "tcp"
            server = await asyncio.start_server(self._handle_client, host="127.0.0.1", port=0)
        else:
            self.transport = "unix"
            if self.default_socket_path.exists():
                self.default_socket_path.unlink()
            server = await asyncio.start_unix_server(self._handle_client, path=str(self.default_socket_path))
        return server

    def _persist_broker_metadata(self) -> None:
        payload: dict[str, Any] = {
            "pid": os.getpid(),
            "workspace_root": str(self.workspace_root),
            "state_root": str(self.state_root),
            "transport": self.transport,
            "started_at": time.time(),
        }
        sockets = self.server.sockets if self.server is not None else ()
        if self.transport == "tcp" and sockets:
            host, port = sockets[0].getsockname()[:2]
            payload["host"] = host
            payload["port"] = port
        else:
            payload["socket_path"] = str(self.default_socket_path)
        self.metadata_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        response: dict[str, Any]
        try:
            raw = await reader.readline()
            if not raw:
                response = {"ok": False, "error": "Empty request."}
            else:
                payload = json.loads(raw.decode("utf-8"))
                response = await self._dispatch(payload if isinstance(payload, dict) else {})
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        writer.write((json.dumps(response, ensure_ascii=True) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        op = str(payload.get("op") or "").strip()
        if op == "ping":
            return {"ok": True, "broker_pid": os.getpid()}
        if op == "shutdown":
            self._shutdown_event.set()
            return {"ok": True}
        if op == "list":
            return {"ok": True, "entries": [self._entry_snapshot(entry) for entry in self.entries.values()]}
        if op == "describe":
            entry = self._entry_for_request(payload)
            return {"ok": True, "entry": self._entry_snapshot(entry)}
        if op == "read":
            entry = self._entry_for_request(payload)
            after_sequence = int(payload.get("after_sequence") or 0)
            max_output_chars = int(payload.get("max_output_chars") or _SESSION_OUTPUT_MAX_CHARS)
            session_output, latest_sequence = self._output_since_sequence(
                entry,
                after_sequence=after_sequence,
                max_output_chars=max_output_chars,
            )
            return {
                "ok": True,
                "entry": self._entry_snapshot(entry),
                "session_output": session_output,
                "session_output_sequence": latest_sequence,
                "session_output_complete": entry.status != "running",
            }
        if op == "start":
            entry = await self._start_entry(payload)
            return {"ok": True, "entry": self._entry_snapshot(entry)}
        if op == "send":
            entry = self._entry_for_request(payload)
            await self._send(entry, stdin=str(payload.get("stdin") or ""))
            return {"ok": True, "entry": self._entry_snapshot(entry)}
        if op == "interrupt":
            entry = self._entry_for_request(payload)
            await self._interrupt(entry)
            return {"ok": True, "entry": self._entry_snapshot(entry)}
        if op == "stop":
            entry = self._entry_for_request(payload)
            await self._stop(entry)
            return {"ok": True, "entry": self._entry_snapshot(entry)}
        raise RuntimeError(f"Unsupported broker operation: {op}")

    def _entry_for_request(self, payload: dict[str, Any]) -> BrokerEntry:
        entry_id = str(payload.get("entry_id") or payload.get("shell_session_id") or payload.get("job_id") or "").strip()
        if not entry_id:
            raise RuntimeError("entry_id is required.")
        entry = self.entries.get(entry_id)
        if entry is None:
            raise RuntimeError(f"Unknown shell broker entry: {entry_id}")
        return entry

    async def _start_entry(self, payload: dict[str, Any]) -> BrokerEntry:
        kind = str(payload.get("kind") or "").strip()
        if kind not in {"shell_session", "background_shell"}:
            raise RuntimeError(f"Unsupported shell broker kind: {kind}")
        entry_id = str(payload.get("entry_id") or "").strip()
        if not entry_id:
            raise RuntimeError("entry_id is required.")
        if entry_id in self.entries and self.entries[entry_id].status == "running":
            raise RuntimeError(f"Shell broker entry is already running: {entry_id}")
        command = str(payload.get("command") or "").strip()
        if not command:
            raise RuntimeError("command is required.")
        shell = str(payload.get("shell") or "bash")
        cwd = Path(str(payload.get("cwd") or self.workspace_root)).resolve()
        session_profile = str(payload.get("session_profile") or "line_session")
        terminal_mode = str(payload.get("terminal_mode") or ("pty" if session_profile == "pty_session" else "line"))
        shell_session_id = str(payload.get("shell_session_id") or "").strip() or None
        job_id = str(payload.get("job_id") or "").strip() or None
        description = str(payload.get("description") or "").strip() or None
        classification = str(payload.get("classification") or "other")
        sidecar_dir = (
            session_sidecar_dir(self.workspace_root, shell_session_id or entry_id)
            if kind == "shell_session"
            else background_sidecar_dir(self.workspace_root, job_id or entry_id)
        )
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = sidecar_dir / "session.json"
        output_path = sidecar_dir / "output.jsonl"
        if not output_path.exists():
            output_path.write_text("", encoding="utf-8")
        entry = BrokerEntry(
            entry_id=entry_id,
            kind=kind,
            command=command,
            shell=shell,
            cwd=cwd,
            workspace_root=self.workspace_root,
            session_mode="session" if kind == "shell_session" else "background",
            session_profile=session_profile,
            terminal_mode=terminal_mode,
            shell_session_id=shell_session_id,
            job_id=job_id,
            description=description,
            classification=classification,
            sidecar_dir=sidecar_dir,
            metadata_path=metadata_path,
            output_path=output_path,
            live_handle=True,
        )
        self.entries[entry_id] = entry
        if session_profile == "pty_session":
            self._start_pty_entry(entry)
        else:
            await self._start_line_entry(entry)
        self._persist_entry(entry)
        self._schedule_idle_shutdown()
        return entry

    async def _start_line_entry(self, entry: BrokerEntry) -> None:
        wants_stdin = entry.kind == "shell_session"
        if entry.shell == "powershell":
            process = await asyncio.create_subprocess_exec(
                "pwsh",
                "-NoProfile",
                "-Command",
                entry.command,
                cwd=str(entry.cwd),
                stdin=asyncio.subprocess.PIPE if wants_stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        else:
            process = await asyncio.create_subprocess_shell(
                entry.command,
                cwd=str(entry.cwd),
                stdin=asyncio.subprocess.PIPE if wants_stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        entry.process = process
        entry.pid = process.pid
        entry.status = "running"
        entry.recovery_state = "attached"
        entry.reader_tasks = [
            asyncio.create_task(self._capture_stream(entry, process.stdout, stream="stdout")),
            asyncio.create_task(self._capture_stream(entry, process.stderr, stream="stderr")),
        ]
        entry.wait_task = asyncio.create_task(self._watch_entry(entry))

    def _start_pty_entry(self, entry: BrokerEntry) -> None:
        if os.name == "nt":
            raise RuntimeError("PTY sessions are unsupported on this platform.")
        import pty

        master_fd, slave_fd = pty.openpty()
        argv = _shell_command_argv(entry.shell, entry.command)
        process = subprocess.Popen(
            argv,
            cwd=str(entry.cwd),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        entry.process = process
        entry.master_fd = master_fd
        entry.pid = process.pid
        entry.status = "running"
        entry.recovery_state = "attached"
        entry.reader_tasks = [asyncio.create_task(self._capture_pty(entry))]
        entry.wait_task = asyncio.create_task(self._watch_entry(entry))

    async def _capture_stream(
        self,
        entry: BrokerEntry,
        reader: asyncio.StreamReader | None,
        *,
        stream: str,
    ) -> None:
        if reader is None:
            return
        while True:
            chunk = await reader.read(_READ_CHUNK_SIZE)
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace")
            if text:
                self._append_output(entry, stream=stream, text=text)

    async def _capture_pty(self, entry: BrokerEntry) -> None:
        if entry.master_fd is None:
            return
        loop = asyncio.get_running_loop()
        while True:
            chunk = await loop.run_in_executor(None, os.read, entry.master_fd, _READ_CHUNK_SIZE)
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace")
            if text:
                self._append_output(entry, stream="pty", text=text)

    def _append_output(self, entry: BrokerEntry, *, stream: str, text: str) -> None:
        if stream in {"stdout", "pty"}:
            entry.stdout_buffer = _append_capped_text(entry.stdout_buffer, text)
        if stream == "stderr":
            entry.stderr_buffer = _append_capped_text(entry.stderr_buffer, text)
        chunk = ShellOutputChunk(sequence=entry.next_sequence, stream=stream, text=text)
        entry.output_chunks.append(chunk)
        entry.next_sequence += 1
        entry.output_sequence = chunk.sequence
        entry.recent_output = text
        entry.recent_stream = stream
        if len(entry.output_chunks) > _SESSION_OUTPUT_MAX_CHUNKS:
            entry.output_chunks = entry.output_chunks[-_SESSION_OUTPUT_MAX_CHUNKS:]
        with entry.output_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"sequence": chunk.sequence, "stream": chunk.stream, "text": chunk.text},
                    ensure_ascii=True,
                )
            )
            handle.write("\n")
        self._persist_entry(entry)

    async def _watch_entry(self, entry: BrokerEntry) -> None:
        try:
            returncode = await self._wait_for_process(entry)
            if entry.reader_tasks:
                await asyncio.gather(*entry.reader_tasks, return_exceptions=True)
        finally:
            entry.exit_code = returncode if "returncode" in locals() else entry.exit_code
            if entry.stop_requested:
                entry.status = "stopped"
            elif entry.interrupt_requested:
                entry.status = "interrupted"
            elif entry.exit_code == 0:
                entry.status = "completed"
            else:
                entry.status = "command_failed"
            entry.recovery_state = "completed"
            entry.live_handle = False
            if entry.master_fd is not None:
                try:
                    os.close(entry.master_fd)
                except OSError:
                    pass
                entry.master_fd = None
            self._persist_entry(entry)
            self._schedule_idle_shutdown()

    async def _wait_for_process(self, entry: BrokerEntry) -> int:
        process = entry.process
        if process is None:
            return int(entry.exit_code or 0)
        if isinstance(process, asyncio.subprocess.Process):
            return int(await process.wait())
        loop = asyncio.get_running_loop()
        return int(await loop.run_in_executor(None, process.wait))

    async def _send(self, entry: BrokerEntry, *, stdin: str) -> None:
        if entry.status != "running":
            raise RuntimeError(f"Shell broker entry is not running: {entry.entry_id}")
        if not entry.live_handle:
            raise RuntimeError(f"Shell broker entry cannot accept stdin after recovery: {entry.entry_id}")
        if entry.master_fd is not None:
            os.write(entry.master_fd, stdin.encode("utf-8"))
            return
        process = entry.process
        if not isinstance(process, asyncio.subprocess.Process) or process.stdin is None:
            raise RuntimeError(f"Shell broker entry cannot accept stdin: {entry.entry_id}")
        process.stdin.write(stdin.encode("utf-8"))
        await process.stdin.drain()

    async def _interrupt(self, entry: BrokerEntry) -> None:
        entry.interrupt_requested = True
        self._signal_entry(entry, signal.SIGINT)
        self._persist_entry(entry)

    async def _stop(self, entry: BrokerEntry) -> None:
        entry.stop_requested = True
        if entry.live_handle and entry.wait_task is not None:
            await self._terminate_live_entry(entry)
            await entry.wait_task
            return
        self._signal_entry(entry, signal.SIGTERM)
        entry.status = "stopped"
        entry.recovery_state = "completed"
        self._persist_entry(entry)

    async def _terminate_live_entry(self, entry: BrokerEntry) -> None:
        process = entry.process
        if process is None:
            return
        self._signal_entry(entry, signal.SIGTERM)
        try:
            await asyncio.wait_for(self._wait_for_process(entry), timeout=_STOP_GRACE_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        self._signal_entry(entry, signal.SIGKILL)

    def _signal_entry(self, entry: BrokerEntry, sig: signal.Signals) -> None:
        pid = entry.pid
        if pid is None:
            return
        try:
            if os.name == "nt":
                os.kill(pid, sig)
            else:
                os.killpg(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            return

    def _entry_snapshot(self, entry: BrokerEntry) -> dict[str, Any]:
        stdout_preview, _ = _truncate_text(entry.stdout_buffer, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
        stderr_preview, _ = _truncate_text(entry.stderr_buffer, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
        recent_output_preview, _ = _truncate_text(entry.recent_output, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
        return {
            "entry_id": entry.entry_id,
            "kind": entry.kind,
            "command": entry.command,
            "shell": entry.shell,
            "cwd": str(entry.cwd),
            "workspace_root": str(entry.workspace_root),
            "session_mode": entry.session_mode,
            "session_profile": entry.session_profile,
            "terminal_mode": entry.terminal_mode,
            "shell_session_id": entry.shell_session_id,
            "job_id": entry.job_id,
            "description": entry.description,
            "classification": entry.classification,
            "status": entry.status,
            "recovery_state": entry.recovery_state,
            "exit_code": entry.exit_code,
            "pid": entry.pid,
            "broker_pid": os.getpid(),
            "socket_path": str(self.default_socket_path) if self.transport == "unix" else None,
            "broker_address": (
                f"{self.server.sockets[0].getsockname()[0]}:{self.server.sockets[0].getsockname()[1]}"
                if self.transport == "tcp" and self.server is not None and self.server.sockets
                else None
            ),
            "sidecar_dir": str(entry.sidecar_dir),
            "metadata_path": str(entry.metadata_path),
            "output_path": str(entry.output_path),
            "output_sequence": entry.output_sequence,
            "recent_output_preview": recent_output_preview,
            "recent_output_stream": entry.recent_stream,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
            "live_handle": entry.live_handle,
        }

    def _output_since_sequence(
        self,
        entry: BrokerEntry,
        *,
        after_sequence: int,
        max_output_chars: int,
    ) -> tuple[str, int]:
        if entry.output_chunks:
            relevant = [chunk for chunk in entry.output_chunks if chunk.sequence > after_sequence]
            text = "".join(chunk.text for chunk in relevant)
            if len(text) > max_output_chars:
                text = text[-max_output_chars:]
            latest_sequence = relevant[-1].sequence if relevant else after_sequence
            return text, latest_sequence
        text_parts: list[str] = []
        latest_sequence = after_sequence
        if entry.output_path.exists():
            for raw_line in entry.output_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                sequence = int(payload.get("sequence") or 0)
                if sequence <= after_sequence:
                    latest_sequence = max(latest_sequence, sequence)
                    continue
                text_parts.append(str(payload.get("text") or ""))
                latest_sequence = sequence
        text = "".join(text_parts)
        if len(text) > max_output_chars:
            text = text[-max_output_chars:]
        return text, latest_sequence

    def _load_existing_entries(self) -> None:
        for payload in list_shell_sidecars(self.workspace_root):
            entry_id = str(payload.get("entry_id") or "").strip()
            if not entry_id:
                continue
            kind = str(payload.get("kind") or "").strip()
            shell = str(payload.get("shell") or "bash")
            cwd = Path(str(payload.get("cwd") or self.workspace_root)).resolve()
            session_profile = str(payload.get("session_profile") or "line_session")
            session_mode = str(payload.get("session_mode") or ("session" if kind == "shell_session" else "background"))
            terminal_mode = str(payload.get("terminal_mode") or ("pty" if session_profile == "pty_session" else "line"))
            shell_session_id = str(payload.get("shell_session_id") or "").strip() or None
            job_id = str(payload.get("job_id") or "").strip() or None
            metadata_path = Path(str(payload.get("metadata_path") or ""))
            if not metadata_path:
                metadata_path = (
                    session_sidecar_dir(self.workspace_root, shell_session_id or entry_id)
                    if kind == "shell_session"
                    else background_sidecar_dir(self.workspace_root, job_id or entry_id)
                ) / "session.json"
            sidecar_dir = Path(str(payload.get("sidecar_dir") or metadata_path.parent))
            output_path = Path(str(payload.get("output_path") or (sidecar_dir / "output.jsonl")))
            entry = BrokerEntry(
                entry_id=entry_id,
                kind=kind or "background_shell",
                command=str(payload.get("command") or ""),
                shell=shell,
                cwd=cwd,
                workspace_root=self.workspace_root,
                session_mode=session_mode,
                session_profile=session_profile,
                terminal_mode=terminal_mode,
                shell_session_id=shell_session_id,
                job_id=job_id,
                description=str(payload.get("description") or "").strip() or None,
                classification=str(payload.get("classification") or "other"),
                sidecar_dir=sidecar_dir,
                metadata_path=metadata_path,
                output_path=output_path,
                created_at=float(payload.get("created_at") or time.time()),
                updated_at=float(payload.get("updated_at") or time.time()),
                status=str(payload.get("status") or "completed"),
                recovery_state=str(payload.get("recovery_state") or "completed"),
                exit_code=payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
                pid=payload.get("pid") if isinstance(payload.get("pid"), int) else None,
                output_sequence=int(payload.get("output_sequence") or 0),
                recent_output=str(payload.get("recent_output") or ""),
                recent_stream=str(payload.get("recent_stream") or "").strip() or None,
                stdout_buffer=str(payload.get("stdout_buffer") or ""),
                stderr_buffer=str(payload.get("stderr_buffer") or ""),
            )
            if entry.status == "running":
                if entry.pid is not None and _pid_alive(entry.pid):
                    entry.recovery_state = "orphaned"
                else:
                    entry.status = "recovery_unavailable"
                    entry.recovery_state = "recovery_unavailable"
            self.entries[entry.entry_id] = entry
            self._persist_entry(entry)

    def _persist_entry(self, entry: BrokerEntry) -> None:
        entry.updated_at = time.time()
        payload = {
            "entry_id": entry.entry_id,
            "kind": entry.kind,
            "command": entry.command,
            "shell": entry.shell,
            "cwd": str(entry.cwd),
            "workspace_root": str(entry.workspace_root),
            "session_mode": entry.session_mode,
            "session_profile": entry.session_profile,
            "terminal_mode": entry.terminal_mode,
            "shell_session_id": entry.shell_session_id,
            "job_id": entry.job_id,
            "description": entry.description,
            "classification": entry.classification,
            "status": entry.status,
            "recovery_state": entry.recovery_state,
            "exit_code": entry.exit_code,
            "pid": entry.pid,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "output_sequence": entry.output_sequence,
            "recent_output": entry.recent_output,
            "recent_stream": entry.recent_stream,
            "stdout_buffer": entry.stdout_buffer,
            "stderr_buffer": entry.stderr_buffer,
            "sidecar_dir": str(entry.sidecar_dir),
            "metadata_path": str(entry.metadata_path),
            "output_path": str(entry.output_path),
        }
        entry.metadata_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")

    def _schedule_idle_shutdown(self) -> None:
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_shutdown_loop())

    async def _idle_shutdown_loop(self) -> None:
        await asyncio.sleep(_BROKER_IDLE_SHUTDOWN_SECONDS)
        if any(entry.live_handle and entry.status == "running" for entry in self.entries.values()):
            return
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        for entry in list(self.entries.values()):
            if entry.live_handle and entry.status == "running":
                await self._terminate_live_entry(entry)
        _cleanup_stale_broker_files(self.workspace_root)


def _shell_command_argv(shell: str, command: str) -> list[str]:
    if shell == "powershell":
        return ["pwsh", "-NoProfile", "-Command", command]
    return ["bash", "-lc", command]


def _append_capped_text(current: str, text: str) -> str:
    combined = current + text
    if len(combined) <= _SESSION_OUTPUT_MAX_CHARS:
        return combined
    return combined[-_SESSION_OUTPUT_MAX_CHARS:]


def _truncate_text(text: str, max_chars: int, max_lines: int) -> tuple[str, bool]:
    if not text:
        return "", False
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    clipped = "\n".join(lines)
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars].rstrip()
        truncated = True
    return clipped, truncated


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the code assistant shell broker.")
    parser.add_argument("--workspace-root", required=True, help="Workspace root for durable shell state.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace_root = Path(args.workspace_root).resolve()
    broker = ShellBroker(workspace_root)
    asyncio.run(broker.serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
