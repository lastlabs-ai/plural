"""Scorecards, the held-out lock, and Plural's own model steps, without a live model."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from plural.errors import NotFoundError, PluralError
from plural.heldout import peeks, record_peek, split_heldout
from plural.model_steps import BudgetExceeded, model_step
from plural.project.layout import BENCHMARK
from plural.scorecards import (
    Label,
    Scorecard,
    calibrate,
    cohen_kappa,
    fleiss_kappa,
    meets,
    parse_target,
    rescore,
    resolve_primary,
)

ROOT = Path(__file__).resolve().parents[2]
QUOTING = ROOT / "examples" / "quoting"
CLI = Path(sys.executable).with_name("plural")


def _card(**fields: Any) -> Scorecard:
    return Scorecard.model_validate(
        {
            "name": "steel-quoting",
            "metrics": [
                {"name": "price_correct", "role": "gate"},
                {"name": "margin_usd", "role": "objective", "target": ">= 150"},
                {"name": "cost_usd", "role": "guardrail", "target": "<= 0.50"},
            ],
            "primary": "margin_usd",
            **fields,
        }
    )


def test_a_scorecard_validates_its_roles_and_targets() -> None:
    with pytest.raises(ValueError, match="primary must be an objective"):
        _card(primary="price_correct")
    with pytest.raises(ValueError, match="more than once"):
        Scorecard(name="x", metrics=[{"name": "a", "role": "gate"}] * 2)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="between"):
        parse_target("about 3")
    assert meets("between 1 5", 5) is True and meets(">= 1", None) is None
    from plural.metrics import MetricSpec

    problems = _card().problems(
        {"margin_usd": MetricSpec(name="margin_usd", kind="number")},
        produced={"quote-1": ["margin_usd"], "quote-2": ["price_correct", "margin_usd"]},
    )
    assert any("price_correct" in item and "no Verifier declares it" in item for item in problems)
    score_gate = Scorecard(name="x", metrics=[{"name": "quality", "role": "gate"}])
    assert "needs a target" in score_gate.problems({"quality": MetricSpec(name="quality")})[0]


def test_a_scorecard_hashes_without_labels_and_the_benchmark_ranks_on_its_primary() -> None:
    card = _card()
    assert card.content_hash == _card().content_hash
    # Like every revision, the hash is the content; the version is a label on it.
    assert card.content_hash == card.bumped().content_hash
    assert card.content_hash != _card(good="Right on price.").content_hash
    assert resolve_primary(card, "score") == "margin_usd"
    assert resolve_primary(card, "cost_usd") == "cost_usd"


def test_gates_skip_metrics_that_do_not_apply() -> None:
    card = _card()
    assert card.evaluate({"price_correct": 0.0}).passed is False
    handoff = card.evaluate({"price_correct": None, "margin_usd": None})
    assert handoff.gates == {} and handoff.passed is True
    limited = Scorecard.model_validate(
        {"name": "x", "metrics": [{"name": "ok", "role": "gate", "applies_to": ["rush"]}]}
    )
    assert limited.evaluate({"ok": 0.0}, task="q-1", categories=["simple"]).gates == {}
    assert limited.evaluate({"ok": 0.0}, task="q-1", categories=["rush"]).passed is False


def test_rescore_never_passes_a_failed_trial() -> None:
    rows = rescore(
        _card(),
        [
            {"trial_id": "a", "task": "t", "status": "succeeded", "metrics": {"price_correct": 1}},
            {"trial_id": "b", "task": "t", "status": "failed", "metrics": {"price_correct": 1}},
        ],
    )
    assert [row["passed"] for row in rows] == [True, False]


def test_agreement_statistics() -> None:
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 1]) == pytest.approx(0.5)
    assert cohen_kappa([1, 1], [1, 1]) == 1.0
    assert fleiss_kappa([[1, 1, 1], [0, 0, 0]]) == pytest.approx(1.0)


def test_calibration_statuses() -> None:
    card = Scorecard.model_validate(
        {
            "name": "x",
            "metrics": [{"name": "ok", "role": "gate"}, {"name": "tone", "role": "objective"}],
            "calibration": {"min_labels": 4},
        }
    )
    truth = [1, 0, 1, 0, 1]
    labels = [
        Label(scorecard="x", trial_id=f"t{i}", labeler=who, values={"ok": value, "tone": tone})
        for i, value in enumerate(truth)
        for who, tone in (("a", (1, 5)[i % 2]), ("b", (5, 1)[i % 2]))
    ]
    graders = {f"t{i}": {"ok": float(value)} for i, value in enumerate(truth)}
    result = calibrate(card, labels, graders, {})
    ok, tone = result.metric("ok"), result.metric("tone")
    assert ok is not None and ok.status == "trusted" and ok.grader_agreement == 1.0
    # Two labelers who rate tone opposite ways do not agree on what it means.
    assert tone is not None and tone.status == "undefined"
    from plural.metrics import MetricSpec

    # A grader that passes everything agrees with nobody, as a number or as a pass/fail.
    always = {key: {"ok": 1.0} for key in graders}
    for specs in ({}, {"ok": MetricSpec(name="ok", kind="binary")}):
        broken = calibrate(card, labels, always, specs)
        assert broken.metric("ok").status == "needs_work"  # type: ignore[union-attr]
    few = calibrate(card, labels[:4], graders, {})
    assert few.metric("ok").status == "not_calibrated"  # type: ignore[union-attr]


def test_a_later_label_from_the_same_person_replaces_the_earlier(tmp_path: Path) -> None:
    from plural.scorecards import read_labels, write_labels

    path = tmp_path / "labels.jsonl"
    write_labels(path, [Label(scorecard="x", trial_id="t", labeler="a", values={"ok": "n"})])
    write_labels(path, [Label(scorecard="x", trial_id="t", labeler="a", values={"ok": "y"})])
    (only,) = read_labels(path)
    assert only.values == {"ok": 1.0}


# The held-out lock.


def test_the_split_is_seeded_stratified_and_keeps_dev_tasks() -> None:
    tasks = [f"t{i}" for i in range(20)]
    groups = {task: "a" if index < 10 else "b" for index, task in enumerate(tasks)}
    held = split_heldout(tasks, 0.3, seed=7, groups=groups)
    assert held == split_heldout(tasks, 0.3, seed=7, groups=groups)
    assert sum(groups[task] == "a" for task in held) == 3
    assert sum(groups[task] == "b" for task in held) == 3
    with pytest.raises(ValueError):
        split_heldout(tasks, 1.0)


def test_peeks_are_counted(tmp_path: Path) -> None:
    record_peek(tmp_path, benchmark="quoting", job_id="job_1", purpose="eval", tasks=["q-1"])
    record_peek(tmp_path, benchmark="other", job_id="job_2", purpose="confirm", tasks=["o-1"])
    assert [item["job_id"] for item in peeks(tmp_path, "quoting")] == ["job_1"]


@pytest.fixture(scope="module")
def split_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project = tmp_path_factory.mktemp("heldout") / "quoting"
    shutil.copytree(QUOTING, project, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    run = subprocess.run(
        [
            str(CLI),
            "benchmark",
            "split",
            "quoting",
            "--heldout",
            "0.3",
            "--stratify",
            "category",
            "--seed",
            "7",
            "--json",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout[: run.stdout.rindex("}") + 1])
    assert (len(result["dev"]), len(result["heldout"])) == (42, 18)
    manifest = yaml.safe_load((project / "benchmarks/quoting/benchmark.yaml").read_text())
    assert manifest["heldout"] == result["heldout"]
    return project


def test_a_plain_benchmark_job_runs_only_dev_tasks(split_project: Path) -> None:
    from plural import Agent, Job
    from plural.project import Project, Workspace

    space = Workspace(Project.at(split_project))
    benchmark = space.get("benchmark", "quoting")
    agent = Agent(name="a", model="openai/gpt-5.6-luna")
    plain = Job(benchmark, agents=[agent])
    assert {task.task_id for task in plain.spec.tasks}.isdisjoint(benchmark.heldout)
    assert len(plain.plan.trials) == 42
    peek = Job(benchmark, agents=[agent], heldout=True)
    assert len(peek.plan.trials) == 60
    assert peek.spec.job_id != plain.spec.job_id
    # Diagnosis never sees a held-out Task, and the refusal names the confirm command.
    with pytest.raises(ValueError, match="plural fix confirm"):
        Job(benchmark, agents=[agent], heldout=True, purpose="diagnose")
    # A dev-only run hashes as runs did before held-out Tasks existed.
    assert "include_heldout" not in plain.spec.model_dump(mode="json")["source"]


def test_a_heldout_run_executes_every_task_and_counts_its_own_job(
    split_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run's snapshot keeps the held-out Tasks, and the peek names the Job that ran."""
    import plural.execution.engine
    from plural.project import Project, Workspace
    from plural.project.runs import RunRequest, plan_run, run_local

    class _Ran(Exception):
        pass

    executed: list[Any] = []

    class _Runner:
        def __init__(self, spec: Any, *_args: Any, **_kwargs: Any) -> None:
            executed.append(spec)
            raise _Ran

    monkeypatch.setattr(plural.execution.engine, "JobRunner", _Runner)
    space = Workspace(Project.at(split_project))
    request = RunRequest(benchmark="quoting", agent="quote-bot", heldout=True)
    environ = {"PLURAL_API_KEY": "unused"}
    with pytest.raises(_Ran):
        run_local(space, plan_run(space, request, environ=environ), environ=environ)
    (spec,) = executed
    assert len(spec.tasks) == 60
    (peek,) = peeks(space.project.state_dir, "quoting")
    assert peek["job_id"] == spec.job_id
    assert len(peek["tasks"]) == 18


def test_a_benchmark_without_a_split_or_scorecard_keeps_its_hash() -> None:
    from plural.project import Project, Workspace

    space = Workspace(Project.at(ROOT / "examples" / "wordle"))
    benchmark = space.get("benchmark", space.project.names(BENCHMARK)[0])
    assert benchmark.heldout == () and benchmark.scorecard is None
    # The hash the SDK computed for this Benchmark before held-out Tasks and Scorecards.
    assert benchmark.content_hash == (
        "sha256:d34aa4716b050bcd1c8e62816c2761837e2352e63f2c0f8a5a6a3419b7517334"
    )


# Plural's own model steps.


class _Studio:
    """Mints and revokes step keys the way the hosted service does, and records it."""

    project = "proj_1"

    def __init__(self, *, missing: bool = False) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.missing = missing

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        self.calls.append((method, path, kwargs.get("json")))
        if self.missing:
            raise NotFoundError("not found")
        if path == "/step-keys":
            return {"id": "key_1", "key": "plural_step_secret_value", "expires_at": "soon"}
        return {"revoked": True}


class _Model:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def chat(self, **request: Any) -> Any:
        self.requests.append(request)
        content = json.dumps(self.replies.pop(0))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=1_000, completion_tokens=200, cost=None),
        )


def test_a_step_key_is_minted_for_one_purpose_and_revoked_even_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plural.client

    built: list[dict[str, Any]] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

        def chat(self, **_request: Any) -> Any:
            raise RuntimeError("model down")

    monkeypatch.setattr(plural.client, "Client", _Client)
    studio = _Studio()
    with (
        pytest.raises(RuntimeError, match="model down"),
        model_step(
            "scorecard-draft", budget_usd=1.0, studio=studio, gateway_url="http://gw"
        ) as step,
    ):
        step.json(system="s", user="u", schema_name="x", schema={"type": "object"})
    assert studio.calls[0] == (
        "POST",
        "/step-keys",
        {"purpose": "scorecard-draft", "ttl_seconds": 900},
    )
    assert studio.calls[-1][:2] == ("POST", "/step-keys/key_1/revoke")
    # The minted key reaches only the gateway client, never a URL.
    assert built[0]["api_key"] == "plural_step_secret_value"
    assert all("plural_step_secret_value" not in path for _, path, _ in studio.calls)


def test_a_service_without_step_keys_stops_with_a_next_line() -> None:
    with (
        pytest.raises(PluralError, match="Next:"),
        model_step("scorecard-draft", budget_usd=1.0, studio=_Studio(missing=True)),
    ):
        pass


def test_a_step_refuses_a_call_over_its_budget() -> None:
    model = _Model({"ok": True})
    with (
        model_step("task-generate", budget_usd=0.0001, client=model) as step,
        pytest.raises(BudgetExceeded, match="--budget-usd"),
    ):
        step.json(system="s" * 4_000, user="u", schema_name="x", schema={"type": "object"})
    assert model.requests == []


ANALYSIS = {
    "outcomes": [
        {"text": "Win the order at a healthy margin", "source": "sop.md", "quote": "margin"}
    ],
    "hard_rules": [{"text": "Never below cost", "source": "sop.md", "quote": "never below cost"}],
    "failure_costs": [],
    "tradeoffs": [],
    "contradictions": [
        {"text": "Rush fee: 5% or 8%?", "source": "sop.md, pricing.md", "quote": "5% / 8%"}
    ],
    "suggestions": {
        "outcome": "Win the order at a healthy margin",
        "unacceptable": "Pricing below cost; a delivery date the mill can't meet",
        "uncertainty": "Hand off to a person",
        "tradeoffs": "A correct quote in under 10 minutes",
        "decision_owner": "KB (sales lead)",
    },
}
DRAFT = {
    "workflow": "Quote inbound steel RFQs.",
    "good": "A good quote is right on price and delivery and never below cost.",
    "primary": "margin_usd",
    "metrics": [
        {
            "name": "price_correct",
            "kind": "binary",
            "role": "gate",
            "target": None,
            "unit": None,
            "description": "Price matches today's.",
            "implementation": "code",
            "why": "in State",
            "logic": "",
            "existing": False,
        },
        {
            "name": "grade_in_stock",
            "kind": "binary",
            "role": "gate",
            "target": None,
            "unit": None,
            "description": "The grade quoted is one the mill stocks.",
            "implementation": "code",
            "why": "in State",
            "logic": "state.stock[grade] > 0",
            "existing": False,
        },
        {
            "name": "margin_usd",
            "kind": "number",
            "role": "objective",
            "target": ">= 150",
            "unit": "USD",
            "description": "Price minus cost.",
            "implementation": "code",
            "why": "in State",
            "logic": "",
            "existing": True,
        },
        {
            "name": "tone",
            "kind": "rating",
            "role": "objective",
            "target": None,
            "unit": None,
            "description": "Warm and clear.",
            "implementation": "judge",
            "why": "judgment",
            "logic": "",
            "existing": False,
        },
        {
            "name": "cost_usd",
            "kind": "number",
            "role": "guardrail",
            "target": "<= 0.50",
            "unit": "USD",
            "description": "Spend per quote.",
            "implementation": "code",
            "why": "built-in",
            "logic": "",
            "existing": False,
        },
    ],
}


def test_a_draft_reuses_existing_metrics_and_scaffolds_the_rest(tmp_path: Path) -> None:
    from plural.project import Project, Workspace
    from plural.project.scorecards import metric_specs
    from plural.scorecard_drafting import analyze, compose, draft_files, read_sources

    project = tmp_path / "quoting"
    shutil.copytree(QUOTING, project, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    shutil.rmtree(project / "scorecards")
    (tmp_path / "sop.md").write_text("Never quote below cost.\n", encoding="utf-8")
    sources = read_sources([tmp_path / "sop.md"])
    space = Workspace(Project.at(project))
    model = _Model(ANALYSIS, DRAFT)
    with model_step("scorecard-draft", budget_usd=1.0, client=model) as step:
        analysis = analyze(step, "Quote steel.", sources)
        draft = compose(
            step, "Quote steel.", analysis, analysis.suggestions, existing=metric_specs(space)
        )
    assert step.calls == 2 and step.spent_usd > 0
    assert "Never quote below cost" in model.requests[0]["messages"][1]["content"]
    by_name = {item.name: item for item in draft.metrics}
    assert by_name["price_correct"].existing and by_name["margin_usd"].existing
    files = draft_files(
        "steel",
        draft,
        analysis,
        analysis.suggestions,
        judge_model="openai/gpt-5.6-luna",
        accepted=True,
    )
    for relative, text in files.items():
        (project / relative).parent.mkdir(parents=True, exist_ok=True)
        (project / relative).write_text(text, encoding="utf-8")
    assert "verifiers/steel-checks/verify.py" in files
    assert "price_correct" not in files["verifiers/steel-checks/verifier.yaml"]
    assert "PLURAL-TODO: grade_in_stock" in files["verifiers/steel-checks/verify.py"]
    assert "Rush fee" in files["scorecards/steel/questions.md"]
    space = Workspace(Project.at(project))
    card = space.get("scorecard", "steel")
    assert card.owner == "KB (sales lead)" and card.primary == "margin_usd"
    assert {item.name for item in card.gates} == {"price_correct", "grade_in_stock"}
    # The project's tone Verifier already measures tone, so no judge is drafted for it.
    assert by_name["tone"].existing and "verifiers/steel-judge/verifier.yaml" not in files


def test_a_drafted_target_that_is_not_a_number_is_left_open(tmp_path: Path) -> None:
    """A live model proposed ``cost_usd <= baseline``; the draft must still be a Scorecard."""
    from plural.scorecard_drafting import analyze, compose, read_sources, to_scorecard

    loose = json.loads(json.dumps(DRAFT))
    loose["metrics"][4]["target"] = "<= baseline"
    loose["metrics"][1]["name"] = "Grade in-stock?"
    model = _Model(ANALYSIS, loose)
    with model_step("scorecard-draft", budget_usd=1.0, client=model) as step:
        analysis = analyze(step, "Quote steel.", read_sources([]))
        draft = compose(step, "Quote steel.", analysis, analysis.suggestions)
    by_name = {item.name: item for item in draft.metrics}
    assert by_name["cost_usd"].target is None
    assert "Target left open: the draft proposed '<= baseline'" in by_name["cost_usd"].description
    assert "grade_in_stock" in by_name
    card = to_scorecard("steel", draft, analysis.suggestions)
    assert card.metric("cost_usd").target is None
