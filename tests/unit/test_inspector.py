"""The Inspector: evidence over a real local Job, signals, Findings, revise, report, faults."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_forks import GUESSES, ROOT, _plural, _WordleModel

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def failed_job(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """A Wordle Job where the scripted model fails nymph and solves crane."""
    import os
    import threading
    from http.server import ThreadingHTTPServer

    root = tmp_path_factory.mktemp("inspector")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WordleModel)
    _WordleModel.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    project = root / "wordle"
    shutil.copytree(ROOT / "examples" / "wordle", project)
    folder = project / "agents" / "scripted"
    folder.mkdir()
    (folder / "agent.yaml").write_text(
        "# Agent: plays the same guesses every time.\n"
        "name: scripted\nversion: 1.0.0\nmodel: test/wordle\ninstructions: Play Wordle.\n"
        f"endpoint: {url}\nendpoint_key: WORDLE_MODEL_KEY\n",
        encoding="utf-8",
    )
    bench = project / "benchmarks" / "two"
    bench.mkdir(parents=True)
    (bench / "README.md").write_text("# two\n\nOne solved, one not.\n", encoding="utf-8")
    (bench / "benchmark.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "two",
                "version": "1.0.0",
                "description": "One word in the guess list, one not.",
                "purpose": "Gives the Inspector one failed Trial and one passed.",
                "tasks": ["crane", "nymph"],
                "scoring": {"description": "Share of words solved."},
            }
        ),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
    }
    env.update({"PLURAL_CONFIG_HOME": str(root / "config"), "WORDLE_MODEL_KEY": "unused"})
    try:
        run = _plural(project, env, "run", "-b", "two", "-a", "scripted", "--yes")
        trials = {item["task"]: item["trial_id"] for item in run["trials"]}
        yield {"project": project, "env": env, "job_id": run["job_id"], "trials": trials}
    finally:
        server.shutdown()


def _evidence(job: dict[str, Any]) -> Any:
    from plural.inspector.evidence import JobEvidence

    return JobEvidence(job["project"], job["job_id"])


def test_evidence_reads_the_failed_trial(failed_job: dict[str, Any]) -> None:
    evidence = _evidence(failed_job)
    failed = evidence.failed()
    assert [item.trial_id for item in failed] == [failed_job["trials"]["nymph"]]
    trial = failed[0]
    overview = trial.overview()
    assert overview["task"] == "nymph" and overview["passed"] is False
    steps = trial.step_view(1, 6)
    assert [item["arguments"]["word"] for item in steps] == list(GUESSES)
    context = trial.context_at(3)
    assert context["messages"] and context["input_tokens"] == 9
    assert sum(item["role"] == "tool" for item in context["messages"]) == 2
    diff = trial.state_diff(0, 2)
    assert diff and "nymph" not in json.dumps(trial.step_view(1, 6))
    assert trial.task_view()["expected"]["note"]
    assert evidence.compare(failed_job["trials"]["nymph"], failed_job["trials"]["crane"])


def test_evidence_never_shows_a_held_out_trial(failed_job: dict[str, Any]) -> None:
    from plural.project.layout import ProjectError

    evidence = _evidence(failed_job)
    evidence.heldout_tasks = {"nymph"}
    evidence.__dict__.pop("trials", None)
    assert failed_job["trials"]["nymph"] not in evidence.trials
    with pytest.raises(ProjectError):
        evidence.trial(failed_job["trials"]["nymph"])


def test_signals_built_in_and_from_the_project(failed_job: dict[str, Any]) -> None:
    from plural.inspector import signals

    trial = _evidence(failed_job).failed()[0]
    assert {"unknown_action", "failed_gate", "stop_reason"} <= set(signals.registered())
    assert isinstance(signals.run_signals(trial), list)
    folder = failed_job["project"] / "inspector"
    folder.mkdir(exist_ok=True)
    (folder / "signals.py").write_text(
        "from plural.inspector.signals import Signal, signal\n\n"
        "@signal('six_guesses')\n"
        "def six(trial):\n"
        "    if len(trial.steps) >= 6:\n"
        "        yield Signal('six_guesses', 6, 'used every guess')\n\n"
        "@signal('broken')\n"
        "def broken(trial):\n"
        "    raise RuntimeError('boom')\n",
        encoding="utf-8",
    )
    try:
        signals.load_project_signals(failed_job["project"])
        found = {item.name: item for item in signals.run_signals(trial)}
        assert found["six_guesses"].step == 6
        assert "boom" in found["signal_failed"].detail
    finally:
        shutil.rmtree(folder)
        signals._SIGNALS.pop("six_guesses", None)
        signals._SIGNALS.pop("broken", None)


def test_finding_status_is_computed_from_the_forks() -> None:
    from plural.inspector.findings import ForkTest, finding_status

    def test(verdict: str, candidate: float, control: float, high: float | None = None) -> ForkTest:
        return ForkTest(
            test_id="X1",
            job_id="job_1",
            step=2,
            verdict=verdict,  # type: ignore[arg-type]
            candidate=candidate,
            control=control,
            high=high,
            candidates=4,
            controls=4,
        )

    assert finding_status(()) == "inferred"
    assert finding_status((test("likely_matters", 1.0, 0.0),)) == "confirmed"
    assert finding_status((test("likely_matters", 0.0, 1.0, high=-0.25),)) == "refuted"
    assert finding_status((test("no_clear_effect", 0.0, 0.0, high=0.0),)) == "refuted"
    assert finding_status((test("no_clear_effect", 0.5, 0.0, high=1.0),)) == "inconclusive"
    assert finding_status((test("no_clear_effect", 0.5, 0.5),)) == "refuted"
    assert finding_status((test("too_few", 1.0, 0.0),)) == "inconclusive"
    beaten = (test("likely_matters", 1.0, 0.0),)
    assert finding_status(beaten, agent_cause=False) == "inferred"
    other = (test("likely_matters", 1.0, 0.0).model_copy(update={"gates": ("decision_correct",)}),)
    assert finding_status(other, gates=("price_correct",)) == "inferred"
    assert finding_status(other, gates=("decision_correct",)) == "confirmed"


def _app(job: dict[str, Any], **state: Any) -> Any:
    from plural.inspector.app import InspectorApp

    app = InspectorApp(name="inspector")
    app.reset(
        {
            "project": str(job["project"]),
            "job_id": job["job_id"],
            "trial_id": job["trials"]["nymph"],
            "depth": "quick",
            **state,
        }
    )
    return app


def test_record_finding_checks_its_cause_evidence_and_forks(failed_job: dict[str, Any]) -> None:
    app = _app(failed_job)
    assert app.overview()["forks_allowed"] is False
    with pytest.raises(ValueError, match="quick inspection runs no forks"):
        app.fork(step=2, instructions="Guess nymph.")
    with pytest.raises(ValueError, match="cause must be one of"):
        app.record_finding(cause="luck", summary="s", evidence=["e"], critical_step=6)
    with pytest.raises(ValueError, match="evidence"):
        app.record_finding(cause="model", summary="s", evidence=[], critical_step=6)
    with pytest.raises(ValueError, match="No fork X9"):
        app.record_finding(
            cause="model", summary="s", evidence=["e"], critical_step=6, tests=["X9"]
        )
    assert not app.terminated()
    with pytest.raises(ValueError, match="didn't fail"):
        app.record_finding(cause="model", summary="s", evidence=["e"], gates=["solved"])
    app.record_finding(
        cause="instructions",
        summary="It never guessed nymph.",
        evidence=["six guesses, none nymph"],
        critical_step=6,
        more=True,
    )
    assert not app.terminated()
    with pytest.raises(ValueError, match="already recorded"):
        app.record_finding(cause="instructions", summary="s", evidence=["e"], critical_step=6)
    app.record_finding(
        cause="grader",
        summary="The answer key wanted a word not in the list.",
        evidence=["expected nymph"],
    )
    assert [item["status"] for item in app.state.findings] == ["inferred", "inferred"]
    assert app.terminated()


def test_entity_names_come_from_collections_named_fields_and_identifiers() -> None:
    from plural.inspector.evidence import entity_names
    from plural.inspector.findings import Remedy

    state = {
        "storage": {"units": {"soda": 30, "water": 30}, "status": "open"},
        "machine": {"last_day": {"revenue": 28.5, "sold": {"soda": 6}}},
        "suppliers": {
            "open_orders": [{"supplier": "harbor-wholesale", "product": "soda", "units": 60}],
            "threads": {"Dana Reyes": ["Can you deliver Monday?"]},
        },
        "bank": {"account_id": "acct-1042", "note": "settled"},
    }
    names = entity_names(state)
    assert names >= {"soda", "water", "harbor-wholesale", "Dana Reyes", "acct-1042"}
    # Fields are never entities, nor a record's keys, nor free text in a field that
    # names nothing.
    assert not names & {"storage", "units", "open_orders", "supplier", "status", "open", "note"}
    assert not names & {"last_day", "revenue", "sold"}
    assert entity_names({"secret": "nymph"}) == set()
    assert entity_names({"secret": "nymph"}, authored=True) == {"nymph"}

    remedy = Remedy(
        instructions="Reorder from Harbor-Wholesale before stock runs out.",
        tool_overrides={"message": {"description": "Write to acct-1042."}},
        harness_config={
            "context": {
                "strategy": "summarize",
                "max_tokens": 8000,
                "summary_instructions": "Keep soda.",
            }
        },
    )
    found = {"harbor-wholesale", "acct-1042", "soda", "water", "dana reyes"}
    assert remedy.names(found) == ["acct-1042", "harbor-wholesale", "soda"]
    assert Remedy(instructions="Keep sodas and watering cans.").names(found) == []


def test_a_remedy_that_names_the_tasks_own_entities_is_refused(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.inspector.app import CREDENTIAL

    app = _app(failed_job)
    trial = app._trial()
    specific = app._job.task_entities(trial)
    assert "nymph" in specific
    # crane is the other Task's word; the Agent's own guesses are not the Task's.
    assert "crane" not in specific and "wordle" not in specific
    with pytest.raises(ValueError, match="names 'nymph'.*Task nymph alone"):
        app.record_finding(
            cause="instructions",
            summary="It never guessed the word.",
            evidence=["six guesses"],
            critical_step=6,
            instructions="Play Wordle. If the word ends in -ymph, guess NYMPH.",
        )
    with pytest.raises(ValueError, match="names 'nymph'"):
        app.record_finding(
            cause="instructions",
            summary="s",
            evidence=["e"],
            critical_step=6,
            note="Tell it the answer is nymph.",
        )
    assert not app.state.findings

    forking = _app(failed_job, depth="standard")
    monkeypatch.setenv(CREDENTIAL, "unused")
    with pytest.raises(ValueError, match="names 'nymph'"):
        forking.fork(step=2, instructions="Guess nymph.")
    assert not forking.state.tests

    app.record_finding(
        cause="instructions",
        summary="It never used the letters the feedback ruled in.",
        evidence=["six guesses"],
        critical_step=6,
        instructions="Play Wordle. Each guess must keep every letter marked present.",
    )
    assert app.state.findings[0]["remedy"]["instructions"].startswith("Play Wordle.")


def test_a_model_finding_needs_a_stronger_model_that_beat_the_controls(
    failed_job: dict[str, Any],
) -> None:
    app = _app(failed_job)
    own = app._trial().agent.model

    def fork(test_id: str, **remedy: Any) -> None:
        app.state.tests.append(
            {
                "test_id": test_id,
                "job_id": "job_fork",
                "step": 0,
                "remedy": remedy,
                "verdict": "likely_matters",
                "candidate": 1.0,
                "control": 0.0,
                "candidates": 4,
                "controls": 4,
            }
        )

    fork("X1", model=own)
    fork("X2", model="openai/gpt-5.6-luna", instructions="Guess nymph.")
    fork("X3", instructions="Use each clue.")
    for tests in ([], ["X1"], ["X2"], ["X3"]):
        with pytest.raises(ValueError, match="stronger model beat the controls"):
            app.record_finding(cause="model", summary="s", evidence=["e"], tests=tests)
    fork("X4", model="openai/gpt-5.6-luna" if own != "openai/gpt-5.6-luna" else "x/y")
    app.state.tests[-1]["verdict"] = "no_clear_effect"
    with pytest.raises(ValueError, match="keep looking"):
        app.record_finding(cause="model", summary="s", evidence=["e"], tests=["X4"])
    app.state.tests[-1]["verdict"] = "likely_matters"
    assert app.record_finding(cause="model", summary="s", evidence=["e"], tests=["X4"]) == (
        "Recorded: model, confirmed."
    )


def test_a_confirmed_finding_ships_the_remedy_its_fork_tested(
    failed_job: dict[str, Any],
) -> None:
    context = {"strategy": "summarize", "max_tokens": 8000, "summary_instructions": "Keep it."}
    tested = {"harness_config": {"context": context}}

    def inspector() -> Any:
        app = _app(failed_job)
        app.state.tests.append(
            {
                "test_id": "X1",
                "job_id": "job_fork",
                "step": 2,
                "remedy": tested,
                "verdict": "likely_matters",
                "candidate": 0.75,
                "control": 0.0,
                "low": 0.25,
                "high": 1.0,
                "candidates": 4,
                "controls": 4,
            }
        )
        return app

    app = inspector()
    with pytest.raises(ValueError, match="This remedy wasn't tested: X1"):
        app.record_finding(
            cause="context",
            summary="The summary lost the clues.",
            evidence=["step 3"],
            tests=["X1"],
            instructions="Remember every clue.",
        )
    assert app.record_finding(
        cause="context", summary="s", evidence=["e"], tests=["X1"], note="Keep the clues."
    ) == ("Recorded: context, confirmed.")
    recorded = app.state.findings[0]["remedy"]
    assert recorded["harness_config"]["context"]["summary_instructions"] == "Keep it."
    assert recorded["instructions"] is None and recorded["note"] == "Keep the clues."

    again = inspector()
    again.record_finding(
        cause="context", summary="s", evidence=["e"], tests=["X1"], context=context
    )
    assert again.state.findings[0]["remedy"]["harness_config"] == recorded["harness_config"]


def test_forks_may_switch_only_to_the_allowed_models(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.inspector.app import CREDENTIAL

    app = _app(failed_job, depth="standard", fork_models=["openai/gpt-5.6-luna"])
    assert app.overview()["fork_models"] == ["openai/gpt-5.6-luna"]
    monkeypatch.setenv(CREDENTIAL, "test")
    with pytest.raises(ValueError, match="Forks may run openai/gpt-5.6-luna, not openai/gpt"):
        app.fork(step=0, model="openai/gpt-5.6")
    assert _app(failed_job).overview()["fork_models"] == "any"


def test_every_failed_gate_needs_a_finding(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.inspector.evidence import TrialEvidence

    row = TrialEvidence.row
    monkeypatch.setattr(
        TrialEvidence,
        "row",
        lambda self: {**row(self), "failed_gates": ["price_correct", "delivery_feasible"]},
    )
    app = _app(failed_job)
    with pytest.raises(ValueError, match="No Finding explains delivery_feasible"):
        app.record_finding(
            cause="instructions", summary="s", evidence=["e"], gates=["price_correct"]
        )
    app.record_finding(
        cause="instructions", summary="s", evidence=["e"], gates=["price_correct"], more=True
    )
    app.state.tests.append(
        {
            "test_id": "X1",
            "job_id": "job_fork",
            "step": 3,
            "gates": ["delivery_feasible"],
            "verdict": "likely_matters",
            "candidate": 1.0,
            "control": 0.0,
            "low": 0.5,
            "high": 1.0,
            "candidates": 4,
            "controls": 4,
            "outcomes": {"candidate": {"passed": 0, "above_cost": 4}},
        }
    )
    with pytest.raises(ValueError, match="No Finding explains above_cost"):
        app.record_finding(
            cause="tools", summary="s", evidence=["e"], gates=["delivery_feasible"], tests=["X1"]
        )
    app.record_finding(
        cause="tools",
        summary="s",
        evidence=["e"],
        gates=["delivery_feasible"],
        tests=["X1"],
        more=True,
    )
    app.record_finding(cause="grader", summary="s", evidence=["e"], gates=["above_cost"])
    assert [item["gates"] for item in app.state.findings] == [
        ["price_correct"],
        ["delivery_feasible"],
        ["above_cost"],
    ]
    assert app.terminated()


def test_finding_check_grades_against_the_answer_key() -> None:
    import importlib.util

    from plural import Episode

    path = ROOT / "src/plural/inspector/project/verifiers/finding-check/verify.py"
    spec = importlib.util.spec_from_file_location("finding_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    finding = {
        "cause": "tools",
        "critical_step": 4,
        "status": "confirmed",
        "summary": "check_schedule was hidden",
        "evidence": ["no schedule call"],
    }
    expected = {"cause": "tools", "critical_steps": [4, 5], "terms": ["schedule"]}
    other = {**finding, "cause": "model"}
    episode = Episode(state={"mode": "inspect", "findings": [other, finding]}, expected=expected)
    right = module.check(episode)
    assert right.score == 1.0 and right.evidence
    wrong = module.check(Episode(state={"mode": "inspect", "findings": [other]}, expected=expected))
    assert wrong.score == 0.0 and wrong.metrics["cause_correct"] == 0.0
    assert module.check(Episode(state={"mode": "inspect"}, expected=expected)).score == 0.0
    task = {**finding, "cause": "task", "critical_step": None}
    keyed = {"cause": "task", "critical_steps": [1], "terms": ["schedule"]}
    unstepped = module.check(Episode(state={"mode": "inspect", "findings": [task]}, expected=keyed))
    assert unstepped.score == 1.0 and unstepped.metrics["step_correct"] is None


def _save(job: dict[str, Any], **finding: Any) -> None:
    from plural.inspector.findings import InspectionRecord, now, number_findings, save_findings

    draft = {
        "job_id": job["job_id"],
        "trial_id": job["trials"]["nymph"],
        "task": "nymph",
        "agent": "scripted",
        "critical_step": 6,
        "cause": "instructions",
        "summary": "Nothing told it to use the feedback.",
        "evidence": ["it guessed the same list regardless of feedback"],
        "forks": [
            {
                "test_id": "X1",
                "job_id": "job_fork",
                "step": 0,
                "verdict": "likely_matters",
                "candidate": 0.75,
                "control": 0.0,
                "candidates": 4,
                "controls": 4,
            }
        ],
        "status": "confirmed",
        "remedy": {"instructions": "Play Wordle. Use each clue."},
        **finding,
    }
    record = InspectionRecord(
        job_id=job["job_id"],
        inspected_at=now(),
        inspector_job_id="job_inspector",
        depth="standard",
        failed=1,
        findings=number_findings(job["job_id"], [draft]),
    )
    save_findings(job["project"] / ".plural" / "jobs" / job["job_id"], record)


def test_breakdown_counts_a_trial_once_per_cause(capsys: pytest.CaptureFixture[str]) -> None:
    from plural.inspector.findings import InspectionRecord, breakdown, now, number_findings

    def draft(trial: str, cause: str) -> dict[str, Any]:
        return {
            "job_id": "job_a",
            "trial_id": trial,
            "task": trial,
            "agent": "bot",
            "cause": cause,
            "summary": "s",
            "evidence": ["e"],
            "status": "inferred",
        }

    drafts = [draft("t1", "instructions"), draft("t1", "tools"), draft("t2", "instructions")]
    record = InspectionRecord(
        job_id="job_a",
        inspected_at=now(),
        inspector_job_id="job_i",
        depth="quick",
        failed=3,
        findings=number_findings("job_a", drafts),
        uninspected=("t3",),
    )
    rows = {row.cause: row for row in breakdown(record)}
    assert rows["instructions"].trial_ids == ("t1", "t2")
    assert rows["tools"].share == pytest.approx(1 / 3)
    assert rows["uninspected"].findings == 1

    from plural.cli.inspector_commands import _print_inspection

    _print_inspection(record)
    printed = capsys.readouterr().out
    assert printed.startswith("Inspected 3 of 3 failed Trials")
    assert "F2 t1 t1: tools, inferred, no critical step" in printed


def test_revise_applies_a_confirmed_finding_as_a_new_version(
    failed_job: dict[str, Any], tmp_path: Path
) -> None:
    from plural.inspector.revise import revise_agent
    from plural.project import Project, Workspace
    from plural.project.layout import ProjectError

    project = tmp_path / "wordle"
    shutil.copytree(failed_job["project"], project)
    job = {**failed_job, "project": project}
    space = Workspace(Project.at(project))
    _save(job, status="inferred", forks=[])
    with pytest.raises(ProjectError, match="not confirmed"):
        revise_agent(space, "scripted", "F1")
    _save(job, cause="grader")
    with pytest.raises(ProjectError, match="Verifier's code"):
        revise_agent(space, "scripted", "F1")
    _save(job)
    revision = revise_agent(space, "scripted", "F1")
    assert (revision.previous, revision.version) == ("1.0.0", "1.1.0")
    manifest = (project / "agents/scripted/agent.yaml").read_text()
    assert manifest.startswith("# Agent: plays the same guesses")
    assert yaml.safe_load(manifest)["instructions"] == "Play Wordle. Use each clue."
    changelog = (project / "agents/scripted/CHANGELOG.md").read_text()
    assert "## 1.1.0" in changelog and "passed 3 of 4, the controls 0 of 4" in changelog
    assert space.get("agent", "scripted").version == "1.1.0"
    _save(job, remedy={"instructions": "Play Wordle carefully."})
    with pytest.raises(ProjectError, match="instructions changed since"):
        revise_agent(space, "scripted", "F1")
    _save(job, remedy={"tool_overrides": {"guess": {"description": "Guess a word."}}})
    assert revise_agent(space, "scripted", "F1").version == "1.2.0"
    # A Finding saved before the context policy moved to the Harness still applies.
    _save(job, remedy={"context": {"strategy": "window", "max_tokens": 8000}})
    assert revise_agent(space, "scripted", "F1").version == "1.3.0"
    written = yaml.safe_load((project / "agents/scripted/agent.yaml").read_text())
    assert "context" not in written
    assert written["harness_config"]["context"]["strategy"] == "window"
    loaded = Workspace(Project.at(project)).get("agent", "scripted")
    assert loaded.context is not None and loaded.context.max_tokens == 8000


def test_revise_writes_a_fix_note_for_an_external_agent(
    failed_job: dict[str, Any], tmp_path: Path
) -> None:
    from plural.inspector.revise import revise_agent
    from plural.project import Project, Workspace

    project = tmp_path / "wordle"
    shutil.copytree(failed_job["project"], project)
    (project / "agents/scripted/agent.yaml").write_text(
        "name: scripted\nversion: 2.0.0\nexternal:\n  url: https://agent.example/episodes\n"
        "  version: v7\n  secret: AGENT_WEBHOOK_SECRET\n",
        encoding="utf-8",
    )
    job = {**failed_job, "project": project}
    _save(job, status="inferred", forks=[])
    revision = revise_agent(Workspace(Project.at(project)), "scripted", "F1")
    assert revision.version is None
    note = (project / "agents/scripted/fixes/F1.md").read_text()
    assert "Nothing told it to use the feedback" in note, note
    assert "Suggested change:" in note and "instructions" in note.split("Suggested change:")[1]


def test_the_report_computes_every_number_with_its_trials(failed_job: dict[str, Any]) -> None:
    from plural.inspector.report import (
        build_report,
        render_markdown,
        render_summary,
        validate_summary,
    )
    from plural.project import Project, Workspace

    space = Workspace(Project.at(failed_job["project"]))
    _save(failed_job)
    report = build_report(space, failed_job["job_id"], compare=failed_job["job_id"], findings=True)
    facts = {item.fact_id: item for item in report.facts}
    row = report.performance[0]
    assert row.pass_rate is None, "Wordle's Verifier has no gates, so no Trial is judged"
    assert facts[row.success_rate or ""].display == "50% (1 of 2)"
    assert set(facts[row.success_rate or ""].trial_ids) == set(failed_job["trials"].values())
    assert report.failures and report.failures.findings[0].cause == "instructions"
    assert report.changes is not None
    dev = report.changes.splits["dev"]
    assert "pass_rate" not in dev and dev["success_rate"].verdict == "not_enough_data"
    assert all(item.trial_ids for item in report.facts if item.label.startswith("scripted"))
    text = render_markdown(report)
    for heading in ("performs", "Why it fails", "What changed", "trusted", "Facts"):
        assert heading in text
    summary = f"The Agent passed {{{row.success_rate}}}."
    assert validate_summary(summary, report.facts) == []
    assert render_summary(summary, report.facts) == "The Agent passed 50% (1 of 2)."
    assert validate_summary("It passed 1 of 2.", report.facts)


def test_the_report_compares_a_dollar_metric_in_its_unit_and_direction() -> None:
    from types import SimpleNamespace

    from plural.inspector.report import _Facts, _metric_change
    from plural.metrics import MetricSpec

    def job(job_id: str, worth: dict[str, list[float]]) -> Any:
        trials = [
            SimpleNamespace(
                task=task,
                metrics={"net_worth_usd": value},
                receipt=SimpleNamespace(trial_id=f"{job_id}-{task}-{index}"),
            )
            for task, values in worth.items()
            for index, value in enumerate(values)
        ]
        return SimpleNamespace(
            job_id=job_id,
            heldout=set(),
            finished=lambda: trials,
            task=lambda trial: trial.task,
        )

    tasks = [f"seed-{index}" for index in range(12)]
    new = job("job-2", {task: [1500.0 + index] for index, task in enumerate(tasks)})
    old = job("job-1", {task: [1000.0 + index] for index, task in enumerate(tasks)})
    spec = MetricSpec(name="net_worth_usd", kind="number", unit="USD")
    facts = _Facts()
    change = _metric_change(new, old, spec, "dev", facts)
    shown = {item.fact_id: item.display for item in facts.items}
    assert change is not None and change["verdict"] == "better"
    assert (change["unit"], change["direction"]) == ("USD", "higher")
    assert shown[change["new"]] == "$1,506" and shown[change["delta"]] == "+$500"
    # Lower is better for a cost: the same rise is then worse.
    costly = MetricSpec(name="net_worth_usd", kind="number", unit="USD", direction="lower")
    assert _metric_change(new, old, costly, "dev", _Facts())["verdict"] == "worse"  # type: ignore[index]


def test_a_summary_that_writes_its_own_numbers_is_rejected(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.inspector import report as module
    from plural.project import Project, Workspace

    space = Workspace(Project.at(failed_job["project"]))
    built = module.build_report(space, failed_job["job_id"])
    replies = iter(["Half passed: 50%.", "Half passed: 50 percent."])
    monkeypatch.setattr(module, "_complete", lambda *_args: next(replies))
    environ = {"PLURAL_GATEWAY_URL": "http://gateway", "PLURAL_API_KEY": "key"}
    rejected = module.write_summary(built, environ)
    assert rejected.summary is None and "number itself" in rejected.summary_problems[0]
    first = built.performance[0].success_rate
    monkeypatch.setattr(module, "_complete", lambda *_args: f"Half passed: {{{first}}}.")
    assert module.write_summary(built, environ).summary == "Half passed: 50% (1 of 2)."


def test_remedy_agents_merge_tool_overrides() -> None:
    from plural.agents import Agent, AgentBinding
    from plural.agents.tool_overrides import ToolOverride
    from plural.inspector.experiments import remedy_agent
    from plural.inspector.findings import Remedy

    agent = Agent(
        name="bot",
        model="openai/gpt-5.6-luna",
        tool_overrides={"check_schedule": "Optional."},
    )
    binding = AgentBinding(agent=agent._definition())
    remedy = Remedy(
        instructions="Always check the schedule.",
        tool_overrides={"check_schedule": ToolOverride(description="Required.")},
    )
    changed = remedy_agent(binding, remedy, "X1")
    assert changed.name == "bot-x1"
    assert changed.agent.instructions == "Always check the schedule."
    assert changed.agent.tool_overrides["check_schedule"].description == "Required."


def test_a_remedy_can_change_the_context_policy() -> None:
    from plural.agents import Agent, AgentBinding
    from plural.agents.models import ContextPolicy
    from plural.inspector.experiments import remedy_agent
    from plural.inspector.findings import ForkTest, Remedy, stronger_model_won

    agent = Agent(
        name="bot",
        model="openai/gpt-5.6-luna",
        context={"strategy": "summarize", "max_tokens": 20000},
    )
    policy = ContextPolicy(
        strategy="summarize",
        max_tokens=20000,
        summary_instructions="Keep the supplier accounts and standing orders.",
    )
    remedy = Remedy(context=policy)
    assert remedy == Remedy(harness_config={"context": policy.model_dump(mode="json")})
    assert not remedy.empty
    assert remedy.describe() == ["harness_config.context: summarize, rewritten"]
    changed = remedy_agent(AgentBinding(agent=agent._definition()), remedy, "X1")
    assert changed.agent.context == policy
    assert changed.agent.instructions == agent.instructions
    fork = ForkTest(
        test_id="X1",
        job_id="j",
        step=3,
        remedy=Remedy(model="openai/gpt-5.6-sol", context=policy),
        verdict="likely_matters",
        candidate=1.0,
        control=0.0,
        candidates=4,
        controls=4,
    )
    assert not stronger_model_won(fork, "openai/gpt-5.6-luna")


def test_every_fault_applies_to_the_quoting_example(tmp_path: Path) -> None:
    from plural.agents import Agent
    from plural.inspector.faults import IGNORED, QUOTING_FAULTS, healthy_agent

    source = ROOT / "examples" / "quoting"
    manifest = yaml.safe_load((source / "agents/quote-bot/agent.yaml").read_text())
    healthy = healthy_agent(manifest)
    assert "round the price" not in healthy["instructions"]
    Agent.model_validate(healthy)
    causes = set()
    for index, fault in enumerate(QUOTING_FAULTS):
        causes.add(fault.cause)
        if fault.agent is not None:
            for level in fault.levels:
                variant = json.loads(json.dumps(healthy))
                fault.agent(variant, level)
                assert variant != healthy, fault.name
                Agent.model_validate(variant)
        else:
            assert fault.project is not None
            copy = tmp_path / str(index)
            shutil.copytree(source, copy, ignore=IGNORED)
            before = {p: p.read_bytes() for p in copy.rglob("*") if p.is_file()}
            fault.project(copy)
            after = {p: p.read_bytes() for p in copy.rglob("*") if p.is_file()}
            assert before != after, fault.name
    assert causes >= {"tools", "instructions", "context", "model", "grader", "task"}


def test_uploads_translate_local_trial_ids() -> None:
    from plural.inspector.hosted import _translate

    payload = {"trial_id": "trl_a", "facts": [{"trial_ids": ["trl_a", "trl_b"]}], "n": 2}
    assert _translate(payload, {"trl_a": "hosted-a"}) == {
        "trial_id": "hosted-a",
        "facts": [{"trial_ids": ["hosted-a", "trl_b"]}],
        "n": 2,
    }


class _InspectorModel(BaseHTTPRequestHandler):
    """Calls overview once, then stops; records every request it was sent."""

    seen: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        message: dict[str, Any] = {"role": "assistant", "content": "Done."}
        if not any(item["role"] == "tool" for item in body["messages"]):
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_overview",
                        "type": "function",
                        "function": {"name": "overview", "arguments": "{}"},
                    }
                ],
            }
        payload = json.dumps(
            {
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 3},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        return


class _Jobs:
    def __init__(self, key: str) -> None:
        self.key = key
        self.calls: list[tuple[str, str]] = []

    def inspection_key(self, job_id: str, *, ttl_seconds: int) -> dict[str, Any]:
        self.calls.append(("mint", job_id))
        return {"key": self.key, "expires_at": "2099-01-01T00:00:00Z"}

    def end_inspection_key(self, job_id: str) -> None:
        self.calls.append(("end", job_id))


def test_the_fork_key_reaches_the_app_host_alone(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Job-scoped key is minted for this Job, reaches the Inspector App, and is never
    written down, shown to the model, or kept past the inspection."""
    import threading
    from http.server import ThreadingHTTPServer
    from types import SimpleNamespace

    import plural.inspector.run as inspector_run
    from plural.inspector.app import CREDENTIAL
    from plural.project import Project, Workspace

    server = ThreadingHTTPServer(("127.0.0.1", 0), _InspectorModel)
    _InspectorModel.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original = inspector_run.inspector_workspace

    def scripted(project: Any, *, model: str | None = None) -> Any:
        space = original(project, model="test/inspector")
        path = space.project.root / "agents" / "inspector" / "agent.yaml"
        manifest = yaml.safe_load(path.read_text("utf-8"))
        manifest["endpoint"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
        manifest["endpoint_key"] = "INSPECTOR_MODEL_KEY"
        path.write_text(yaml.safe_dump(manifest, sort_keys=False), "utf-8")
        return space

    monkeypatch.setattr(inspector_run, "inspector_workspace", scripted)
    sentinel = "pk_live_fork_key_sentinel_7f3a9c"
    jobs = _Jobs(sentinel)
    project = failed_job["project"]
    environ = {**failed_job["env"], "INSPECTOR_MODEL_KEY": "unused", CREDENTIAL: "stale-key"}
    try:
        record = inspector_run.inspect_job(
            Workspace(Project.at(project)),
            failed_job["job_id"],
            depth="standard",
            environ=environ,
            studio=SimpleNamespace(jobs=jobs),  # type: ignore[arg-type]
            trial_ids=[failed_job["trials"]["nymph"]],
        )
    finally:
        server.shutdown()
    # Minted for this Job alone, and ended when the inspection ended.
    assert jobs.calls == [("mint", failed_job["job_id"]), ("end", failed_job["job_id"])]
    # The Inspector App had it: its overview offered forks.
    results = [
        json.loads(message["content"])
        for body in _InspectorModel.seen
        for message in body["messages"]
        if message["role"] == "tool"
    ]
    assert results and results[0]["forks_allowed"] is True
    # The model never saw it, nor the stale key it replaced.
    sent = json.dumps(_InspectorModel.seen)
    assert sentinel not in sent and "stale-key" not in sent
    # Nothing written down holds it: Tasks, State, traces, Findings, or the record.
    assert sentinel not in record.model_dump_json()
    leaked = [
        path
        for path in project.rglob("*")
        if path.is_file() and sentinel.encode() in path.read_bytes()
    ]
    assert leaked == []


def test_the_bench_never_runs_a_held_out_task() -> None:
    from plural.inspector.faults import _categories

    source = ROOT / "examples" / "quoting"
    manifest = yaml.safe_load((source / "benchmarks/quoting/benchmark.yaml").read_text("utf-8"))
    picked = {task for tasks in _categories(source).values() for task in tasks}
    assert picked and not picked & set(manifest["heldout"])


class _Finished:
    def __init__(self, trial_id: str, cost: float) -> None:
        self.trial_id = trial_id
        self.metrics = {"cost_usd": cost}


def _forking(failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch, run: Any) -> Any:
    from plural.inspector import experiments
    from plural.inspector.app import CREDENTIAL

    monkeypatch.setenv(CREDENTIAL, "test")
    monkeypatch.setattr(experiments, "run_fork", run)
    return _app(failed_job, depth="standard", budget_usd=5.0)


def test_a_fork_runs_in_the_background_and_fork_result_records_it(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.inspector.app import FORK_LEDGER, fork_seconds
    from plural.inspector.evidence import JobEvidence
    from plural.inspector.findings import ForkTest

    def run(*_args: Any, progress: Any, test_id: str, **_kwargs: Any) -> ForkTest:
        for index in range(8):
            progress(None, _Finished(f"t{index}", 0.01))
        return ForkTest(
            test_id=test_id,
            job_id="job_fork",
            step=2,
            verdict="likely_matters",
            candidate=1.0,
            control=0.0,
            candidates=4,
            controls=4,
            cost_usd=0.08,
        )

    app = _forking(failed_job, monkeypatch, run)
    trial = app._trial()
    started = app.fork(step=2, instructions="Read every clue before guessing.")
    assert started["status"] == "running"
    assert started["deadline_seconds"] == round(
        fork_seconds(trial.task.environment.limits.max_seconds, 4)
    )
    done = app.fork_result(started["test_id"], wait_seconds=10)
    assert done["status"] == "done"
    assert done["beat_controls"]
    assert [item["test_id"] for item in app.state.tests] == ["X1"]
    assert app.state.spent_usd == pytest.approx(0.08)
    again = app.fork_result("X1", wait_seconds=0)
    assert again["status"] == "done"
    assert app.state.spent_usd == pytest.approx(0.08)
    ledger = JobEvidence(failed_job["project"], failed_job["job_id"]).directory / FORK_LEDGER
    assert len(ledger.read_text("utf-8").splitlines()) == 8
    ledger.unlink()


def test_a_timed_out_fork_still_records_what_its_trials_spent(
    failed_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from plural.inspector import app as module
    from plural.inspector.evidence import JobEvidence
    from plural.inspector.run import fork_ledger

    release = threading.Event()

    def run(*_args: Any, progress: Any, **_kwargs: Any) -> None:
        progress(None, _Finished("t0", 0.03))
        release.wait(10)
        raise RuntimeError("stopped")

    monkeypatch.setattr(module, "fork_seconds", lambda *_args: 0.2)
    app = _forking(failed_job, monkeypatch, run)
    started = app.fork(step=2, instructions="Read every clue before guessing.")
    assert app.fork_result(started["test_id"], wait_seconds=0)["status"] == "running"
    out = app.fork_result(started["test_id"], wait_seconds=1)
    assert out["status"] == "timed_out"
    assert out["finished_trials"] == 1
    assert app.state.spent_usd == pytest.approx(0.03)
    assert app.state.tests == []
    release.set()
    directory = JobEvidence(failed_job["project"], failed_job["job_id"]).directory
    assert fork_ledger(directory) == pytest.approx(0.03)
    (directory / module.FORK_LEDGER).unlink()


def test_the_inspector_has_time_for_forks_as_long_as_the_forked_trial(
    failed_job: dict[str, Any],
) -> None:
    from plural.inspector.app import fork_seconds
    from plural.inspector.evidence import JobEvidence
    from plural.inspector.run import INSPECTOR_SECONDS, inspection_seconds

    trial = JobEvidence(failed_job["project"], failed_job["job_id"]).trial(
        failed_job["trials"]["nymph"]
    )
    limit = trial.task.environment.limits.max_seconds
    assert inspection_seconds([trial], "quick") == INSPECTOR_SECONDS
    assert inspection_seconds([trial], "standard") == int(
        INSPECTOR_SECONDS + 2 * fork_seconds(limit, 4)
    )
    assert fork_seconds(6 * 3600, 4) > 1800


def test_revise_ships_the_exact_remedy_a_winning_fork_tested(
    failed_job: dict[str, Any], tmp_path: Path
) -> None:
    from plural.inspector.findings import InspectionRecord, now, save_findings
    from plural.inspector.revise import revise_from_fork
    from plural.project import Project, Workspace
    from plural.project.layout import ProjectError

    project = tmp_path / "wordle"
    shutil.copytree(failed_job["project"], project)
    space = Workspace(Project.at(project))
    trial_id = failed_job["trials"]["nymph"]

    def fork(test_id: str, job_id: str, **fields: Any) -> dict[str, Any]:
        return {
            "test_id": test_id,
            "job_id": job_id,
            "trial_id": trial_id,
            "step": 2,
            "verdict": "likely_matters",
            "candidate": 1.0,
            "control": 0.0,
            "candidates": 4,
            "controls": 4,
            **fields,
        }

    record = InspectionRecord.model_validate(
        {
            "job_id": failed_job["job_id"],
            "inspected_at": now(),
            "forks": [
                fork("X1", "job_won", remedy={"instructions": "Play Wordle. Use each clue."}),
                fork(
                    "X2", "job_lost", remedy={"model": "openai/gpt-5.6"}, verdict="no_clear_effect"
                ),
                fork("X3", "job_seen", change="context", payload={"mode": "restore"}),
                fork("X1", "job_other", remedy={"model": "openai/gpt-5.6"}),
            ],
        }
    )
    save_findings(project / ".plural" / "jobs" / failed_job["job_id"], record)
    with pytest.raises(ProjectError, match="names several forks"):
        revise_from_fork(space, "scripted", "X1")
    with pytest.raises(ProjectError, match="didn't beat its controls"):
        revise_from_fork(space, "scripted", "job_lost")
    with pytest.raises(ProjectError, match="nothing to ship"):
        revise_from_fork(space, "scripted", "job_seen")
    with pytest.raises(ProjectError, match="of scripted, not other"):
        revise_from_fork(space, "other", "job_won")
    revision = revise_from_fork(space, "scripted", "job_won")
    assert (revision.previous, revision.version) == ("1.0.0", "1.1.0")
    assert revision.fork_job_id == "job_won"
    written = yaml.safe_load((project / "agents/scripted/agent.yaml").read_text())
    assert written["instructions"] == "Play Wordle. Use each clue."
    changelog = (project / "agents/scripted/CHANGELOG.md").read_text()
    assert "From fork X1 (Job job_won)" in changelog
    assert "passed 4 of 4, the controls 0 of 4" in changelog


def test_agent_revise_takes_one_source(failed_job: dict[str, Any]) -> None:
    from typer.testing import CliRunner

    from plural.cli import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "120"})
    result = runner.invoke(app, ["agent", "revise", "scripted"])
    assert result.exit_code != 0
    assert "--from-finding and --from-fork" in result.output


def test_an_inspection_fork_is_recorded_as_a_fork_of_the_inspected_job(
    failed_job: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.inspector.experiments import remedy_agent
    from plural.inspector.findings import Remedy
    from plural.project import Project, Workspace, runs
    from plural.project.forks import ForkRequest, plan_fork, trial_source
    from plural.project.layout import ProjectError, ResourceRef
    from plural.project.sync import HostedRevision

    project = tmp_path / "wordle"
    shutil.copytree(failed_job["project"], project)
    space = Workspace(Project.at(project))
    trial_id = failed_job["trials"]["nymph"]
    source = trial_source(space, trial_id)
    candidate = remedy_agent(source.agent, Remedy(instructions="Use each clue."), "X1")
    spec, record = plan_fork(
        space, ForkRequest(trial_id=trial_id, step=2, attempts=2, candidates=(candidate,))
    )
    control = source.agent

    def revision(ref: ResourceRef) -> HostedRevision:
        digest = control.agent.content_hash if ref.kind == "agent" else f"sha256:{ref.name}"
        return HostedRevision(
            resource_id=f"res-{ref.name}",
            revision_id=f"rev-{ref.name}",
            version=None,
            content_hash=digest,
            package_digest=None,
        )

    monkeypatch.setattr(
        runs,
        "resolve_pinned",
        lambda _studio, inputs, job_id: {
            ResourceRef.parse(key): revision(ResourceRef.parse(key)) for key in inputs
        },
    )
    pushed: list[dict[str, Any]] = []
    submitted: list[dict[str, Any]] = []

    class Agents:
        def push(self, value: Any, **options: Any) -> dict[str, Any]:
            pushed.append({"name": value.name, **options})
            return {"id": f"rev-{value.name}"}

    class Jobs:
        def submit(self, job: Any, **options: Any) -> dict[str, Any]:
            submitted.append(options)
            return {"id": "hosted-fork"}

    class Studio:
        agents = Agents()
        jobs = Jobs()

    with pytest.raises(ProjectError, match="was never recorded"):
        runs.submit_client_job(space, Studio(), spec, record)  # type: ignore[arg-type]
    original = project / ".plural" / "jobs" / failed_job["job_id"] / runs.RUN_RECORD
    original.write_text(
        json.dumps({**json.loads(original.read_text()), "hosted_job_id": "hosted-inspected"})
    )
    client = runs.submit_client_job(space, Studio(), spec, record)  # type: ignore[arg-type]
    assert client.job_id == "hosted-fork"
    assert submitted[0]["forked_from_job_id"] == "hosted-inspected"
    assert len(submitted[0]["agent_revision_ids"]) == len(spec.agents)
    assert f"rev-{control.name}" in submitted[0]["agent_revision_ids"]
    assert pushed == [
        {
            "name": candidate.name,
            "resource_id": f"res-{control.name}",
            "current": False,
            "lineage": [{"relation": "derived_from", "revision_id": f"rev-{control.name}"}],
        }
    ]


def test_the_hosted_finding_names_each_recorded_fork_job() -> None:
    from plural.inspector.hosted import _link_forks

    fork = {"test_id": "X1", "job_id": "job_local"}
    payload = _link_forks(
        {
            "forks": [fork, {"test_id": "X2", "job_id": "job_unrecorded"}],
            "findings": [{"forks": [fork]}],
        },
        {"job_local": "hosted-fork"},
    )
    assert payload["forks"][0]["hosted_job_id"] == "hosted-fork"
    assert "hosted_job_id" not in payload["forks"][1]
    assert payload["findings"][0]["forks"][0]["hosted_job_id"] == "hosted-fork"
