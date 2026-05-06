from __future__ import annotations

from pathlib import Path

from examples._shared.common import print_json, temporary_workspace

from weavert import (
    DefinitionOrigin,
    DefinitionSource,
    InvocationDefinition,
    InvocationExecutionPolicy,
    InvocationSourceKind,
    InvocationTargetKind,
    InvocationVisibilityPolicy,
    StaticInvocationProvider,
)
from weavert.runtime_kernel import RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.package_system.protocols import build_provider_only_invocation_package_manifest


def _provider() -> StaticInvocationProvider:
    return StaticInvocationProvider(
        "demo-package-commands",
        (
            InvocationDefinition(
                name="package-release-check",
                source_kind=InvocationSourceKind.PLUGIN_COMMAND,
                description="Inspect release metadata from a provider-only package.",
                visibility_policy=InvocationVisibilityPolicy(),
                execution_policy=InvocationExecutionPolicy(
                    target_kind=InvocationTargetKind.PLUGIN_COMMAND,
                    target_name="package.release_check",
                ),
                origin=DefinitionOrigin(DefinitionSource.PROJECT, path=Path(__file__)),
            ),
        ),
    )


def main() -> None:
    with temporary_workspace() as workspace:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    build_provider_only_invocation_package_manifest(
                        name="weavert-provider-only-demo",
                        provider_name="demo-package-commands",
                        provider=_provider(),
                    ),
                ),
                requested_packages={"weavert-provider-only-demo"},
            )
        )

        session = runtime.create_session(session_id="provider-only-demo", cwd=workspace)
        visible = session.visible_invocations()
        registration = next(
            entry
            for entry in runtime.services.metadata["invocation_provider_registrations"]
            if entry["provider_name"] == "demo-package-commands"
        )
        accepted = runtime.services.metadata["package_registration"]["accepted"]

        assert [entry.name for entry in visible] == ["package-release-check"]
        assert accepted[0]["package_name"] == "weavert-provider-only-demo"
        assert registration["registration_path"] == "PackageContribution.invocation_providers"

        print("demo: provider-only package")
        print(f"visible invocations: {', '.join(entry.name for entry in visible)}")
        print_json("provider registration", registration)
        print("status: ok")


if __name__ == "__main__":
    main()
