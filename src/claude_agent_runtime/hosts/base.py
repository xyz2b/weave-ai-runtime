from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class HostAdapter(Protocol):
    name: str

    async def startup(self) -> None: ...

    async def ready(self) -> None: ...

    async def shutdown(self) -> None: ...


class HostFactory(Protocol):
    def __call__(
        self,
        name: str,
        config: Mapping[str, Any],
        kernel: Any,
    ) -> HostAdapter: ...


@dataclass(slots=True)
class NullHostAdapter:
    name: str = "null"

    async def startup(self) -> None:
        return None

    async def ready(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class BoundHostRuntime:
    kernel: Any
    host: HostAdapter
    metadata: dict[str, Any] = field(default_factory=dict)

