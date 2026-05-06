from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_devtools.tool_impls",
    surface="weavert.devtools.tool_impls",
    distribution_names=("weavert-devtools",),
    source_paths=("packages/framework-packs/workflows/devtools",),
)
sys.modules[__name__] = _module
