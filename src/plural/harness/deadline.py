"""How long a Harness's model call may wait: until the episode's own deadline.

The engine tells every Harness process how many seconds it has in
``PLURAL_STOP_SECONDS``: the Environment's ``max_seconds``, capped by the
Runtime's timeout. A model call may use whatever is left of that, so a slow
local model is limited by the episode, not by a fixed per-call timeout.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

STOP_VARIABLE = "PLURAL_STOP_SECONDS"
"""Seconds a Harness has before it is stopped, set by the engine."""

DEFAULT_EPISODE_SECONDS = 600.0
"""The Environment default for ``max_seconds``, used when nothing says otherwise."""


def episode_deadline(limits: Mapping[str, Any] | None = None) -> float:
    """The ``time.monotonic()`` at which this episode runs out of time.

    Args:
        limits: The Environment's limits, when the Harness was given them.

    Returns:
        Now plus the smaller of ``max_seconds`` and ``PLURAL_STOP_SECONDS``.
    """
    seconds = DEFAULT_EPISODE_SECONDS
    if limits and limits.get("max_seconds") is not None:
        seconds = float(limits["max_seconds"])
    stop = os.environ.get(STOP_VARIABLE)
    if stop:
        seconds = min(seconds, float(stop)) if limits else float(stop)
    return time.monotonic() + seconds


def call_timeout(deadline: float) -> float:
    """Seconds a model call may wait, which is what is left of the episode.

    Raises:
        TimeoutError: When the episode has no time left for another call.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the episode reached max_seconds before this model call")
    return remaining


__all__ = ["DEFAULT_EPISODE_SECONDS", "STOP_VARIABLE", "call_timeout", "episode_deadline"]
