from __future__ import annotations

import json

from demos._shared.common import (
    AllowAllPermissionService,
    demo_workspace,
    discovery_source,
    extract_tool_result,
    run_async,
    temporary_workspace,
)
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch

from weavert import AgentDefinition
from weavert.result_projections import final_assistant_text, latest_skill_outcome
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.runtime_package_protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    ContextContributorStage,
    PackageAssemblyStage,
    PackageContribution,
    RuntimePackageManifest,
)

FIXTURE_ROOT = demo_workspace("projects", "workspaces", "release_workflow")
HOOK_FRAGMENT = "package context: release-freeze is active and not blocking"
PACKAGE_NAME = "weavert-release-workflow-demo"
EXPECTED_READINESS = {
    "workspace": "release-fixture",
    "release_id": "2026.05",
    "changed_services": ["payments", "notifications"],
    "qa_status": "passed",
    "critical_findings": 0,
    "has_changelog": True,
    "release_blockers": [],
}
EXPECTED_RELEASE_SUMMARY = "release-fixture is ready"


class ReleaseFreezeContributor:
    async def collect(self, **_kwargs):
        return (HOOK_FRAGMENT,)


def _assemble_release_freeze_package(context):
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key="demo.release.freeze",
                value={"active": True, "blocking": False, "owner": context.manifest.name},
                owner=context.ownership("capability"),
            ),
        ),
        context_contributors=(
            ContextContributorBinding(
                name="demo.release.freeze.notice",
                stage=ContextContributorStage.HOOKS,
                contributor=ReleaseFreezeContributor(),
                owner=context.ownership("context_contributor"),
                order=5,
            ),
        ),
    )


def _release_package_manifest() -> RuntimePackageManifest:
    return RuntimePackageManifest(
        name=PACKAGE_NAME,
        role="capability",
        description="Provide release-freeze context for the project demo.",
        dependencies=("weavert-core",),
        assembly_entrypoint=_assemble_release_freeze_package,
    )


def _message_payloads(request) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for message in request.messages:
        if not message.text:
            continue
        try:
            payload = json.loads(message.text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _require_readiness_payload(request) -> dict[str, object]:
    for payload in _message_payloads(request):
        if payload.get("workspace") == EXPECTED_READINESS["workspace"]:
            assert payload == EXPECTED_READINESS
            return payload
    raise AssertionError("Expected the release-readiness tool payload before continuing the workflow")


def _require_skill_result_payload(request) -> dict[str, object]:
    for payload in _message_payloads(request):
        if payload.get("skill") == "release-summary":
            assert payload["mode"] == "fork"
            assert payload["agent_result"]["agent"] == "skill-writer"
            assert payload["agent_result"]["summary"] == EXPECTED_RELEASE_SUMMARY
            return payload
    raise AssertionError("Expected the release-summary skill result before rendering a verdict")


def _collect_batch(request):
    assert request.agent is not None
    assert request.agent.name == "release-reviewer"
    assert set(request.turn_context.available_tools) == {"collect_release_readiness", "skill"}
    assert request.turn_context.available_skills == ("release-summary",)
    assert HOOK_FRAGMENT in request.turn_context.hook_context
    return tool_call_batch(
        request_id="req-release-workflow-1",
        tool_name="collect_release_readiness",
        tool_input={},
        call_id="call-collect-release-readiness",
    )


def _skill_batch(request):
    assert request.agent is not None
    assert request.agent.name == "release-reviewer"
    assert HOOK_FRAGMENT in request.turn_context.hook_context
    _require_readiness_payload(request)
    return tool_call_batch(
        request_id="req-release-workflow-2",
        tool_name="skill",
        tool_input={"skill": "release-summary", "arguments": ["release-fixture"]},
        call_id="call-release-summary",
    )


def _skill_writer_batch(request):
    assert request.agent is not None
    assert request.agent.name == "skill-writer"
    assert any("release-fixture" in message.text for message in request.messages)
    assert HOOK_FRAGMENT in request.turn_context.hook_context
    return text_batch(
        request_id="req-release-workflow-3",
        text=EXPECTED_RELEASE_SUMMARY,
    )


def _verdict_batch(request):
    assert request.agent is not None
    assert request.agent.name == "release-reviewer"
    assert HOOK_FRAGMENT in request.turn_context.hook_context
    _require_readiness_payload(request)
    _require_skill_result_payload(request)
    return text_batch(
        request_id="req-release-workflow-4",
        text="release verdict: approve",
    )


def main() -> None:
    with temporary_workspace(FIXTURE_ROOT) as workspace:
        client = ScriptedModelClient(
            [
                _collect_batch,
                _skill_batch,
                _skill_writer_batch,
                _verdict_batch,
            ]
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                model_client=client,
                discovery_sources=(discovery_source(workspace),),
                extra_package_manifests=(_release_package_manifest(),),
                requested_packages={PACKAGE_NAME},
                builtins=BuiltinPackConfig(
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="skill-writer",
                            description="Draft short release summaries.",
                            prompt="Write one-sentence release summaries for the release workflow demo.",
                        )
                    ],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        messages = run_async(
            runtime.run_prompt(
                "Review whether the fixture workspace is ready to release.",
                session_id="release-workflow-demo",
                agent_name="release-reviewer",
            )
        )

        readiness = extract_tool_result(messages, "call-collect-release-readiness")
        summary_projection = latest_skill_outcome(messages, skill_name="release-summary")
        assert summary_projection is not None
        summary_result = dict(summary_projection.payload)
        freeze_capability = runtime.services.require_capability("demo.release.freeze")
        release_summary = summary_result["agent_result"]["summary"]
        final_verdict = final_assistant_text(messages)

        assert readiness == EXPECTED_READINESS
        assert freeze_capability == {"active": True, "blocking": False, "owner": PACKAGE_NAME}
        assert summary_result["skill"] == "release-summary"
        assert summary_result["mode"] == "fork"
        assert summary_result["agent_result"]["agent"] == "skill-writer"
        assert release_summary == EXPECTED_RELEASE_SUMMARY
        assert final_verdict == "release verdict: approve"
        assert [request.agent.name for request in client.requests if request.agent is not None] == [
            "release-reviewer",
            "release-reviewer",
            "skill-writer",
            "release-reviewer",
        ]

        print("demo: release workflow")
        print(f"workspace: {readiness['workspace']}")
        print(f"changed services: {', '.join(readiness['changed_services'])}")
        print(f"qa status: {readiness['qa_status']}")
        print(f"freeze status: {'active' if freeze_capability['active'] else 'inactive'}")
        print(f"release summary: {release_summary}")
        print(final_verdict)
        print("status: ok")


if __name__ == "__main__":
    main()
