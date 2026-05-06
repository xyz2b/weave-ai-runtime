from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_planning.builtins",
    surface="weavert.planning.builtins",
    distribution_names=("weavert-planning",),
    source_paths=("packages/framework-packs/workflows/planning",),
)
sys.modules[__name__] = _module
