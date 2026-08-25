"""Model catalog and local cost computation.

Examples:
    >>> from plural.catalog import ModelCatalog, estimate_cost
    >>> isinstance(ModelCatalog().models(), list)
    True
"""

from __future__ import annotations

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
    "ModelCatalog",
    "ModelEndpoint",
    "ModelPricing",
    "ModelSpec",
    "estimate_cost",
]
