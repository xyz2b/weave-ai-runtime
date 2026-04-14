from __future__ import annotations

from ..definitions import AgentDefinition
from .base import DefinitionRegistry


class AgentRegistry(DefinitionRegistry[AgentDefinition]):
    definition_type = "agent"

