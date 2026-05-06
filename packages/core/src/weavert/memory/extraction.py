from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_memory.extraction",
    surface="weavert.memory.extraction",
    distribution_names=("weavert-memory",),
    source_paths=("packages/framework-packs/capabilities/memory",),
)
sys.modules[__name__] = _module
