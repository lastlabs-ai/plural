"""Run a Trial several Agents share: one Harness per seat, kept apart from each other.

Every seat's Harness runs in the same Runtime and acts on the same App host,
but each has a folder of its own under ``/workspace/seats``, a seat token only
it holds, and, where the Runtime can
(:meth:`~plural.sandbox.SandboxProvider.isolate_seats`), an OS user of its
own. Its folder is ``0700`` and is its ``HOME`` and ``TMPDIR``, so one seat
cannot read another's directions, transcript, or scratch files, nor its
process and the token in it. The host acts for the seat a token names and
refuses an action out of turn.

After the episode each seat's output is kept under ``seats/<seat>/``: its
transcript is the episode from its side of the table. The Trial's own
``episode.jsonl`` is rebuilt from the host's record alone, every step with the
seat that took it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from plural.harness.episode import EPISODE_FILE
from plural.jobs import SeatResult, VerifierResult
from plural.rewards import RewardRecord
from plural.sandbox import DownloadedFile, ExecRequest, SandboxHandle, SandboxProvider
from plural.tasks import TaskDefinition

SEATS_ROOT = "/workspace/seats"
SEAT_STAGE = "/workspace/.seat-stage"
SEAT_ARTIFACTS = "seats"

_SHARE = """
import os, sys
seats, stage, *shared = sys.argv[1:]
os.makedirs(seats, exist_ok=True)
# Each seat may make its own folder here, but none may list or remove another's.
os.chmod(seats, 0o1733)
for root in (stage, *shared):
    if not os.path.isdir(root):
        continue
    os.chmod(root, 0o755)
    for folder, names, files in os.walk(root):
        for name in names:
            os.chmod(os.path.join(folder, name), 0o755)
        for name in files:
            path = os.path.join(folder, name)
            os.chmod(path, (os.stat(path).st_mode & ~0o022) | 0o444)
"""
_TAKE = """
import os, shutil, sys
stage, target = sys.argv[1:]
os.umask(0o077)
os.mkdir(target, 0o700)
if os.path.isdir(stage):
    shutil.copytree(stage, target, dirs_exist_ok=True)
os.chmod(target, 0o700)
os.makedirs(os.path.join(target, ".tmp"), exist_ok=True)
"""
_CLEAR = "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)"
_READABLE = "import os, sys; sys.exit(0 if os.access(sys.argv[1], os.R_OK) else 1)"


def seat_workspace(seat: str) -> str:
    """The folder one seat's Harness owns."""
    return f"{SEATS_ROOT}/{seat}"


def seat_stage(seat: str) -> str:
    """Where a seat's Harness package is staged before its user copies it."""
    return f"{SEAT_STAGE}/{seat}"


def seat_environment(seat: str, token: str) -> dict[str, str]:
    """What a seat's Harness process gets beyond its Agent's own variables.

    Returns:
        Its seat token, and ``HOME`` and ``TMPDIR`` in its own folder.
    """
    from plural.apps.daemon import SEAT_TOKEN

    root = seat_workspace(seat)
    return {SEAT_TOKEN: token, "HOME": root, "TMPDIR": f"{root}/.tmp"}


class SeatSetupError(RuntimeError):
    """A seat's folder could not be prepared."""


async def _exec(
    provider: SandboxProvider,
    handle: SandboxHandle,
    command: Sequence[str],
    *,
    user: str | None = None,
) -> None:
    result = await provider.exec(
        handle,
        ExecRequest(command=tuple(command), cwd="/", env={}, timeout_seconds=120, user=user),
    )
    if result.timed_out or result.exit_code != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-500:]
        raise SeatSetupError(f"Could not prepare the seats' folders: {detail}")


async def prepare_seats(
    provider: SandboxProvider,
    handle: SandboxHandle,
    users: Mapping[str, str | None],
    *,
    shared: Sequence[str],
) -> bool:
    """Give each seat's user a private copy of its staged Harness.

    The staged packages, and the ``shared`` folders every seat reads, are
    opened read-only to all; each seat's user copies its own into a ``0700``
    folder it creates; then the stage is removed.

    Returns:
        True when every seat has a user of its own and no seat can read
        another's folder.
    """
    await _exec(provider, handle, ("python", "-c", _SHARE, SEATS_ROOT, SEAT_STAGE, *shared))
    for seat, user in users.items():
        await _exec(
            provider,
            handle,
            ("python", "-c", _TAKE, seat_stage(seat), seat_workspace(seat)),
            user=user,
        )
    await _exec(provider, handle, ("python", "-c", _CLEAR, SEAT_STAGE))
    named = [user for user in users.values() if user]
    if len(named) != len(users) or len(set(named)) != len(named) or len(users) < 2:
        return False
    seats = list(users)
    for index, seat in enumerate(seats):
        other = seats[(index + 1) % len(seats)]
        result = await provider.exec(
            handle,
            ExecRequest(
                command=("python", "-c", _READABLE, seat_workspace(other)),
                cwd="/",
                env={},
                timeout_seconds=30,
                user=users[seat],
            ),
        )
        if result.exit_code != 1:
            return False
    return True


def seat_files(seat: str, artifacts: Sequence[DownloadedFile]) -> tuple[DownloadedFile, ...]:
    """A seat's Harness output, moved under ``seats/<seat>/`` so no seat can replace another's.

    Returns:
        The artifacts with their new paths.
    """
    return tuple(
        DownloadedFile(path=f"{SEAT_ARTIFACTS}/{seat}/{item.path}", data=item.data)
        for item in artifacts
    )


def seat_steps(steps: Sequence[Mapping[str, Any]], seat: str) -> list[dict[str, Any]]:
    """The host's steps one seat took.

    Returns:
        Those steps, in order.
    """
    return [dict(item) for item in steps if item.get("seat") == seat]


def seat_scores(
    task: TaskDefinition, seats: Sequence[str], results: Sequence[VerifierResult]
) -> dict[str, float | None]:
    """Each seat's score, weighing the Verifiers as the Trial's score does.

    A Verifier that scores no seats, such as one for a cooperative Task,
    gives every seat its episode score.

    Returns:
        Seat to score, ``None`` for a seat no Verifier scored.
    """
    weights = {binding.verifier.content_hash: binding.weight for binding in task.verifiers}
    scores: dict[str, float | None] = {}
    for seat in seats:
        weighted = [
            (item.seats.get(seat, item.score), weights[item.verifier_digest])
            for item in results
            if item.verifier_digest in weights
            and item.status == "succeeded"
            and (seat in item.seats or item.score is not None)
        ]
        total = math.fsum(weight for _, weight in weighted)
        scores[seat] = (
            math.fsum(float(value) * weight for value, weight in weighted if value is not None)
            / total
            if total
            else None
        )
    return scores


def unknown_seats(seats: Sequence[str], scored: Mapping[str, float]) -> list[str]:
    """Seats a Verifier scored that the party does not have.

    Returns:
        Their names, sorted.
    """
    return sorted(set(scored) - set(seats))


def seat_results(
    seats: Sequence[str],
    *,
    agents: Mapping[str, tuple[str, str, str]],
    scores: Mapping[str, float | None],
    steps: Sequence[Mapping[str, Any]],
    ledger: Sequence[RewardRecord],
    traces: Mapping[str, str | None],
    costs: Mapping[str, float | None],
    errors: Mapping[str, str],
) -> tuple[SeatResult, ...]:
    """How each seat did.

    Args:
        seats: The party's seats, in order.
        agents: Seat to the Agent's id, name, and digest.
        scores: Seat to score, from :func:`seat_scores`.
        steps: The host's steps.
        ledger: The Trial's reward ledger.
        traces: Seat to its Harness's trace id.
        costs: Seat to its Harness's model cost.
        errors: Seat to how its Harness failed, for one that did.

    Returns:
        One result per seat, in order.
    """
    return tuple(
        SeatResult(
            seat=seat,
            agent_id=agents[seat][0],
            agent_name=agents[seat][1],
            agent_digest=agents[seat][2],
            score=scores.get(seat),
            step_reward_total=math.fsum(
                record.value * record.weight
                for record in ledger
                if record.seat == seat and record.source == "step"
            ),
            steps=len(seat_steps(steps, seat)),
            trace_id=traces.get(seat),
            artifact_root=f"{SEAT_ARTIFACTS}/{seat}",
            cost_usd=costs.get(seat),
            error_message=errors.get(seat),
        )
        for seat in seats
    )


def shared_episode(steps: Sequence[Mapping[str, Any]]) -> DownloadedFile:
    """The Trial's ``episode.jsonl`` from the host's record: every seat's steps, in order.

    Returns:
        The file.
    """
    from plural.execution.steps import dump_jsonl, merge_host_steps

    return DownloadedFile(path=EPISODE_FILE, data=dump_jsonl(merge_host_steps([], steps)))


__all__ = [
    "SEATS_ROOT",
    "SEAT_ARTIFACTS",
    "SeatSetupError",
    "prepare_seats",
    "seat_environment",
    "seat_files",
    "seat_results",
    "seat_scores",
    "seat_stage",
    "seat_steps",
    "seat_workspace",
    "shared_episode",
    "unknown_seats",
]
