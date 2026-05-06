from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_team.builtins",
    surface="weavert.team.builtins",
    distribution_names=("weavert-team",),
    source_paths=("packages/framework-packs/capabilities/team",),
)
sys.modules[__name__] = _module
