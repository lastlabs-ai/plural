"""Bounded scheduling for parallel Trial execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def drain(
    workers: int,
    items: Sequence[T],
    execute: Callable[[T], Awaitable[None]],
) -> None:
    """Run ``execute`` over ``items`` with at most ``workers`` in flight.

    Trials run in waves of ``workers`` instead of fanning out one task per
    planned Trial, so a bulk evaluation with thousands of Trials never
    creates thousands of waiting tasks. Error semantics match a single
    ``asyncio.gather``: the first failure propagates and the Job stops.
    """
    step = max(1, workers)
    for index in range(0, len(items), step):
        await asyncio.gather(*(execute(item) for item in items[index : index + step]))
