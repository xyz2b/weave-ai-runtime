from __future__ import annotations

import sys

from .._optional_compat import load_optional_module

_module = load_optional_module(
    "weavert_hosts_reference.reference",
    surface="weavert.hosts.reference",
    distribution_names=("weavert-hosts-reference",),
    source_paths=("packages/framework-packs/integrations/hosts-reference",),
)
sys.modules[__name__] = _module
