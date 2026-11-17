"""Metrics: declared measurements, None as not applicable, running metrics, and ranking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from plural import (
    AgentVerifier,
    App,
    DeterministicVerifier,
    Environment,
    Episode,
    Runtime,
    State,
    Step,
    VerifierOutput,
    action,
)
from plural.execution.replay import replay_verifier
from plural.execution.trial_metrics import trial_metrics
from plural.integrity.checks import judge_probe
from plural.jobs import TrialResult, VerifierResult
from plural.metrics import (
    MetricSpec,
    aggregate_metric,
    aggregate_series,
    default_score,
    judge,
    metric_failures,
)
from plural.sandbox import DownloadedFile
from plural.verifiers import RubricCriterion, coerce_verifier_output, criterion_metrics


def _running(aggregate: str, **fields: Any) -> MetricSpec:
    return MetricSpec(name="cash", kind="running", aggregate=aggregate, **fields)


def test_a_metric_declares_what_it_needs() -> None:
    assert MetricSpec(name="ok", kind="binary").range == (0.0, 1.0)
    with pytest.raises(ValidationError, match="needs a range"):
        MetricSpec(name="tone", kind="rating")
    with pytest.raises(ValidationError, match="needs an aggregate"):
        MetricSpec(name="cash", kind="running")
    with pytest.raises(ValidationError, match="needs a threshold"):
        _running("time_to")
    with pytest.raises(ValidationError, match="only a running metric"):
        MetricSpec(name="ok", kind="binary", aggregate="final")
    with pytest.raises(ValidationError, match="lowercase"):
        MetricSpec(name="Cash On Hand", kind="number")
    assert _running("time_to", threshold=5).trial_direction == "lower"


def test_running_series_reduce_to_one_number() -> None:
    series = [(1, 10.0), (2, 30.0), (4, 20.0)]
    assert aggregate_series(series, _running("final")) == 20.0
    assert aggregate_series(series, _running("mean")) == 20.0
    assert aggregate_series(series, _running("min")) == 10.0
    assert aggregate_series(series, _running("max")) == 30.0
    # Trapezoids: (1->2) 20, (2->4) 50; over 3 steps.
    assert aggregate_series(series, _running("auc")) == pytest.approx(70 / 3)
    assert aggregate_series(series, _running("time_to", threshold=25)) == 2.0
    lower = MetricSpec(
        name="debt", kind="running", aggregate="time_to", threshold=15, direction="lower"
    )
    assert aggregate_series(series, lower) == 1.0
    assert aggregate_series(series, _running("time_to", threshold=99), steps=9) == 10.0
    assert aggregate_series([], _running("final")) is None


def test_none_is_not_applicable_and_left_out_of_aggregates() -> None:
    gate = MetricSpec(name="price_correct", kind="binary")
    row = aggregate_metric(gate, {"q1": [1.0, 1.0], "q2": [None, None], "q3": [0.0, 1.0]})
    assert (row.n, row.total) == (4, 6)
    assert row.mean == 0.75
    assert row.pass_hat_k == 0.5
    assert row.pass_at_k == 1.0
    assert row.k == 2
    assert default_score([gate], {"price_correct": None}) == 1.0


def test_a_verifier_with_only_number_metrics_needs_no_score() -> None:
    def check(episode: Episode) -> dict[str, float]:
        return {"margin_usd": 12.5, "turns_taken": 3}

    verifier = DeterministicVerifier(
        name="books",
        check=check,
        metrics=[
            {"name": "margin_usd", "kind": "number", "unit": "USD"},
            {"name": "turns_taken", "kind": "number", "direction": "lower"},
        ],
    )
    output = verifier.invoke(Episode())
    assert output.score == 1.0
    assert output.metrics == {"margin_usd": 12.5, "turns_taken": 3.0}


def test_declared_metrics_are_checked_and_scores_is_an_alias() -> None:
    specs = (
        MetricSpec(name="decision_correct", kind="binary"),
        MetricSpec(name="price_correct", kind="binary"),
        MetricSpec(name="margin_usd", kind="number"),
    )
    output = coerce_verifier_output(
        {"scores": {"decision_correct": 1, "extra": 0.5}, "metrics": {"price_correct": None}},
        verifier_name="quote-check",
        metrics=specs,
    )
    # The score is the mean of the applicable binary metrics: decision_correct only.
    assert output.score == 1.0
    assert output.metrics == {"price_correct": None, "decision_correct": 1.0}
    assert output.scores == {"extra": 0.5}
    with pytest.raises(ValueError, match="in both scores and metrics"):
        coerce_verifier_output(
            {"scores": {"margin_usd": 1}, "metrics": {"margin_usd": 2}},
            verifier_name="q",
            metrics=specs,
        )
    with pytest.raises(ValueError, match="does not declare"):
        coerce_verifier_output({"metrics": {"tone": 3}}, verifier_name="q", metrics=specs)
    with pytest.raises(ValueError, match="must be 0 or 1"):
        coerce_verifier_output(
            {"metrics": {"decision_correct": 0.5}}, verifier_name="q", metrics=specs
        )
    with pytest.raises(ValueError, match="declares none"):
        coerce_verifier_output({"score": 1, "metrics": {"x": 1}}, verifier_name="q")
    with pytest.raises(ValidationError, match="needs a score"):
        VerifierOutput()


def test_existing_verifiers_and_tasks_keep_their_hashes() -> None:
    plain = DeterministicVerifier(name="plain", check=["true"])
    payload = plain._hash_payload()
    assert "metrics" not in payload
    assert "measure" not in payload
    judge = AgentVerifier(
        name="tone",
        model="openai/gpt-5.6-luna",
        instructions="Judge the tone.",
        criteria=[RubricCriterion(name="Tone", description="1-5", min_score=1, max_score=5)],
    )
    assert "metrics" not in judge._hash_payload()
    # Its rubric still produces a rating metric, by the criterion's name.
    assert [(item.name, item.kind, item.range) for item in judge.metric_specs] == [
        ("tone", "rating", (1.0, 5.0))
    ]
    assert criterion_metrics(judge, {"Tone": 4}) == {"tone": 4.0}
    declared = plain.model_copy(update={"metrics": (MetricSpec(name="ok", kind="binary"),)})
    assert declared.content_hash != plain.content_hash


def test_a_measure_hook_needs_a_running_metric() -> None:
    with pytest.raises(ValidationError, match="declare at least one"):
        DeterministicVerifier(name="books", measure=_measure)
    verifier = DeterministicVerifier(
        name="books",
        measure="verify.py:measure",
        metrics=[{"name": "cash", "kind": "running", "aggregate": "final"}],
    )
    assert verifier.model_dump(mode="json")["measure"] == {"python": "verify.py:measure"}
    assert verifier.measure_ref == "verify.py:measure"


def test_metric_names_are_unique_across_a_tasks_verifiers() -> None:
    from test_package_execution import make_task

    def check(episode: Episode) -> dict[str, float]:
        return {"ok": 1}

    first = DeterministicVerifier(name="a", check=check, metrics=[{"name": "ok", "kind": "binary"}])
    second = first.model_copy(update={"name": "b"})
    task = make_task("one", "docker")
    from plural.verifiers import WeightedVerifier

    with pytest.raises(ValidationError, match="both produce metric 'ok'"):
        task.model_validate(
            {
                **task.model_dump(),
                "verifiers": (WeightedVerifier(verifier=first), WeightedVerifier(verifier=second)),
            }
        )


class TillState(State):
    cash: float = 10.0
    day: int = 1


class Till(App[TillState]):
    """A till that takes money and keeps a day count."""

    @action
    def sell(self, amount: float) -> str:
        """Take money."""
        self.state.cash += amount
        return "sold"

    @action
    def spend(self, amount: float) -> str:
        """Pay money out."""
        self.state.cash -= amount
        self.state.day += 1
        return "spent"

    def sim_time(self) -> float:
        return float(self.state.day)


def _measure(step: Step) -> dict[str, float]:
    return {"cash": step.current_state["cash"]}


def _broken(step: Step) -> dict[str, float]:
    if step.action == "spend":
        raise RuntimeError("no till roll")
    return {"undeclared": 1.0} if step.turn == 2 else {"other": 1.0}


def _check(episode: Episode) -> dict[str, float]:
    return {"solvent": float(min(v for _, v in episode.metric_series["cash"]) >= 0)}


RUNNING = [
    {"name": "cash", "kind": "running", "aggregate": "min"},
    {"name": "solvent", "kind": "binary"},
]


def test_the_host_samples_running_metrics_after_each_action() -> None:
    books = DeterministicVerifier(name="books", check=_check, measure=_measure, metrics=RUNNING)
    broken = DeterministicVerifier(
        name="broken",
        measure=_broken,
        metrics=[{"name": "other", "kind": "running", "aggregate": "final"}],
    )
    environment = Environment(apps=[Till()], runtime=Runtime.local())
    environment.reset(verifiers=[books, broken])
    environment.step("sell", amount=5)
    environment.step("sell", amount=1)
    observation, reward, _, _, info = environment.step("spend", amount=20)
    assert observation == {"text": "spent"}
    # A measurement is never a reward and never in what the Agent sees.
    assert reward == 0.0
    assert "cash" not in json.dumps(info)
    host = environment._host
    assert host is not None
    report = host.report()
    points = [item for item in report["metrics"] if item["verifier"] == "books"]
    assert [(p["step"], p["values"]["cash"], p["sim_time"]) for p in points] == [
        (1, 15.0, 1.0),
        (2, 16.0, 1.0),
        (3, -4.0, 2.0),
    ]
    assert all(p["source"] == "agent" for p in points)
    assert all(line["source"] == "agent" for line in report["steps"])
    failures = metric_failures(report["metric_failures"])
    assert [(item.verifier, item.steps) for item in failures] == [("broken", 2)]
    assert "undeclared" in failures[0].error


def test_each_state_line_says_whether_the_agent_or_the_environment_changed_it(
    tmp_path: Path,
) -> None:
    from plural.apps.host import AppHost

    host = AppHost(Environment(apps=[Till()], runtime=Runtime.local()), tmp_path)
    host.start()
    host.step("sell", {"amount": 1})
    lines = (tmp_path / ".plural/apps/states.jsonl").read_text().splitlines()
    assert [json.loads(line)["source"] for line in lines] == ["environment", "agent"]
    # Running metric points never land in the workspace, where the Harness could read them.
    assert not list(tmp_path.rglob("metrics.jsonl"))


def test_a_trial_gets_its_metrics_from_checks_points_and_built_ins() -> None:
    from test_package_execution import make_task

    books = DeterministicVerifier(name="books", check=_check, measure=_measure, metrics=RUNNING)
    from plural.verifiers import WeightedVerifier

    task = make_task("one", "docker").model_copy(
        update={"verifiers": (WeightedVerifier(verifier=books),)}
    )
    points = [
        {"step": 1, "verifier": "books", "values": {"cash": 15.0}},
        {"step": 2, "verifier": "books", "values": {"cash": -4.0}},
    ]
    artifacts = [
        DownloadedFile(
            path="metrics.jsonl", data="".join(json.dumps(p) + "\n" for p in points).encode()
        )
    ]
    result = VerifierResult(
        verifier_name="books",
        verifier_digest=books.content_hash,
        kind="deterministic",
        status="succeeded",
        score=0.0,
        metrics={"solvent": 0.0},
    )
    values = trial_metrics(
        task,
        [result],
        artifacts,
        cost_usd=0.01,
        latency_seconds=2.0,
        turns=2,
        stop_reason="environment_terminated",
        succeeded=True,
    )
    assert values["cash"] == -4.0
    assert values["solvent"] == 0.0
    assert values["succeeded"] == 1.0
    assert values["cost_usd"] == 0.01
    failed = trial_metrics(
        task,
        [],
        [],
        cost_usd=None,
        latency_seconds=None,
        turns=0,
        stop_reason="error",
        succeeded=False,
        checked=False,
    )
    # A check that never ran says nothing about whether its metric applied.
    assert "solvent" not in failed
    assert failed["cash"] is None
    assert failed["succeeded"] == 0.0


def test_a_task_check_reports_a_failing_binary_metric() -> None:
    result = VerifierResult.model_construct(
        verifier_name="quote-check", score=0.0, scores={}, metrics={"price_correct": 0.0}
    )
    trial = TrialResult.model_construct(
        status="succeeded", score=0.0, verifier_results=(result,), receipt=None
    )
    assert judge_probe("reference", trial, 1.0).failed_checks == ("price_correct",)


def test_replaying_a_verifier_replays_measure(tmp_path: Path) -> None:
    states = [
        {"step": 0, "state": {"till": {"cash": 10.0, "day": 1}}, "source": "environment"},
        {"step": 1, "app": "till", "action": "sell", "state": {"till": {"cash": 15.0, "day": 1}}},
        {"step": 2, "app": "till", "action": "spend", "state": {"till": {"cash": 2.0, "day": 2}}},
    ]
    steps = [
        {"kind": "step", "action": "sell", "info": {"step": 1}, "arguments": {"amount": 5}},
        {"kind": "step", "action": "spend", "info": {"step": 2}, "arguments": {"amount": 13}},
    ]
    (tmp_path / "states.jsonl").write_text("".join(json.dumps(s) + "\n" for s in states))
    (tmp_path / "steps.jsonl").write_text("".join(json.dumps(s) + "\n" for s in steps))
    books = DeterministicVerifier(name="books", check=_check, measure=_measure, metrics=RUNNING)
    replay = replay_verifier(books, tmp_path)
    assert replay.problems == []
    assert [(p["step"], p["values"]) for p in replay.metrics] == [
        (1, {"cash": 15.0}),
        (2, {"cash": 2.0}),
    ]
    assert replay.output is not None
    assert replay.output.metrics == {"solvent": 1.0}


def test_the_leaderboard_ranks_on_the_benchmarks_primary_metric() -> None:
    from types import SimpleNamespace

    from test_package_execution import make_task

    from plural.agents import AgentBinding, AgentDefinition
    from plural.execution.engine import _agent_aggregates
    from plural.jobs import BenchmarkJobSource, JobSpec
    from plural.tasks import BenchmarkDefinition
    from plural.verifiers import WeightedVerifier

    books = DeterministicVerifier(name="books", check=_check, measure=_measure, metrics=RUNNING)
    tasks = tuple(
        make_task(name, "docker").model_copy(
            update={"verifiers": (WeightedVerifier(verifier=books),)}
        )
        for name in ("one", "two")
    )
    with pytest.raises(ValidationError, match="primary_metric 'profit'"):
        BenchmarkDefinition(name="shop", tasks=tasks, primary_metric="profit")
    benchmark = BenchmarkDefinition(name="shop", tasks=tasks, primary_metric="cash")
    assert "primary_metric" in benchmark.model_dump()
    agents = tuple(
        AgentBinding(agent=AgentDefinition(name=name, model="test/model"))
        for name in ("thrifty", "spender")
    )
    spec = JobSpec(source=BenchmarkJobSource(benchmark=benchmark), agents=agents)

    def trial(agent: AgentBinding, task: str, cash: float, solvent: float | None) -> TrialResult:
        receipt = SimpleNamespace(
            agent_digest=agent.content_hash,
            task_pin=SimpleNamespace(name=task),
            attempt=0,
            trial_id=f"{agent.name}-{task}",
            cost_usd=None,
            timings={},
        )
        return TrialResult.model_construct(
            status="succeeded",
            score=1.0,
            seats=(),
            receipt=receipt,
            error_code=None,
            stop_reason="",
            metrics={"cash": cash, "solvent": solvent},
        )

    thrifty, spender = agents
    results = [
        trial(thrifty, "one", 120.0, 1.0),
        trial(thrifty, "two", 80.0, None),
        trial(spender, "one", 400.0, 0.0),
        trial(spender, "two", 300.0, 1.0),
    ]
    rows = {row.agent_name: row for row in _agent_aggregates(spec, results)}
    assert rows["thrifty"].primary_metric == "cash"
    assert rows["thrifty"].primary == 100.0
    assert rows["spender"].primary == 350.0
    solvent = rows["thrifty"].metrics["solvent"]
    assert (solvent.n, solvent.total, solvent.mean) == (1, 2, 1.0)


def test_a_gate_needs_a_target_unless_it_is_binary() -> None:
    assert MetricSpec(name="ok", kind="binary", gate=True).passes(1.0) is True
    assert MetricSpec(name="ok", kind="binary", gate=True).passes(0.0) is False
    with pytest.raises(ValidationError, match="needs a target"):
        MetricSpec(name="margin", kind="number", gate=True)
    with pytest.raises(ValidationError, match="target"):
        MetricSpec(name="margin", kind="number", target="about 3")
    # A plain number means equal to it.
    assert MetricSpec(name="turns", kind="number", target=3).target == "== 3"


def test_a_trial_passes_when_every_applicable_gate_passes() -> None:
    specs = [
        MetricSpec(name="decision", kind="binary", gate=True),
        MetricSpec(name="price", kind="binary", gate=True),
        MetricSpec(name="margin", kind="number", gate=True, target=">= 150"),
        MetricSpec(name="tone", kind="rating", range=(1, 5), target=">= 4"),
    ]
    handoff = judge(specs, {"decision": 1.0, "price": None, "margin": None, "tone": 1.0})
    assert handoff.gates == {"decision": True}
    assert handoff.passed is True
    quote = judge(specs, {"decision": 1.0, "price": 1.0, "margin": 120.0, "tone": 5.0})
    assert quote.gates == {"decision": True, "price": True, "margin": False}
    assert quote.passed is False
    # A target on a metric that is not a gate never decides a pass.
    assert "tone" not in quote.gates
    # No gate applies: not judged, never a vacuous pass.
    assert judge(specs, {"decision": None}).passed is None
    assert (
        judge([MetricSpec(name="tone", kind="rating", range=(1, 5))], {"tone": 5.0}).passed is None
    )


def test_rating_metrics_from_colliding_criterion_names_stay_apart() -> None:
    grader = AgentVerifier(
        name="reply",
        model="openai/gpt-5.6-luna",
        instructions="Judge the reply.",
        criteria=[
            RubricCriterion(name="Tone", description="1-5", min_score=1, max_score=5),
            RubricCriterion(name="tone!", description="1-5", min_score=1, max_score=5),
            RubricCriterion(name="TONE", description="1-5", min_score=1, max_score=5),
        ],
    )
    assert [item.name for item in grader.metric_specs] == ["tone", "tone_2", "tone_3"]
    rated = criterion_metrics(grader, {"Tone": 2.0, "tone!": 5.0, "TONE": 4.0})
    assert rated == {"tone": 2.0, "tone_2": 5.0, "tone_3": 4.0}
