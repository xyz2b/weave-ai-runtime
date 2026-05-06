from __future__ import annotations

from importlib import import_module
from typing import Any


def load_object(spec: str) -> Any:
    module_name, separator, attribute_path = spec.partition(":")
    if not separator or not module_name or not attribute_path:
        raise ValueError(
            "Loader specs must use the '<module>:<attribute>' format"
        )
    value: Any = import_module(module_name)
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute)
    return value


__all__ = ["load_object"]
