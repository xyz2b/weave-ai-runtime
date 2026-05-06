from __future__ import annotations

from pathlib import Path

from examples._shared.common import temporary_workspace

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
from weavert.runtime_package_protocols import build_provider_only_invocation_package_manifest

PACKAGE_NAME = "weavert-provider-only-demo"
PROVIDER_NAME = "demo-package-commands"
INVOCATION_NAME = "package-release-check"


def _provider() -> StaticInvocationProvider:
    return StaticInvocationProvider(
        PROVIDER_NAME,
        (
            InvocationDefinition(
                name=INVOCATION_NAME,
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


def _manifest():
    return build_provider_only_invocation_package_manifest(
        name=PACKAGE_NAME,
        provider_name=PROVIDER_NAME,
        provider=_provider(),
    )


def _resolved_order(runtime) -> list[str]:
    metadata = runtime.services.metadata["resolved_active_package_graph_provenance"]
    return list(metadata["resolved_order"])


def _visible_invocation_names(runtime, *, session_id: str, cwd: Path) -> list[str]:
    session = runtime.create_session(session_id=session_id, cwd=cwd)
    return [entry.name for entry in session.visible_invocations()]


def _format_names(names: list[str]) -> str:
    return ", ".join(names) if names else "none"


def main() -> None:
    with temporary_workspace() as workspace:
        inactive_runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(_manifest(),),
            )
        )
        active_runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(_manifest(),),
                requested_packages={PACKAGE_NAME},
            )
        )

        accepted = inactive_runtime.services.metadata["package_registration"]["accepted"]
        inactive_order = _resolved_order(inactive_runtime)
        active_order = _resolved_order(active_runtime)
        inactive_visible = _visible_invocation_names(
            inactive_runtime,
            session_id="package-activation-inactive",
            cwd=workspace,
        )
        active_visible = _visible_invocation_names(
            active_runtime,
            session_id="package-activation-active",
            cwd=workspace,
        )

        assert accepted[0]["package_name"] == PACKAGE_NAME
        assert inactive_order == ["weavert-core"]
        assert inactive_visible == []
        assert active_order == ["weavert-core", PACKAGE_NAME]
        assert active_visible == [INVOCATION_NAME]

        print("demo: package activation")
        print(f"accepted package: {accepted[0]['package_name']}")
        print(f"inactive order: {', '.join(inactive_order)}")
        print(f"inactive visible invocations: {_format_names(inactive_visible)}")
        print(f"active order: {', '.join(active_order)}")
        print(f"active visible invocations: {_format_names(active_visible)}")
        print("status: ok")


if __name__ == "__main__":
    main()
