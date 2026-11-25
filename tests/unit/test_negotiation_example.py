"""The negotiation example: party Benchmarks with rotated seats and fixed opponents.

``negotiation`` ranks ``negotiator-luna`` at two competitive haggling Tasks against
``steady-haggler``, once from each seat. ``teamwork`` seats one Agent in both seats of
a cooperative Task. Planning a Job is enough to check the seatings; the refusals are
checked by editing a copy of the project.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plural.metrics import judge
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
            "party_size: 2\n",
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


def _measured(root: Path, state: dict[str, Any]) -> dict[str, dict[str, float]]:
    spec = importlib.util.spec_from_file_location(
        "deal_books", root / "verifiers/deal-books/verify.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    market = SimpleNamespace(state=SimpleNamespace(model_dump=lambda: state))
    return module.measure(SimpleNamespace(apps={"market": market}))


@pytest.mark.parametrize(
    ("ended", "price", "verdicts"),
    [
        ("deal", 150.0, {"seat_1": True, "seat_2": True}),
        ("deal", 260.0, {"seat_1": False, "seat_2": True}),
        ("deal", 80.0, {"seat_1": True, "seat_2": False}),
        ("walked", None, {"seat_1": False, "seat_2": False}),
    ],
)
def test_each_seat_is_gated_on_a_deal_inside_its_own_limit(
    root: Path, ended: str, price: float | None, verdicts: dict[str, bool]
) -> None:
    verifier = Workspace(Project.at(root)).load(ResourceRef("verifier", "deal-books")).value
    specs = verifier.metric_specs
    gate = next(spec for spec in specs if spec.name == "fair_deal")
    assert gate.gate and gate.seat_aggregate == "min"
    state = {"value": 200.0, "cost": 100.0, "price": price, "ended": ended, "offers": []}
    fair = _measured(root, state)["fair_deal"]
    assert {seat: judge(specs, {"fair_deal": fair[seat]}).passed for seat in fair} == verdicts


def test_party_size_is_one_name_and_older_task_files_still_load(root: Path) -> None:
    task = root / "tasks/bike-deal/task.yaml"
    pinned = Workspace(Project.at(root)).load(ResourceRef("task", "bike-deal")).value
    assert pinned.party_size == 2
    _edit(task, "party_size: 2\n", "party: 2\n")
    older = Workspace(Project.at(root)).load(ResourceRef("task", "bike-deal")).value
    assert older.party_size == 2
    assert older._definition().content_hash == pinned._definition().content_hash
    _edit(task, "party: 2\n", "party: 2\nparty_size: 2\n")
    with pytest.raises(ProjectError, match="sets party and party_size"):
        Workspace(Project.at(root)).load(ResourceRef("task", "bike-deal"))
