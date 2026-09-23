"""Model catalog and local cost computation.

Examples:
    >>> from plural.catalog import ModelCatalog, estimate_cost
    >>> isinstance(ModelCatalog().models(), list)
    True
"""

from __future__ import annotations

from plural.catalog.context import CatalogContext
from plural.catalog.models import (
    Architecture,
    ModelCatalog,
    ModelEndpoint,
    ModelPricing,
    ModelSpec,
    estimate_cost,
)

__all__ = [
    "Architecture",
    "CatalogContext",
    "ModelCatalog",
    "ModelEndpoint",
    "ModelPricing",
    "ModelSpec",
    "estimate_cost",
]
