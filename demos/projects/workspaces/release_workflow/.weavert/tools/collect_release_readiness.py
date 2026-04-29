from __future__ import annotations

import json
from pathlib import Path

from weavert.definitions import ToolDefinition, ToolTraits


def _parse_key_value_lines(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _parse_release_plan(path: Path) -> dict[str, object]:
    services: list[str] = []
    plan: dict[str, object] = {"services": services}
    current_list: list[str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith("  - ") and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key == "services":
            current_list = services
            continue
        current_list = None
        plan[normalized_key] = [] if normalized_value == "[]" else normalized_value
    return plan


def execute(tool_input, context):
    _ = tool_input
    workspace = context.cwd
    plan = _parse_release_plan(workspace / "release_plan.yaml")
    qa_report = json.loads((workspace / "qa_report.json").read_text(encoding="utf-8"))
    changed_services: list[str] = []
    for service_name in plan.get("services", []):
        manifest = _parse_key_value_lines(workspace / "services" / str(service_name) / "manifest.txt")
        if manifest.get("changed", "").lower() == "true":
            changed_services.append(str(service_name))
    blockers = qa_report.get("release_blockers", [])
    return {
        "workspace": str(plan["workspace"]),
        "release_id": str(plan["release_id"]),
        "changed_services": changed_services,
        "qa_status": str(qa_report["status"]),
        "critical_findings": int(qa_report["critical_findings"]),
        "has_changelog": (workspace / "CHANGELOG.md").exists(),
        "release_blockers": list(blockers),
    }


TOOL_DEFINITION = ToolDefinition(
    name="collect_release_readiness",
    description="Collect deterministic release-readiness facts from the demo workspace.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    traits=ToolTraits(read_only=True, concurrency_safe=True),
    execute=execute,
)
