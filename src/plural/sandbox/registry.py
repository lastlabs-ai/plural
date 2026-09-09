"""Built-in and entry-point sandbox provider registry."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from plural.sandbox.base import SandboxProvider
from plural.sandbox.daytona import DaytonaProvider
from plural.sandbox.docker import DockerProvider
from plural.sandbox.local import LocalProvider
from plural.sandbox.models import ProviderDoctor

ENTRY_POINT_GROUP = "plural.sandbox_providers"


class ProviderRegistry:
    """Resolve built-ins and installed provider plugins lazily."""

    def __init__(self) -> None:
        self._providers: dict[str, SandboxProvider] = {
            "local": LocalProvider(),
            "docker": DockerProvider(),
            "daytona": DaytonaProvider(),
        }
        self._plugins_loaded = False

    def register(self, provider: SandboxProvider, *, replace: bool = False) -> None:
        """Register one concrete provider."""
        if provider.name in self._providers and not replace:
            raise ValueError(f"sandbox provider {provider.name!r} is already registered")
        self._providers[provider.name] = provider

    def _load_plugins(self) -> None:
        if self._plugins_loaded:
            return
        self._plugins_loaded = True
        selected = entry_points().select(group=ENTRY_POINT_GROUP)
        for point in selected:
            factory: Any = point.load()
            provider = factory() if callable(factory) else factory
            if not isinstance(provider, SandboxProvider):
                raise TypeError(
                    f"provider entry point {point.name!r} did not return SandboxProvider"
                )
            self.register(provider)

    def get(self, name: str) -> SandboxProvider:
        """Return a registered provider, loading plugins first."""
        self._load_plugins()
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"unknown sandbox provider {name!r}") from exc

    async def doctors(self, *, include_unavailable: bool = False) -> tuple[ProviderDoctor, ...]:
        """Return dynamic provider reports in stable name order."""
        self._load_plugins()
        reports = [await self._providers[name].doctor() for name in sorted(self._providers)]
        if not include_unavailable:
            reports = [item for item in reports if item.available and item.healthy]
        return tuple(reports)


default_registry = ProviderRegistry()


__all__ = ["ENTRY_POINT_GROUP", "ProviderRegistry", "default_registry"]
