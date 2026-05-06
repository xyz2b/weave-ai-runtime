from __future__ import annotations

from examples._shared.common import AllowAllPermissionService, print_json, run_async, temporary_workspace
from weavert_testing import ScriptedModelClient, text_batch

from weavert import AgentDefinition
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.runtime_package_protocols import (
    ContextContributorPackageBindingSpec,
    ContextContributorStage,
    build_context_contributor_only_package_manifest,
)

PACKAGE_NAME = "weavert-context-only-demo"
CONTRIBUTOR_NAME = "demo.release.freeze.notice"
HOOK_FRAGMENT = "package context: release-freeze is active"


class ReleaseFreezeContributor:
    async def collect(self, **_kwargs):
        return (HOOK_FRAGMENT,)


def _context_only_batch(request):
    assert request.agent is not None
    assert request.agent.name == "main-router"
    assert HOOK_FRAGMENT in request.turn_context.hook_context
    return text_batch(
        request_id="req-context-only-1",
        text="context-only package demo complete",
    )


def main() -> None:
    with temporary_workspace() as workspace:
        client = ScriptedModelClient([_context_only_batch])
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                model_client=client,
                extra_package_manifests=(
                    build_context_contributor_only_package_manifest(
                        name=PACKAGE_NAME,
                        context_contributors=(
                            ContextContributorPackageBindingSpec(
                                name=CONTRIBUTOR_NAME,
                                stage=ContextContributorStage.HOOKS,
                                contributor=ReleaseFreezeContributor(),
                                order=5,
                            ),
                        ),
                    ),
                ),
                requested_packages={PACKAGE_NAME},
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="main-router",
                            description="Routes the context-only package demo.",
                            prompt="Confirm that the package context is visible.",
                        )
                    ],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        messages = run_async(
            runtime.run_prompt("Show the package-owned context.", session_id="context-only-package-demo")
        )
        request = client.requests[0]
        binding = next(
            entry.binding
            for entry in runtime.services.context_contributor_execution_plan()
            if entry.binding.name == CONTRIBUTOR_NAME
            and entry.stage.name == ContextContributorStage.HOOKS
        )

        assert messages[-1].text == "context-only package demo complete"
        assert binding.owner.package_name == PACKAGE_NAME

        print("demo: context-contributor-only package")
        print_json("hook fragments", list(request.turn_context.hook_context))
        print_json(
            "binding owner",
            {
                "package_name": binding.owner.package_name,
                "package_role": binding.owner.package_role,
                "surface": binding.owner.surface,
                "stage": binding.stage.value,
            },
        )
        print("status: ok")


if __name__ == "__main__":
    main()
