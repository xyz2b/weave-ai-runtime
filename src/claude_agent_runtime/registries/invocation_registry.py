from __future__ import annotations

from typing import Sequence

from ..definitions import InvocationDefinition, InvocationProvider, InvocationResolutionContext, ResolvedInvocationCatalog


class InvocationRegistry:
    def __init__(self, providers: Sequence[InvocationProvider] = ()) -> None:
        self._providers: dict[str, InvocationProvider] = {}
        for provider in providers:
            self.register_provider(provider)

    def register_provider(self, provider: InvocationProvider) -> InvocationProvider:
        self._providers[provider.name] = provider
        return provider

    def remove_provider(self, name: str) -> InvocationProvider | None:
        return self._providers.pop(name, None)

    def providers(self) -> tuple[InvocationProvider, ...]:
        return tuple(self._providers.values())

    def definitions(self) -> tuple[InvocationDefinition, ...]:
        collected: dict[str, InvocationDefinition] = {}
        for provider in self._providers.values():
            for definition in provider.list_invocations():
                collected[definition.name] = definition
        return tuple(collected.values())

    def resolve(self, context: InvocationResolutionContext) -> ResolvedInvocationCatalog:
        from ..invocation_catalog import resolve_invocation_catalog

        return resolve_invocation_catalog(self.definitions(), context)


__all__ = ["InvocationRegistry"]
