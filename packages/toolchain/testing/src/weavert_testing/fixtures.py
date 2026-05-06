from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from weavert.definitions import DefinitionSource
from weavert.runtime_kernel import DefinitionSourcePaths


@dataclass(frozen=True, slots=True)
class FixtureWorkspace:
    workspace_root: Path
    discovery_sources: tuple[DefinitionSourcePaths, ...]
    fixture_source: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", Path(self.workspace_root).resolve())
        object.__setattr__(self, "discovery_sources", tuple(self.discovery_sources))
        if self.fixture_source is not None:
            object.__setattr__(self, "fixture_source", Path(self.fixture_source).resolve())

    def path(self, *parts: str) -> Path:
        return self.workspace_root.joinpath(*parts)


@contextmanager
def temporary_workspace(
    template: Path | str | None = None,
    *,
    prefix: str = "weavert-test-",
) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=prefix) as tmpdir:
        workspace = Path(tmpdir).resolve()
        if template is not None:
            source = Path(template).resolve()
            shutil.copytree(source, workspace, dirs_exist_ok=True)
        yield workspace


@contextmanager
def copied_fixture_workspace(
    fixture_root: Path | str,
    *,
    prefix: str = "weavert-test-",
    source: DefinitionSource | str = DefinitionSource.PROJECT,
) -> Iterator[FixtureWorkspace]:
    fixture_path = Path(fixture_root).resolve()
    if not fixture_path.exists():
        raise FileNotFoundError(fixture_path)
    if not fixture_path.is_dir():
        raise NotADirectoryError(fixture_path)
    with temporary_workspace(fixture_path, prefix=prefix) as workspace:
        yield FixtureWorkspace(
            workspace_root=workspace,
            discovery_sources=discovery_sources(workspace, source=source),
            fixture_source=fixture_path,
        )

def discovery_source(
    workspace: Path | str,
    *,
    source: DefinitionSource | str = DefinitionSource.PROJECT,
) -> DefinitionSourcePaths:
    resolved_source = source if isinstance(source, DefinitionSource) else DefinitionSource(source)
    return DefinitionSourcePaths(resolved_source, Path(workspace).resolve() / ".weavert")

def discovery_sources(
    workspace: Path | str,
    *,
    source: DefinitionSource | str = DefinitionSource.PROJECT,
) -> tuple[DefinitionSourcePaths, ...]:
    return (discovery_source(workspace, source=source),)


__all__ = [
    "FixtureWorkspace",
    "copied_fixture_workspace",
    "discovery_source",
    "discovery_sources",
    "temporary_workspace",
]
