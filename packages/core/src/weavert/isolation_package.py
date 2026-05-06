from __future__ import annotations

import sys

from ._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_isolation.package",
    surface="weavert.isolation_package",
    distribution_names=("weavert-isolation",),
    source_paths=("packages/framework-packs/mechanisms/isolation",),
)
sys.modules[__name__] = _module
