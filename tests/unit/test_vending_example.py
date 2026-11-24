"""The vending-sim example: four Apps on a day clock, a daily metric, and a gate at day 60.

A policy that keeps restocking and reordering is profitable by day 60; one that
never reorders, as an Agent can't once its context loses the supplier accounts,
runs out of stock and fails the gate. Both play in-process through the App host.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from plural.apps.host import AppHost
from plural.project import Project
from plural.project.checks import _heldout_sections, plan_checks
from plural.project.resources import ResourceRef, Workspace
from plural.verifiers import DeterministicVerifier, Episode

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "vending-sim"
PRODUCTS = ("candy", "chips", "soda", "water")


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "vending-sim"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    return Workspace(Project.at(root))


def _counts(text: str, where: str) -> dict[str, int]:
    return {p: int(n) for p, n in re.findall(rf"(\w+): (\d+) {where}", text)}


def _play(
    workspace: Workspace, *, order_until: int, task_name: str = "vend-quarter"
) -> tuple[AppHost, Episode]:
    task = workspace.load(ResourceRef("task", task_name)).value
    environment = workspace.load(ResourceRef("environment", "vending")).value
    verifier = task.verifiers[0]
    assert isinstance(verifier, DeterministicVerifier)
    environment.reset(initial_state=task.initial_state, seed=11, verifiers=[verifier])
    host = environment._host
    assert host is not None
    day = 1
    while True:
        machine = _counts(host.step("machine_status", {})["observation"]["text"], "in the machine")
        storage_text = host.step("storage_status", {})["observation"]["text"]
        storage = _counts(storage_text, "in storage")
        ordered = {p: 0 for p in PRODUCTS}
        for units, product in re.findall(r"On order: (\d+) (\w+)", storage_text):
            ordered[product] += int(units)
        for product in PRODUCTS:
            if machine[product] < 25 and storage[product]:
                host.step("restock", {"product": product, "units": 40 - machine[product]})
            if day <= order_until and storage[product] + ordered[product] < 70:
                host.step(
                    "order",
                    {"supplier": "pinecrest-supply", "product": product, "units": 120},
                )
        envelope = host.step("wait", {})
        day += 1
        if envelope.get("terminated") or envelope.get("truncated"):
            break
    report = host.report()
    episode = Episode(
        expected=task.expected,
        apps={
            name: {"initial": host.initial[name], "final": host._snapshot(app)}
            for name, app in host.apps.items()
        },
    )
    assert report["clock"]["now"] == 91.0
    return host, episode


def test_a_policy_that_keeps_ordering_passes_the_day_60_gate(workspace: Workspace) -> None:
    host, episode = _play(workspace, order_until=90)
    verifier = workspace.load(ResourceRef("verifier", "vending-books")).value
    output = verifier.check(episode)
    assert output.metrics["profitable_by_day_60"] == 1.0
    assert output.score == 1.0
    points = host.report()["metrics"]
    # One net worth point per simulated day, from day 1 to the close of day 90.
    assert [point["sim_time"] for point in points] == [float(day) for day in range(1, 92)]
    assert points[-1]["values"]["net_worth_usd"] > points[0]["values"]["net_worth_usd"]
    # The suppliers' personas weren't asked; ordering doesn't need them.
    assert host.report()["personas"] == []


def test_a_policy_that_never_reorders_runs_dry_and_fails_the_gate(workspace: Workspace) -> None:
    host, episode = _play(workspace, order_until=0)
    verifier = workspace.load(ResourceRef("verifier", "vending-books")).value
    output = verifier.check(episode)
    assert output.metrics["profitable_by_day_60"] == 0.0
    assert output.metrics["stockout_days"] > 30
    assert output.score == 0.0


def test_a_supplier_answers_from_its_script_without_a_gateway(
    workspace: Workspace, tmp_path: Path
) -> None:
    environment = workspace.load(ResourceRef("environment", "vending")).value
    host = AppHost(environment, tmp_path / "host")
    host.reset(seed=11)
    reply = host.step("email", {"supplier": "harbor-wholesale", "message": "Prices?"})
    assert "Harbor Wholesale" in reply["observation"]["text"]
    assert host.report()["personas"][0]["mode"] == "scripted"
    unknown = host.step("order", {"supplier": "acme", "product": "soda", "units": 5})
    # An unknown account names no real one, so the Task is the only place to learn them.
    assert "pinecrest" not in str(unknown) and "harbor" not in str(unknown)


def test_each_seed_starts_on_another_weekday_and_sells_differently(
    workspace: Workspace,
) -> None:
    base, _ = _play(workspace, order_until=90)
    other, _ = _play(workspace, order_until=90, task_name="vend-quarter-s1")
    assert other.apps["machine"].state.start_weekday == 1
    # Day 5 is a busy Friday from a Monday start, and a quiet Saturday from a Tuesday.
    worth = [
        [point["values"]["net_worth_usd"] for point in host.report()["metrics"]]
        for host in (base, other)
    ]
    assert worth[0] != worth[1]


def test_another_run_of_customers_sells_differently_on_the_same_weekdays(
    workspace: Workspace,
) -> None:
    base, _ = _play(workspace, order_until=90)
    other, _ = _play(workspace, order_until=90, task_name="vend-quarter-h4")
    assert other.apps["machine"].state.start_weekday == 0
    assert other.apps["machine"].state.customers == 1
    worth = [
        [point["values"]["net_worth_usd"] for point in host.report()["metrics"]]
        for host in (base, other)
    ]
    assert worth[0] != worth[1]


def test_the_benchmark_ranks_on_dollars_and_holds_ten_seeds_out(
    workspace: Workspace,
) -> None:
    benchmark = workspace.load(ResourceRef("benchmark", "vending-quarter")).value
    assert benchmark.primary_metric == "net_worth_usd"
    assert benchmark.heldout == tuple(f"vend-quarter-h{index}" for index in range(1, 11))
    verifier = workspace.load(ResourceRef("verifier", "vending-books")).value
    spec = {item.name: item for item in verifier.metrics}["net_worth_usd"]
    assert (spec.direction, spec.unit) == ("higher", "USD")
    hashes = {task.content_hash for task in benchmark.tasks}
    assert len(hashes) == 14, "every seed is its own Task, so its Trials get their own seed"
    assert plan_checks(workspace, benchmark="vending-quarter").heldout == 10


def test_validate_warns_below_ten_held_out_tasks() -> None:
    (section,) = _heldout_sections(3)
    (line,) = section.lines
    assert line.mark == "warning"
    assert "needs 10 shared Tasks" in line.detail and "3 held-out Tasks" in line.detail
    assert _heldout_sections(10)[0].lines[0].mark == "ok"
    assert _heldout_sections(0) == () and _heldout_sections(None) == ()
