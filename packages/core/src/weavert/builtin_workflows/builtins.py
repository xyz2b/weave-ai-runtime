from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_builtin_workflows.builtins",
    surface="weavert.builtin_workflows.builtins",
    distribution_names=("weavert-builtin-workflows",),
    source_paths=("packages/framework-packs/workflows/builtin-workflows",),
)
sys.modules[__name__] = _module
