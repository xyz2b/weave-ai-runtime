from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_team.assembly",
    surface="weavert.team.assembly",
    distribution_names=("weavert-team",),
    source_paths=("packages/framework-packs/capabilities/team",),
)
sys.modules[__name__] = _module
