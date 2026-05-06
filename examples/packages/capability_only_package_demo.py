from __future__ import annotations

from examples._shared.common import print_json, temporary_workspace

from weavert.runtime_kernel import RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.package_system.protocols import (
    CapabilityPackageBindingSpec,
    build_capability_only_package_manifest,
)

PACKAGE_NAME = "weavert-capability-only-demo"
CAPABILITY_KEY = "demo.release.freeze"


def main() -> None:
    with temporary_workspace() as workspace:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    build_capability_only_package_manifest(
                        name=PACKAGE_NAME,
                        capabilities=(
                            CapabilityPackageBindingSpec(
                                key=CAPABILITY_KEY,
                                value={"active": True, "owner": PACKAGE_NAME},
                            ),
                        ),
                    ),
                ),
                requested_packages={PACKAGE_NAME},
            )
        )

        capability = runtime.services.require_capability(CAPABILITY_KEY)
        owner = runtime.services.metadata["package_capability_owners"][CAPABILITY_KEY]
        manifest = runtime.services.metadata["package_manifests"][PACKAGE_NAME]

        assert capability == {"active": True, "owner": PACKAGE_NAME}
        assert owner["package_name"] == PACKAGE_NAME
        assert manifest["package_pattern"] == "capability-only"

        print("demo: capability-only package")
        print_json("capability", capability)
        print_json("capability owner", owner)
        print_json("manifest metadata", manifest)
        print("status: ok")


if __name__ == "__main__":
    main()
