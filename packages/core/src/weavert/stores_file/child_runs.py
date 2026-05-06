from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_stores_file.child_runs",
    surface="weavert.stores_file.child_runs",
    distribution_names=("weavert-stores-file",),
    source_paths=("packages/framework-packs/integrations/stores-file",),
)
sys.modules[__name__] = _module
