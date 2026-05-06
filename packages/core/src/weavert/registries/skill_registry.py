from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePath

from ..definitions import SkillDefinition
from .base import DefinitionRegistry


class SkillRegistry(DefinitionRegistry[SkillDefinition]):
    definition_type = "skill"

    def __init__(self) -> None:
        super().__init__()
        self._activation_overrides: dict[str, bool] = {}

    def _on_add(self, definition: SkillDefinition) -> None:
        self._activation_overrides.setdefault(definition.name, True)

    def _on_remove(self, definition: SkillDefinition) -> None:
        self._activation_overrides.pop(definition.name, None)

    def set_active(self, name: str, active: bool) -> None:
        if name not in self._entries:
            raise KeyError(name)
        self._activation_overrides[name] = active

    def is_active(self, name: str) -> bool:
        if name not in self._entries:
            raise KeyError(name)
        return self._activation_overrides.get(name, True)

    def resolve_active(self, paths: list[str] | None = None) -> tuple[SkillDefinition, ...]:
        selected: list[SkillDefinition] = []
        for definition in self.definitions():
            if not self._activation_overrides.get(definition.name, True):
                continue
            if not definition.paths or not paths:
                selected.append(definition)
                continue
            if any(self._matches_paths(patterns=definition.paths, path=path) for path in paths):
                selected.append(definition)
        return tuple(selected)

    @staticmethod
    def _matches_paths(patterns: tuple[str, ...], path: str) -> bool:
        normalized = str(PurePath(path))
        return any(fnmatch(normalized, pattern) for pattern in patterns)

