"""Labels on every sandbox, and the sweep that removes ones nobody is using.

Every sandbox a Trial creates carries ``plural.job``, ``plural.trial``,
``plural.execution``, and ``plural.owner``. The provider also stops it on its
own once its lifetime is up. If the process that created it dies first,
``plural runtime sweep`` finds sandboxes labeled with your owner name whose Job
is no longer running and deletes them.
"""

from __future__ import annotations

import getpass
import os
import re
import socket
import time
from collections.abc import Iterable, Mapping
from pathlib import Path

from plural.common import FrozenModel
from plural.sandbox.base import SandboxProvider
from plural.sandbox.models import SandboxSummary

OWNER_LABEL = "plural.owner"
JOB_LABEL = "plural.job"
TRIAL_LABEL = "plural.trial"
EXECUTION_LABEL = "plural.execution"
LIVE_WITHIN_SECONDS = 600
"""A Job that wrote nothing for this long is no longer running."""
_UNSAFE = re.compile(r"[^A-Za-z0-9._@-]+")


def owner_label(environ: Mapping[str, str] | None = None) -> str:
    """The name that marks sandboxes as yours: ``PLURAL_SANDBOX_OWNER``, or user@host.

    Returns:
        A label value of at most 63 safe characters.

    Examples:
        >>> owner_label({"PLURAL_SANDBOX_OWNER": "ci runner 7"})
        'ci-runner-7'
    """
    env = os.environ if environ is None else environ
    configured = env.get("PLURAL_SANDBOX_OWNER")
    if configured:
        value = configured
    else:
        try:
            user = getpass.getuser()
        except (KeyError, OSError):
            user = "unknown"
        value = f"{user}@{socket.gethostname()}"
    return _UNSAFE.sub("-", value).strip("-")[:63] or "unknown"


def trial_labels(
    *, job: str, trial: str, execution: str, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The labels one Trial execution's sandbox carries.

    Returns:
        Label names to values.

    Examples:
        >>> labels = trial_labels(
        ...     job="job-1", trial="trl-1", execution="0", environ={"PLURAL_SANDBOX_OWNER": "me"}
        ... )
        >>> labels["plural.owner"], labels["plural.trial"]
        ('me', 'trl-1')
    """
    return {
        JOB_LABEL: _UNSAFE.sub("-", job)[:63],
        TRIAL_LABEL: _UNSAFE.sub("-", trial)[:63],
        EXECUTION_LABEL: _UNSAFE.sub("-", execution)[:63],
        OWNER_LABEL: owner_label(environ),
    }


class SweepResult(FrozenModel):
    """What a sweep found and what it removed.

    Attributes:
        provider: The provider swept.
        owner: The owner label it looked for.
        orphans: Sandboxes with your label and no running Job.
        live: Sandboxes left alone because their Job is still running.
        deleted: Ids removed.
        failed: Ids that could not be removed, with the reason.
    """

    provider: str
    owner: str
    orphans: tuple[SandboxSummary, ...] = ()
    live: tuple[SandboxSummary, ...] = ()
    deleted: tuple[str, ...] = ()
    failed: dict[str, str] = {}


def live_jobs(job_roots: Iterable[Path], *, now: float | None = None) -> frozenset[str]:
    """Jobs still running in the local Job stores under ``job_roots``.

    A Job is running when it has no result yet and wrote something within
    :data:`LIVE_WITHIN_SECONDS`.

    Returns:
        Job ids.
    """
    moment = time.time() if now is None else now
    running = set()
    for root in job_roots:
        if not root.is_dir():
            continue
        for job in root.iterdir():
            if not job.is_dir() or (job / "result.json").exists():
                continue
            newest = max((item.stat().st_mtime for item in job.rglob("*")), default=0.0)
            if moment - newest <= LIVE_WITHIN_SECONDS:
                running.add(job.name)
    return frozenset(running)


async def sweep(
    provider: SandboxProvider,
    *,
    owner: str,
    live: frozenset[str] = frozenset(),
    delete: bool = False,
) -> SweepResult:
    """Find, and optionally delete, your sandboxes whose Job is not running.

    Args:
        provider: The provider to sweep.
        owner: The owner label to match, from :func:`owner_label`.
        live: Job ids still running; their sandboxes are left alone.
        delete: Delete the orphans found. Without it, only list them.

    Returns:
        What was found and removed.
    """
    found = await provider.list_sandboxes({OWNER_LABEL: owner})
    orphans = tuple(item for item in found if item.labels.get(JOB_LABEL) not in live)
    kept = tuple(item for item in found if item.labels.get(JOB_LABEL) in live)
    deleted: list[str] = []
    failed: dict[str, str] = {}
    if delete:
        for item in orphans:
            try:
                await provider.delete_sandbox(item.sandbox_id)
            except Exception as exc:  # noqa: BLE001 - reported per sandbox
                failed[item.sandbox_id] = str(exc)[:300]
            else:
                deleted.append(item.sandbox_id)
    return SweepResult(
        provider=provider.name,
        owner=owner,
        orphans=orphans,
        live=kept,
        deleted=tuple(deleted),
        failed=failed,
    )


__all__ = [
    "EXECUTION_LABEL",
    "JOB_LABEL",
    "OWNER_LABEL",
    "TRIAL_LABEL",
    "SweepResult",
    "live_jobs",
    "owner_label",
    "sweep",
    "trial_labels",
]
