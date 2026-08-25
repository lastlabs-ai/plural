"""Routing policies and the request router.

Examples:
    >>> from plural.routing import Explicit, Fallback, LeastCost
    >>> Explicit().__class__.__name__
    'Explicit'
"""

from __future__ import annotations

from plural.routing.policies import (
    Explicit,
    Fallback,
    LeastCost,
    LowestLatency,
    ModelRoute,
    RoutingPolicy,
)
from plural.routing.router import Router

__all__ = [
    "Explicit",
    "Fallback",
    "LeastCost",
    "LowestLatency",
    "ModelRoute",
    "Router",
    "RoutingPolicy",
]
