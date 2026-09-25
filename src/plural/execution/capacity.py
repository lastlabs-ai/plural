"""How many Trials one machine can run at once.

A Trial spends most of its time waiting on the model, so the limit is set by
whichever runs out first: this machine's CPU and memory for the sandboxes it
hosts, the remote sandbox quota, or the model server when it runs here too.
A hosted model API is not a machine limit at all; it is capped only by
``PLURAL_MODEL_CONCURRENCY`` when the provider rate-limits.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from plural.jobs import JobSpec

MAX_AUTO_CONCURRENCY = 64
"""Ceiling for ``auto``; pass a number to go higher."""

LOCAL_TRIAL_MEMORY_MB = 256
DOCKER_TRIAL_MEMORY_MB = 512
DEFAULT_REMOTE_SANDBOXES = 10
LOCAL_MODEL_CONCURRENCY = 1

_MODEL_URL_NAMES = ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL")


@dataclass(frozen=True)
class ConcurrencyAdvice:
    """The recommended number of Trials at once, and what bounds it."""

    trials: int
    reason: str
    limits: dict[str, int] = field(default_factory=dict)


def recommend_concurrency(
    spec: JobSpec,
    *,
    trial_count: int,
    environ: Mapping[str, str] | None = None,
    cpu_count: int | None = None,
    memory_mb: int | None = None,
    hosted: bool = False,
) -> ConcurrencyAdvice:
    """Size a Job's concurrency from its runtimes, this machine, and its model.

    A hosted Job runs on remote sandboxes, so this machine does not bound it.

    Returns:
        The number of Trials to run at once and the limit that set it.
    """
    env = os.environ if environ is None else environ
    cpus = cpu_count or os.cpu_count() or 1
    memory = memory_mb or _physical_memory_mb()
    limits: dict[str, int] = {"trials": max(trial_count, 1)}
    for task in () if hosted else spec.tasks:
        runtime = task.environment.runtime
        provider = runtime.provider
        if provider == "local":
            by_cpu = cpus * 4
            by_memory = _share(memory, LOCAL_TRIAL_MEMORY_MB)
            _lower(limits, "local cpu", by_cpu)
            _lower(limits, "local memory", by_memory)
        elif provider == "docker":
            cpu = runtime.resources.cpu or 1.0
            ram = runtime.resources.memory_mb or DOCKER_TRIAL_MEMORY_MB
            _lower(limits, "docker cpu", max(int(cpus * 2 / cpu), 1))
            _lower(limits, "docker memory", _share(memory, ram))
        else:
            quota = _int(env.get("PLURAL_MAX_SANDBOXES")) or DEFAULT_REMOTE_SANDBOXES
            _lower(limits, f"{provider} sandboxes", quota)
    model_limit = _int(env.get("PLURAL_MODEL_CONCURRENCY"))
    if model_limit:
        _lower(limits, "model rate limit", model_limit)
    elif _uses_model(spec) and _local_model(env):
        _lower(limits, "local model server", LOCAL_MODEL_CONCURRENCY)
    _lower(limits, "auto ceiling", MAX_AUTO_CONCURRENCY)
    binding = min(limits, key=lambda name: limits[name])
    trials = limits[binding]
    return ConcurrencyAdvice(trials=trials, reason=_reason(binding, trials), limits=limits)


def _reason(binding: str, trials: int) -> str:
    if binding == "trials":
        return "every Trial at once"
    if binding == "local model server":
        return (
            "the model is served on this machine; set PLURAL_MODEL_CONCURRENCY "
            "if it batches requests"
        )
    if binding == "model rate limit":
        return "PLURAL_MODEL_CONCURRENCY"
    if binding.endswith("sandboxes"):
        return f"{binding} quota; set PLURAL_MAX_SANDBOXES to change it"
    if binding == "auto ceiling":
        return f"the auto ceiling of {trials}; pass a number to go higher"
    return f"{binding} on this machine"


def _lower(limits: dict[str, int], name: str, value: int) -> None:
    value = max(value, 1)
    limits[name] = min(limits.get(name, value), value)


def _share(memory_mb: int, per_trial_mb: int) -> int:
    return max(memory_mb // 2 // per_trial_mb, 1)


def _int(value: str | None) -> int | None:
    try:
        parsed = int(value) if value else None
    except ValueError:
        return None
    return parsed if parsed and parsed > 0 else None


def _uses_model(spec: JobSpec) -> bool:
    return any(binding.auth_mode != "none" for binding in spec.agents)


def _local_model(env: Mapping[str, str]) -> bool:
    if env.get("PLURAL_API_KEY"):
        # The gateway forwards to hosted models, wherever the gateway runs.
        return False
    return any(_loopback(env.get(name)) for name in _MODEL_URL_NAMES)


def _loopback(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).hostname or ""
    if host in {"localhost", "host.docker.internal"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _physical_memory_mb() -> int:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return 4096
    return max(int(pages * size // (1024 * 1024)), 1)
