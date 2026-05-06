from __future__ import annotations

from examples._shared.common import AllowAllPermissionService, print_json, run_async, temporary_workspace
from weavert_testing import ScriptedModelClient, text_batch

from weavert import AgentDefinition
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.package_system.protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    ContextContributorStage,
    PackageAssemblyStage,
    PackageContribution,
    RuntimePackageManifest,
)

HOOK_FRAGMENT = "package context: release-freeze is active"


class ReleaseFreezeContributor:
    async def collect(self, **_kwargs):
        return (HOOK_FRAGMENT,)


def _assemble_general_package(context):
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key="demo.release.freeze",
                value={"active": True, "owner": context.manifest.name},
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


def _general_package_batch(request):
    assert request.agent is not None
    assert request.agent.name == "main-router"
    assert HOOK_FRAGMENT in request.turn_context.hook_context
    return text_batch(
        request_id="req-package-1",
        text="general package demo complete",
    )


def main() -> None:
    with temporary_workspace() as workspace:
        client = ScriptedModelClient([_general_package_batch])
        manifest = RuntimePackageManifest(
            name="weavert-general-package-demo",
            role="capability",
            description="Publish a capability and a hook-stage context contributor.",
            dependencies=("weavert-core",),
            assembly_entrypoint=_assemble_general_package,
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                model_client=client,
                extra_package_manifests=(manifest,),
                requested_packages={"weavert-general-package-demo"},
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="main-router",
                            description="Routes the general package demo.",
                            prompt="Confirm that the package context is visible.",
                        )
                    ],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        messages = run_async(
            runtime.run_prompt("Show the package-owned context.", session_id="general-package-demo")
        )
        capability = runtime.services.require_capability("demo.release.freeze")
        request = client.requests[0]

        assert messages[-1].text == "general package demo complete"
        assert capability == {"active": True, "owner": "weavert-general-package-demo"}

        print("demo: general RuntimePackageManifest")
        print_json("capability", capability)
        print_json("hook fragments", list(request.turn_context.hook_context))
        print("status: ok")


if __name__ == "__main__":
    main()
