from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RuntimeErrorCode(StrEnum):
    VALIDATION = "validation_error"
    PERMISSION = "permission_error"
    CONFLICT = "registry_conflict"
    DISCOVERY = "definition_discovery_error"
    CONFIG = "configuration_error"
    MODEL = "model_error"
    TRANSCRIPT = "transcript_error"


@dataclass(slots=True)
class RuntimeFailure(Exception):
    code: RuntimeErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class DefinitionValidationError(RuntimeFailure):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(RuntimeErrorCode.VALIDATION, message, dict(details))


class DefinitionLoadError(RuntimeFailure):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(RuntimeErrorCode.DISCOVERY, message, dict(details))


class RegistryConflictError(RuntimeFailure):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(RuntimeErrorCode.CONFLICT, message, dict(details))


class PermissionDeniedError(RuntimeFailure):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(RuntimeErrorCode.PERMISSION, message, dict(details))

