from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_compaction.package",
    surface="weavert.compaction.package",
    distribution_names=("weavert-compaction",),
    source_paths=("packages/framework-packs/mechanisms/compaction",),
)
sys.modules[__name__] = _module
