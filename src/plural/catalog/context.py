"""Create catalog-backed objects against an explicit model catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from plural.catalog.models import ModelCatalog, ModelSpec

if TYPE_CHECKING:
    from plural.agents import Agent
    from plural.verifiers import AgentVerifier


class CatalogContext:
    """Explicit factory for objects validated against an effective catalog."""

    def __init__(self, catalog: ModelCatalog | None = None) -> None:
        self.catalog = catalog or ModelCatalog()

    @classmethod
    def from_file(cls, path: str | Path) -> CatalogContext:
        """Load project model entries from JSON or YAML.

        Returns:
            A context containing bundled models plus explicit project entries.

        Raises:
            ValueError: When the file does not contain a model list.
        """
        source = Path(path)
        text = source.read_text(encoding="utf-8")
        payload = json.loads(text) if source.suffix == ".json" else yaml.safe_load(text)
        if not isinstance(payload, Mapping):
            raise ValueError(f"{source} must contain a mapping")
        catalog_payload = payload.get("catalog", payload)
        if not isinstance(catalog_payload, Mapping):
            raise ValueError("catalog must be a mapping")
        entries = catalog_payload.get("models", ())
        if not isinstance(entries, list):
            raise ValueError("catalog.models must be a list")
        return cls(ModelCatalog(entries=(ModelSpec.model_validate(item) for item in entries)))

    def agent(self, **fields: Any) -> Agent:
        """Create an Agent against this effective catalog.

        Returns:
            A validated Agent.
        """
        from plural.agents import Agent

        return Agent.from_catalog(self.catalog, **fields)

    def agent_verifier(self, **fields: Any) -> AgentVerifier:
        """Create an AgentVerifier against this effective catalog.

        Returns:
            A validated AgentVerifier.
        """
        from plural.verifiers import AgentVerifier

        return AgentVerifier.from_catalog(self.catalog, **fields)


__all__ = ["CatalogContext"]
