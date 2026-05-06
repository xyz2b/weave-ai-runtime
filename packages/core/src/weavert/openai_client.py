from __future__ import annotations

import sys

from ._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_openai.openai_client",
    surface="weavert.openai_client",
    distribution_names=("weavert-openai",),
    source_paths=("packages/framework-packs/integrations/openai",),
)
sys.modules[__name__] = _module
