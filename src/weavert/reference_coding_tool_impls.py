from __future__ import annotations

import ast
import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .builtins.tool_impls import _path_allowed, _resolve_path
from .definitions import ValidationOutcome
from .tool_runtime import ToolContext

_MAX_SEARCH_RESULTS = 64
_MAX_TEXT_FILE_BYTES = 1_000_000
_IGNORED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".weavert",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
_SYMBOL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"), "class"),
    (re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"), "function"),
    (
        re.compile(r"^\s*(?:export\s+)?function\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
        "function",
    ),
    (
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"),
        "variable",
    ),
    (re.compile(r"^\s*type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"), "type"),
    (re.compile(r"^\s*func\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"), "function"),
    (re.compile(r"^\s*(?:pub\s+)?fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"), "function"),
)
_TEST_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)tests?/", re.IGNORECASE),
    re.compile(r"(^|/)test_[^/]+\.[^.]+$", re.IGNORECASE),
    re.compile(r"(^|/)[^/]+_test\.[^.]+$", re.IGNORECASE),
    re.compile(r"(^|/)[^/]+\.(spec|test)\.[^.]+$", re.IGNORECASE),
)


async def git_status_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    start_path = _resolve_optional_path(context, tool_input.get("path"))
    return await asyncio.to_thread(_git_status_sync, start_path, tool_input)


async def git_diff_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    start_path = _resolve_optional_path(context, tool_input.get("path"))
    return await asyncio.to_thread(_git_diff_sync, start_path, tool_input)


async def git_history_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    start_path = _resolve_optional_path(context, tool_input.get("path"))
    return await asyncio.to_thread(_git_history_sync, start_path, tool_input)


async def workspace_symbols_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_optional_path(context, tool_input.get("path"))
    query = str(tool_input["query"]).strip()
    limit = int(tool_input.get("limit") or _MAX_SEARCH_RESULTS)
    return await asyncio.to_thread(_workspace_symbols_sync, root, query, limit, context)


async def workspace_references_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_optional_path(context, tool_input.get("path"))
    symbol = str(tool_input["symbol"]).strip()
    limit = int(tool_input.get("limit") or _MAX_SEARCH_RESULTS)
    case_sensitive = bool(tool_input.get("case_sensitive", True))
    return await asyncio.to_thread(
        _workspace_references_sync,
        root,
        symbol,
        limit,
        case_sensitive,
        context,
    )


async def workspace_outline_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    file_path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    return await asyncio.to_thread(_workspace_outline_sync, file_path)


async def workspace_test_targets_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    limit = int(tool_input.get("limit") or _MAX_SEARCH_RESULTS)
    file_path = tool_input.get("file_path")
    resolved_file_path = (
        _resolve_path(context.cwd, file_path, context=context)
        if isinstance(file_path, str) and file_path.strip()
        else None
    )
    symbol = str(tool_input.get("symbol") or "").strip() or None
    query = str(tool_input.get("query") or "").strip() or None
    return await asyncio.to_thread(
        _workspace_test_targets_sync,
        context.cwd,
        resolved_file_path,
        symbol,
        query,
        limit,
        context,
    )


def validate_git_path_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = tool_input.get("path")
    if path is None:
        return ValidationOutcome(True)
    try:
        _resolve_path(context.cwd, str(path), context=context)
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True)


def validate_workspace_query_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    query = str(tool_input.get("query") or "").strip()
    if not query:
        return ValidationOutcome(False, "query must be non-empty")
    return validate_git_path_tool(tool_input, context)


def validate_workspace_symbol_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    symbol = str(tool_input.get("symbol") or "").strip()
    if not symbol:
        return ValidationOutcome(False, "symbol must be non-empty")
    return validate_git_path_tool(tool_input, context)


def validate_workspace_outline_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    try:
        path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    if not path.exists():
        return ValidationOutcome(False, f"File does not exist: {path}")
    if not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


def validate_workspace_test_targets_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> ValidationOutcome:
    file_path = str(tool_input.get("file_path") or "").strip()
    if file_path:
        try:
            _resolve_path(context.cwd, file_path, context=context)
        except ValueError as exc:
            return ValidationOutcome(False, str(exc))
    if not file_path and not str(tool_input.get("symbol") or "").strip() and not str(tool_input.get("query") or "").strip():
        return ValidationOutcome(True)
    return ValidationOutcome(True)


def _resolve_optional_path(context: ToolContext, raw_path: Any) -> Path:
    if raw_path is None or not str(raw_path).strip():
        return context.cwd
    resolved = _resolve_path(context.cwd, str(raw_path), context=context)
    return resolved if resolved.is_dir() else resolved.parent


def _git_status_sync(start_path: Path, tool_input: dict[str, Any]) -> dict[str, Any]:
    repo = _git_repo_context(start_path)
    if not repo["ok"]:
        return repo
    target = _git_pathspec(repo_root=repo["repo_root"], start_path=start_path)
    args = ["status", "--short", "--branch"]
    if not bool(tool_input.get("include_untracked", True)):
        args.append("--untracked-files=no")
    if target is not None:
        args.extend(["--", target])
    result = _run_git_command(repo["repo_root"], args)
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    branch = lines[0] if lines and lines[0].startswith("##") else None
    entries = [
        {
            "status": line[:2],
            "path": line[3:] if len(line) > 3 else "",
            "raw": line,
        }
        for line in lines
        if not line.startswith("##")
    ]
    return {
        **repo,
        **result,
        "branch": branch,
        "entries": entries,
    }


def _git_diff_sync(start_path: Path, tool_input: dict[str, Any]) -> dict[str, Any]:
    repo = _git_repo_context(start_path)
    if not repo["ok"]:
        return repo
    target = _git_pathspec(repo_root=repo["repo_root"], start_path=start_path)
    args = ["diff"]
    if bool(tool_input.get("cached", False)):
        args.append("--cached")
    context_lines = tool_input.get("context_lines")
    if context_lines is not None:
        args.append(f"--unified={int(context_lines)}")
    base_ref = str(tool_input.get("base_ref") or "").strip()
    head_ref = str(tool_input.get("head_ref") or "").strip()
    if base_ref and head_ref:
        args.extend([base_ref, head_ref])
    elif base_ref:
        args.append(base_ref)
    elif head_ref:
        args.append(head_ref)
    if target is not None:
        args.extend(["--", target])
    result = _run_git_command(repo["repo_root"], args)
    changed_files = [
        line.removeprefix("+++ b/")
        for line in result["stdout"].splitlines()
        if line.startswith("+++ b/")
    ]
    return {
        **repo,
        **result,
        "changed_files": changed_files,
    }


def _git_history_sync(start_path: Path, tool_input: dict[str, Any]) -> dict[str, Any]:
    repo = _git_repo_context(start_path)
    if not repo["ok"]:
        return repo
    target = _git_pathspec(repo_root=repo["repo_root"], start_path=start_path)
    limit = int(tool_input.get("limit") or 10)
    ref = str(tool_input.get("ref") or "").strip()
    args = ["log", "--decorate", "--oneline", f"-n{limit}"]
    if ref:
        args.append(ref)
    if target is not None:
        args.extend(["--", target])
    result = _run_git_command(repo["repo_root"], args)
    entries = []
    for line in result["stdout"].splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        commit, _separator, summary = normalized.partition(" ")
        entries.append({"commit": commit, "summary": summary, "raw": normalized})
    return {
        **repo,
        **result,
        "entries": entries,
    }


def _workspace_symbols_sync(root: Path, query: str, limit: int, context: ToolContext) -> dict[str, Any]:
    lowered_query = query.lower()
    matches: list[dict[str, Any]] = []
    total_matches = 0
    for file_path in _iter_text_files(root, context):
        text = _read_text(file_path)
        if text is None:
            continue
        file_matches = (
            _python_symbol_matches(file_path, text, lowered_query)
            if file_path.suffix == ".py"
            else _regex_symbol_matches(file_path, text, lowered_query)
        )
        total_matches += len(file_matches)
        for match in file_matches:
            if len(matches) < limit:
                matches.append(match)
    return {
        "query": query,
        "root": str(root),
        "matches": matches,
        "total_matches": total_matches,
        "returned_matches": len(matches),
        "truncated": total_matches > len(matches),
    }


def _workspace_references_sync(
    root: Path,
    symbol: str,
    limit: int,
    case_sensitive: bool,
    context: ToolContext,
) -> dict[str, Any]:
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(rf"\b{re.escape(symbol)}\b", flags)
    matches: list[dict[str, Any]] = []
    total_matches = 0
    for file_path in _iter_text_files(root, context):
        text = _read_text(file_path)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            total_matches += 1
            if len(matches) >= limit:
                continue
            matches.append(
                {
                    "file_path": str(file_path),
                    "line_number": line_number,
                    "line": line,
                }
            )
    return {
        "symbol": symbol,
        "root": str(root),
        "case_sensitive": case_sensitive,
        "matches": matches,
        "total_matches": total_matches,
        "returned_matches": len(matches),
        "truncated": total_matches > len(matches),
    }


def _workspace_outline_sync(file_path: Path) -> dict[str, Any]:
    text = _read_text(file_path)
    if text is None:
        return {
            "file_path": str(file_path),
            "symbols": [],
            "parse_mode": "unreadable",
        }
    if file_path.suffix == ".py":
        try:
            symbols = _python_outline(file_path, text)
            return {
                "file_path": str(file_path),
                "symbols": symbols,
                "parse_mode": "python-ast",
            }
        except SyntaxError:
            pass
    return {
        "file_path": str(file_path),
        "symbols": _regex_outline(file_path, text),
        "parse_mode": "regex",
    }


def _workspace_test_targets_sync(
    workspace_root: Path,
    file_path: Path | None,
    symbol: str | None,
    query: str | None,
    limit: int,
    context: ToolContext,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    search_terms = _test_search_terms(file_path=file_path, symbol=symbol, query=query)
    for test_path in _iter_text_files(workspace_root, context):
        if not _looks_like_test_file(test_path):
            continue
        text = _read_text(test_path)
        if text is None:
            continue
        scored = _score_test_candidate(
            workspace_root=workspace_root,
            test_path=test_path,
            text=text,
            file_path=file_path,
            symbol=symbol,
            query=query,
            search_terms=search_terms,
        )
        if scored is None:
            continue
        candidates.append(scored)
    candidates.sort(key=lambda item: (-item["score"], item["file_path"]))
    returned = candidates[:limit]
    return {
        "workspace_root": str(workspace_root),
        "file_path": str(file_path) if file_path is not None else None,
        "symbol": symbol,
        "query": query,
        "candidates": returned,
        "total_candidates": len(candidates),
        "returned_candidates": len(returned),
        "truncated": len(candidates) > len(returned),
    }


def _git_repo_context(start_path: Path) -> dict[str, Any]:
    probe_root = start_path if start_path.is_dir() else start_path.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(probe_root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "is_git_repo": False,
            "repo_root": None,
            "exit_code": 127,
            "stdout": "",
            "stderr": "git is not installed",
        }
    repo_root = result.stdout.strip()
    if result.returncode != 0 or not repo_root:
        return {
            "ok": False,
            "is_git_repo": False,
            "repo_root": None,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    return {
        "ok": True,
        "is_git_repo": True,
        "repo_root": str(Path(repo_root)),
    }


def _git_pathspec(*, repo_root: str, start_path: Path) -> str | None:
    repo_path = Path(repo_root)
    target = start_path
    if target == repo_path:
        return None
    if target.is_dir():
        return target.relative_to(repo_path).as_posix()
    return target.relative_to(repo_path).as_posix()


def _run_git_command(repo_root: str, args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "-C", repo_root, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": ["git", "-C", repo_root, *args],
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _iter_text_files(root: Path, context: ToolContext):
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in sorted(dirnames)
            if name not in _IGNORED_DIR_NAMES
        ]
        for filename in sorted(filenames):
            path = Path(current_root) / filename
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not _path_allowed(resolved, context):
                continue
            try:
                if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _python_symbol_matches(file_path: Path, text: str, lowered_query: str) -> list[dict[str, Any]]:
    tree = ast.parse(text)
    matches: list[dict[str, Any]] = []

    def visit(node: ast.AST, container: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                _maybe_add_symbol_match(
                    matches,
                    file_path=file_path,
                    name=child.name,
                    kind="class",
                    lowered_query=lowered_query,
                    line_number=child.lineno,
                    column=getattr(child, "col_offset", 0) + 1,
                    container=container,
                )
                visit(child, (*container, child.name))
                continue
            if isinstance(child, ast.AsyncFunctionDef):
                _maybe_add_symbol_match(
                    matches,
                    file_path=file_path,
                    name=child.name,
                    kind="async_function",
                    lowered_query=lowered_query,
                    line_number=child.lineno,
                    column=getattr(child, "col_offset", 0) + 1,
                    container=container,
                )
                visit(child, (*container, child.name))
                continue
            if isinstance(child, ast.FunctionDef):
                _maybe_add_symbol_match(
                    matches,
                    file_path=file_path,
                    name=child.name,
                    kind="function",
                    lowered_query=lowered_query,
                    line_number=child.lineno,
                    column=getattr(child, "col_offset", 0) + 1,
                    container=container,
                )
                visit(child, (*container, child.name))
                continue
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        _maybe_add_symbol_match(
                            matches,
                            file_path=file_path,
                            name=target.id,
                            kind="variable",
                            lowered_query=lowered_query,
                            line_number=target.lineno,
                            column=getattr(target, "col_offset", 0) + 1,
                            container=container,
                        )
                visit(child, container)
                continue
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                target = child.target
                _maybe_add_symbol_match(
                    matches,
                    file_path=file_path,
                    name=target.id,
                    kind="variable",
                    lowered_query=lowered_query,
                    line_number=target.lineno,
                    column=getattr(target, "col_offset", 0) + 1,
                    container=container,
                )
                visit(child, container)
                continue
            visit(child, container)

    visit(tree)
    return matches


def _regex_symbol_matches(file_path: Path, text: str, lowered_query: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern, kind in _SYMBOL_PATTERNS:
            candidate = pattern.search(line)
            if candidate is None:
                continue
            name = candidate.group("name")
            if lowered_query not in name.lower():
                continue
            matches.append(
                {
                    "file_path": str(file_path),
                    "name": name,
                    "kind": kind,
                    "line_number": line_number,
                    "column": candidate.start("name") + 1,
                }
            )
    return matches


def _maybe_add_symbol_match(
    matches: list[dict[str, Any]],
    *,
    file_path: Path,
    name: str,
    kind: str,
    lowered_query: str,
    line_number: int,
    column: int,
    container: tuple[str, ...],
) -> None:
    if lowered_query not in name.lower():
        return
    payload = {
        "file_path": str(file_path),
        "name": name,
        "kind": kind,
        "line_number": line_number,
        "column": column,
    }
    if container:
        payload["container"] = "::".join(container)
    matches.append(payload)


def _python_outline(file_path: Path, text: str) -> list[dict[str, Any]]:
    tree = ast.parse(text)
    outline: list[dict[str, Any]] = []

    def visit(node: ast.AST, depth: int = 0) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                outline.append(_outline_entry(file_path, child.name, "class", child.lineno, child.col_offset + 1, depth))
                visit(child, depth + 1)
                continue
            if isinstance(child, ast.AsyncFunctionDef):
                outline.append(
                    _outline_entry(
                        file_path,
                        child.name,
                        "async_function",
                        child.lineno,
                        child.col_offset + 1,
                        depth,
                    )
                )
                visit(child, depth + 1)
                continue
            if isinstance(child, ast.FunctionDef):
                outline.append(
                    _outline_entry(file_path, child.name, "function", child.lineno, child.col_offset + 1, depth)
                )
                visit(child, depth + 1)
                continue
            visit(child, depth)

    visit(tree)
    return outline


def _regex_outline(file_path: Path, text: str) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern, kind in _SYMBOL_PATTERNS:
            candidate = pattern.search(line)
            if candidate is None:
                continue
            outline.append(
                {
                    "file_path": str(file_path),
                    "name": candidate.group("name"),
                    "kind": kind,
                    "line_number": line_number,
                    "column": candidate.start("name") + 1,
                    "depth": 0,
                }
            )
    return outline


def _outline_entry(
    file_path: Path,
    name: str,
    kind: str,
    line_number: int,
    column: int,
    depth: int,
) -> dict[str, Any]:
    return {
        "file_path": str(file_path),
        "name": name,
        "kind": kind,
        "line_number": line_number,
        "column": column,
        "depth": depth,
    }


def _looks_like_test_file(path: Path) -> bool:
    normalized = path.as_posix()
    return any(pattern.search(normalized) for pattern in _TEST_FILE_PATTERNS)


def _test_search_terms(
    *,
    file_path: Path | None,
    symbol: str | None,
    query: str | None,
) -> tuple[str, ...]:
    terms: list[str] = []
    if file_path is not None:
        stem = file_path.stem
        terms.append(stem)
        if stem.startswith("test_"):
            terms.append(stem.removeprefix("test_"))
        parent_stem = file_path.parent.name
        if parent_stem and parent_stem not in {"src", "tests"}:
            terms.append(parent_stem)
    if symbol:
        terms.append(symbol)
    if query:
        terms.extend(part for part in re.split(r"[^A-Za-z0-9_]+", query) if part)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        lowered = term.lower()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(term)
    return tuple(deduped)


def _score_test_candidate(
    *,
    workspace_root: Path,
    test_path: Path,
    text: str,
    file_path: Path | None,
    symbol: str | None,
    query: str | None,
    search_terms: tuple[str, ...],
) -> dict[str, Any] | None:
    lowered_path = test_path.as_posix().lower()
    score = 0
    reasons: list[str] = []
    preview: dict[str, Any] | None = None

    if file_path is not None:
        target_stem = file_path.stem.lower()
        if target_stem and target_stem in lowered_path:
            score += 100
            reasons.append(f"filename mentions '{file_path.stem}'")

    if symbol:
        symbol_pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if symbol_pattern.search(line):
                score += 80
                reasons.append(f"references symbol '{symbol}'")
                preview = {"line_number": line_number, "line": line}
                break

    lowered_text = text.lower()
    for term in search_terms:
        lowered_term = term.lower()
        if lowered_term in lowered_path:
            score += 40
            reasons.append(f"path mentions '{term}'")
        if lowered_term in lowered_text:
            score += 20
            if preview is None:
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if lowered_term in line.lower():
                        preview = {"line_number": line_number, "line": line}
                        break
            reasons.append(f"content mentions '{term}'")

    if query and not search_terms:
        score += 10
        reasons.append(f"listed for query '{query}'")

    if not search_terms and file_path is None and symbol is None and query is None:
        score = 1
        reasons.append("listed because it is a detected test target")

    if score <= 0:
        return None

    candidate = {
        "file_path": str(test_path.relative_to(workspace_root)),
        "score": score,
        "reasons": reasons,
    }
    if preview is not None:
        candidate["preview"] = preview
    return candidate


__all__ = [
    "git_diff_tool",
    "git_history_tool",
    "git_status_tool",
    "validate_git_path_tool",
    "validate_workspace_outline_tool",
    "validate_workspace_query_tool",
    "validate_workspace_symbol_tool",
    "validate_workspace_test_targets_tool",
    "workspace_outline_tool",
    "workspace_references_tool",
    "workspace_symbols_tool",
    "workspace_test_targets_tool",
]
