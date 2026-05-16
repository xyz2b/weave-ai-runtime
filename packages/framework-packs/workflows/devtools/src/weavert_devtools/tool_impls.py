from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from weavert.builtins.tool_impls import _normalize_optional_string, _path_allowed, _resolve_path
from weavert.definitions import SkillShell, ValidationOutcome
from weavert.tool_runtime import ToolContext
from weavert_web_research import DuckDuckGoHtmlBackend, build_policy, inspect_page, search_web, validate_web_url_input

_GLOB_TOOL_MAX_MATCHES = 128


async def read_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    offset = tool_input.get("offset", 0)
    limit = tool_input.get("limit")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    selected = lines[offset : offset + limit if limit is not None else None]
    return {
        "file_path": str(path),
        "content": "\n".join(selected),
        "start_line": offset + 1 if lines else 0,
        "line_count": len(selected),
    }


async def glob_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_path(context.cwd, tool_input.get("root", "."), context=context)
    pattern = tool_input["pattern"]
    matched_paths = []
    for path in root.glob(pattern):
        resolved = path.resolve()
        if _path_allowed(resolved, context):
            matched_paths.append(path)
    matched_paths.sort(key=str)
    if len(matched_paths) > _GLOB_TOOL_MAX_MATCHES:
        sampled_paths = sorted(
            matched_paths,
            key=lambda path: _glob_sample_sort_key(path, root=root),
        )[:_GLOB_TOOL_MAX_MATCHES]
    else:
        sampled_paths = matched_paths
    return {
        "root": str(root),
        "pattern": pattern,
        "matches": [str(path) for path in sampled_paths],
        "total_matches": len(matched_paths),
        "returned_matches": len(sampled_paths),
        "truncated": len(sampled_paths) < len(matched_paths),
    }


def _glob_sample_sort_key(path: Path, *, root: Path) -> tuple[int, str]:
    relative = path.relative_to(root)
    return (len(relative.parts), relative.as_posix())


async def grep_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_path(context.cwd, tool_input.get("path", "."), context=context)
    pattern = re.compile(
        tool_input["pattern"],
        0 if tool_input.get("case_sensitive", False) else re.IGNORECASE,
    )
    results: list[dict[str, Any]] = []
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        if not _path_allowed(file_path.resolve(), context):
            continue
        try:
            for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    results.append(
                        {
                            "file_path": str(file_path),
                            "line_number": line_number,
                            "line": line,
                        }
                    )
        except UnicodeDecodeError:
            continue
    return {"pattern": tool_input["pattern"], "matches": results}


def validate_read_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    if not path.exists():
        return ValidationOutcome(False, f"File does not exist: {path}")
    if not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


def validate_edit_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    if not path.exists() and tool_input["old_string"] != "":
        return ValidationOutcome(False, f"File does not exist: {path}")
    if path.exists() and not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    if tool_input["old_string"] == tool_input["new_string"]:
        return ValidationOutcome(False, "old_string and new_string must differ")
    return ValidationOutcome(True)


def validate_write_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    if path.exists() and not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


async def edit_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    old_string = tool_input["old_string"]
    new_string = tool_input["new_string"]
    replace_all = tool_input.get("replace_all", False)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if old_string not in original and old_string != "":
        raise ValueError("old_string not found in file")
    updated = (
        original.replace(old_string, new_string)
        if replace_all
        else original.replace(old_string, new_string, 1)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return {"file_path": str(path), "updated": True}


async def write_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    original = path.read_text(encoding="utf-8") if path.exists() else None
    changed = original != tool_input["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tool_input["content"], encoding="utf-8")
    return {
        "file_path": str(path),
        "bytes_written": len(tool_input["content"].encode("utf-8")),
        "changed": changed,
    }


def validate_bash_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not tool_input["command"].strip():
        return ValidationOutcome(False, "command must be non-empty")
    shell = _normalize_optional_string(tool_input.get("shell"))
    if shell is not None and shell not in {SkillShell.BASH.value, SkillShell.POWERSHELL.value}:
        return ValidationOutcome(False, f"Unsupported shell: {shell}")
    return ValidationOutcome(True)


async def bash_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    cwd = _resolve_path(context.cwd, tool_input.get("cwd", "."), context=context)
    timeout_ms = tool_input.get("timeout_ms", 30_000)
    shell = _normalize_optional_string(tool_input.get("shell")) or SkillShell.BASH.value
    if shell == SkillShell.POWERSHELL.value:
        process = await asyncio.create_subprocess_exec(
            "pwsh",
            "-NoProfile",
            "-Command",
            tool_input["command"],
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        process = await asyncio.create_subprocess_shell(
            tool_input["command"],
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        raise ValueError("Command timed out")
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise
    return {
        "command": tool_input["command"],
        "shell": shell,
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def validate_url_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    validation_error = validate_web_url_input(tool_input["url"])
    if validation_error is not None:
        return ValidationOutcome(False, validation_error)
    return ValidationOutcome(True)


async def web_fetch_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    policy = build_policy(tool_input, default_search_limit=5, default_text_chars=32_000, default_find_matches=5)

    def fetch() -> dict[str, Any]:
        result = inspect_page(
            tool_input,
            backend=DuckDuckGoHtmlBackend(),
            policy=policy,
        )
        return {
            "url": result["url"],
            "status": result["status"],
            "content_type": result["content_type"],
            "content": result["content"],
            "title": result["title"],
            "truncated": result["truncated"],
            "source_handle": result["source_handle"],
            "page_handle": result["page_handle"],
            "source": result["source"],
            "policy": result["policy"],
        }

    return await asyncio.to_thread(fetch)


def validate_web_search(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not tool_input["query"].strip():
        return ValidationOutcome(False, "query must be non-empty")
    return ValidationOutcome(True)


async def web_search_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    policy = build_policy(tool_input, default_search_limit=5, default_text_chars=32_000, default_find_matches=5)

    def search() -> dict[str, Any]:
        return search_web(
            str(tool_input["query"]),
            backend=DuckDuckGoHtmlBackend(),
            policy=policy,
        )

    return await asyncio.to_thread(search)


__all__ = [
    "bash_tool",
    "edit_file_tool",
    "glob_tool",
    "grep_tool",
    "read_file_tool",
    "validate_bash_tool",
    "validate_edit_tool",
    "validate_read_tool",
    "validate_url_tool",
    "validate_web_search",
    "validate_write_tool",
    "web_fetch_tool",
    "web_search_tool",
    "write_file_tool",
]
