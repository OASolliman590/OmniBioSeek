"""Built-in and user-extensible adapter registry."""

from __future__ import annotations

from collections.abc import Callable

from omnibioseek.adapters.base import RepositoryAdapter

AdapterFactory = Callable[[], RepositoryAdapter]


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, name: str, factory: AdapterFactory) -> None:
        self._factories[name.casefold()] = factory

    def create(self, name: str) -> RepositoryAdapter:
        key = name.casefold()
        if key not in self._factories:
            raise KeyError(f"unknown adapter: {name}; available: {', '.join(self.names())}")
        return self._factories[key]()

    def names(self) -> list[str]:
        return sorted(self._factories)


def default_registry() -> AdapterRegistry:
    from omnibioseek.adapters.arc import ArcAdapter
    from omnibioseek.adapters.ncbi import NcbiAdapter
    from omnibioseek.adapters.omicsdi import OmicsDIAdapter
    from omnibioseek.adapters.pubmed import PubMedAdapter

    registry = AdapterRegistry()
    registry.register("pubmed", PubMedAdapter)
    registry.register("omicsdi", OmicsDIAdapter)
    registry.register("ncbi", NcbiAdapter)
    registry.register("arc", ArcAdapter)
    return registry
