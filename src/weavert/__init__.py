from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

import runtime as _runtime
from runtime import *  # noqa: F401,F403

__all__ = getattr(_runtime, "__all__", ())


class _WeaveRTAliasLoader(importlib.abc.Loader):
    def __init__(self, fullname: str, runtime_name: str) -> None:
        self._fullname = fullname
        self._runtime_name = runtime_name

    def create_module(self, spec):  # type: ignore[override]
        module = importlib.import_module(self._runtime_name)
        sys.modules[self._fullname] = module
        return module

    def exec_module(self, module) -> None:  # type: ignore[override]
        _ = module


class _WeaveRTAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):  # type: ignore[override]
        _ = path, target
        if not fullname.startswith("weavert."):
            return None
        runtime_name = "runtime." + fullname[len("weavert.") :]
        runtime_module = importlib.import_module(runtime_name)
        spec = importlib.util.spec_from_loader(
            fullname,
            _WeaveRTAliasLoader(fullname, runtime_name),
            is_package=hasattr(runtime_module, "__path__"),
        )
        if spec is not None and hasattr(runtime_module, "__path__"):
            spec.submodule_search_locations = list(runtime_module.__path__)
        return spec


def __getattr__(name: str):
    return getattr(_runtime, name)


if not any(type(finder).__name__ == "_WeaveRTAliasFinder" for finder in sys.meta_path):
    sys.meta_path.insert(0, _WeaveRTAliasFinder())
