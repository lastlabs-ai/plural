"""The negotiation example: party Benchmarks with rotated seats and fixed opponents.

``negotiation`` ranks ``negotiator-luna`` at two competitive haggling Tasks against
``steady-haggler``, once from each seat. ``teamwork`` seats one Agent in both seats of
a cooperative Task. Planning a Job is enough to check the seatings; the refusals are
checked by editing a copy of the project.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from plural.project import Project
from plural.project.layout import ProjectError
from plural.project.resources import ResourceRef, Workspace
from plural.project.runs import RunRequest, plan_run

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "negotiation"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "negotiation"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    return root


def _seatings(root: Path, benchmark: str) -> list[tuple[str, tuple[str, ...]]]:
    plan = plan_run(
        Workspace(Project.at(root)),
        RunRequest(benchmark=benchmark, agent="negotiator-luna", attempts=1),
        environ={},
    )
    return sorted(
        (trial.task_pin.name, tuple(seat.agent_name for seat in trial.seats))
        for trial in plan.job.plan.trials
    )


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_competitive_tasks_seat_the_agent_in_every_seat_against_its_opponent(root: Path) -> None:
    assert _seatings(root, "negotiation") == [
        ("bike-deal", ("negotiator-luna", "steady-haggler")),
        ("bike-deal", ("steady-haggler", "negotiator-luna")),
        ("camera-deal", ("negotiator-luna", "steady-haggler")),
        ("camera-deal", ("steady-haggler", "negotiator-luna")),
    ]


def test_fixed_seatings_play_from_the_first_seat_only(root: Path) -> None:
    _edit(root / "benchmarks/negotiation/benchmark.yaml", "seatings: rotate", "seatings: fixed")
    assert _seatings(root, "negotiation") == [
        ("bike-deal", ("negotiator-luna", "steady-haggler")),
        ("camera-deal", ("negotiator-luna", "steady-haggler")),
    ]


def test_a_cooperative_task_without_opponents_is_self_play(root: Path) -> None:
    assert _seatings(root, "teamwork") == [("two-keys", ("negotiator-luna", "negotiator-luna"))]


def test_the_ranked_agent_cannot_also_be_an_opponent(root: Path) -> None:
    workspace = Workspace(Project.at(root))
    with pytest.raises(ProjectError, match="opponent"):
        plan_run(
            workspace,
            RunRequest(benchmark="negotiation", agent="steady-haggler", attempts=1),
            environ={},
        )


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        (
            "tasks/bike-deal/task.yaml",
            "party: 2\n",
            "",
            "must pin its party size",
        ),
        (
            "environments/market/environment.yaml",
            "isolation: isolated",
            "isolation: shared",
            "competitive, but its Environment's party is shared",
        ),
        (
            "benchmarks/negotiation/benchmark.yaml",
            "opponents:\n  - steady-haggler@1.0.0\n",
            "",
            "comparable only against the same opponents",
        ),
        (
            "benchmarks/negotiation/benchmark.yaml",
            "steady-haggler@1.0.0",
            "steady-haggler@9.9.9",
            "is at version 1.0.0",
        ),
    ],
)
def test_a_benchmark_refuses_an_unrankable_party(
    root: Path, path: str, old: str, new: str, message: str
) -> None:
    _edit(root / path, old, new)
    with pytest.raises(ProjectError) as caught:
        Workspace(Project.at(root)).load(ResourceRef("benchmark", "negotiation"))
    assert message in "\n".join(caught.value.problems or [caught.value.message])
