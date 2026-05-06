from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_stores_file.package",
    surface="weavert.stores_file.package",
    distribution_names=("weavert-stores-file",),
    source_paths=("packages/framework-packs/integrations/stores-file",),
)
sys.modules[__name__] = _module
