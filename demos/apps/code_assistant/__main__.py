from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .app import DEFAULT_PROMPT, default_layout, inspect_demo, reset_demo_state, run_demo, shell_demo


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reactive AI coding shell V2 demo.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    shell_parser = subparsers.add_parser("shell", help="Run the interactive reactive AI coding shell.")
    shell_parser.add_argument("--session-id", default=None, help="Optional stable session id.")
    shell_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve edit, write, and bash actions during the shell session.",
    )

    run_parser = subparsers.add_parser("run", help="Run the live code assistant workflow.")
    run_parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to give the code assistant.")
    run_parser.add_argument("--session-id", default=None, help="Optional stable session id.")
    run_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve edit, write, and bash actions for harness-style runs.",
    )

    subparsers.add_parser("reset", help="Restore the mutable workspace from the pristine fixture.")
    subparsers.add_parser("inspect", help="Show durable-state details for the mutable workspace.")

    args = parser.parse_args()
    layout = default_layout()

    if args.command == "reset":
        workspace_root = reset_demo_state(layout=layout)
        print("code assistant demo reset")
        print(f"workspace: {_display_path(workspace_root)}")
        print(f"fixture: {_display_path(layout.fixture_root)}")
        print("state cleared: live edits, transcripts, child runs, task lists, and memory were reset")
        return 0

    if args.command == "inspect":
        report = inspect_demo(layout=layout)
        print("code assistant demo inspect")
        print(f"workspace exists: {'yes' if report.workspace_exists else 'no'}")
        print(f"fixture: {_display_path(report.fixture_root)}")
        print(f"state root: {_display_path(report.state_root)}")
        if not report.workspace_exists:
            print("hint: run `python3 -B -m demos.apps.code_assistant reset`, `shell`, or `run` first")
            return 0
        print(f"workspace: {_display_path(report.workspace_root)}")
        print(f"distribution: {report.distribution}")
        print(f"default route: {report.default_model_route}")
        print(
            "persistence profile: "
            f"{report.persistence_profile.get('profile_kind', 'unknown')}"
        )
        print(f"transcript sessions: {len(report.transcript_sessions)}")
        for session in report.transcript_sessions[:5]:
            relative = _display_path(Path(session["path"]))
            print(f"- transcript {session['session_id']}: {relative} ({session['entries']} entries)")
        print(f"child run sessions: {len(report.child_run_sessions)}")
        for session in report.child_run_sessions[:5]:
            print(
                f"- child runs {session['session_id']}: {session['count']} "
                f"({', '.join(session['agents'])})"
            )
        if report.child_run_records:
            print(f"child run records: {len(report.child_run_records)}")
            for record in report.child_run_records[:10]:
                print(
                    f"- child {record['session_id']} {record['agent']}: "
                    f"{record['status']} -> {record['summary']}"
                )
        print(f"task lists: {len(report.task_lists)}")
        for task_list in report.task_lists[:5]:
            task_list_id = task_list.get("list_id") or task_list.get("task_list_id") or "<unknown>"
            print(
                f"- task list {task_list_id}: "
                f"{len(task_list.get('tasks', []))} tasks"
            )
            for task in task_list.get("tasks", [])[:5]:
                readiness = task.get("readiness_state")
                readiness_text = f", {readiness}" if readiness else ""
                print(
                    f"  - {task.get('subject', '<unnamed>')} "
                    f"[{task.get('status', 'unknown')}{readiness_text}]"
                )
        if report.workflow_ledger is not None:
            print(
                "workflow: "
                f"{report.workflow_ledger.current_state} "
                f"(change={report.workflow_ledger.change_revision}, "
                f"verified={report.workflow_ledger.verified_revision}, "
                f"reviewed={report.workflow_ledger.reviewed_revision})"
            )
        print(f"changed files: {len(report.changed_files)}")
        for file_path in report.changed_files[:10]:
            print(f"- changed {file_path}")
        if report.memory_root is not None:
            print(f"memory root: {_display_path(report.memory_root)}")
            print(f"memory documents: {report.memory_documents}")
        return 0

    if args.command == "shell":
        report = asyncio.run(
            shell_demo(
                session_id=args.session_id,
                auto_approve=args.auto_approve,
                layout=layout,
            )
        )
        print("code assistant demo shell")
        print(f"session: {report.session_id}")
        print(f"workspace: {_display_path(report.workspace_root)}")
        print(f"distribution: {report.distribution}")
        print(f"default route: {report.default_model_route}")
        print(f"prompts: {report.prompt_count}")
        print(f"local commands: {len(report.local_commands)}")
        print(f"transcript: {_display_path(report.transcript_path)}")
        print(f"child run index: {_display_path(report.child_run_index_path)}")
        print(f"memory root: {_display_path(report.memory_root)}")
        print(
            "workflow: "
            f"{report.workflow_ledger.current_state} "
            f"(change={report.workflow_ledger.change_revision}, "
            f"verified={report.workflow_ledger.verified_revision}, "
            f"reviewed={report.workflow_ledger.reviewed_revision})"
        )
        if report.workflow_warnings:
            print(f"workflow warnings: {len(report.workflow_warnings)}")
            for warning in report.workflow_warnings:
                print(f"- {warning}")
        if not report.ok:
            print(f"error: {report.error_message}")
            return 2
        print("status: ok")
        return 0

    report = asyncio.run(
        run_demo(
            prompt=args.prompt,
            session_id=args.session_id,
            auto_approve=args.auto_approve,
            layout=layout,
        )
    )
    print("code assistant demo run")
    print(f"session: {report.session_id}")
    print(f"workspace: {_display_path(report.workspace_root)}")
    print(f"distribution: {report.distribution}")
    print(f"default route: {report.default_model_route}")
    print(f"task list: {report.task_list_id}")
    print(f"approvals: {len(report.approvals)}")
    for approval in report.approvals:
        verdict = "allow" if approval.approved else "deny"
        print(f"- approval {verdict}: {approval.name} {approval.summary}")
    print(f"child runs: {len(report.child_runs)}")
    for child in report.child_runs:
        print(f"- child {child['agent']}: {child['status']} -> {child['summary']}")
    print(f"transcript: {_display_path(report.transcript_path)}")
    print(f"child run index: {_display_path(report.child_run_index_path)}")
    print(f"memory root: {_display_path(report.memory_root)}")
    if report.notification_texts:
        print(f"notifications: {len(report.notification_texts)}")
    if report.final_text:
        print(f"assistant: {report.final_text}")
    print(
        "workflow: "
        f"{report.workflow_ledger.current_state} "
        f"(change={report.workflow_ledger.change_revision}, "
        f"verified={report.workflow_ledger.verified_revision}, "
        f"reviewed={report.workflow_ledger.reviewed_revision})"
    )
    if report.workflow_warnings:
        print(f"workflow warnings: {len(report.workflow_warnings)}")
        for warning in report.workflow_warnings:
            print(f"- {warning}")
    if report.workflow_gaps:
        print(f"workflow gaps: {len(report.workflow_gaps)}")
        for gap in report.workflow_gaps:
            print(f"- {gap}")
    if not report.ok:
        print(f"error: {report.error_message}")
        return 2
    print("status: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
