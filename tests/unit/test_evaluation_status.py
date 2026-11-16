"""``plural eval status``: each step's status and the command to run next."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

import plural.evaluation
import plural.project.checks
from plural.cli.main import app
from plural.evaluation import STEPS, eval_status

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "quoting"


@pytest.fixture
def quoting(tmp_path: Path) -> Path:
    project = tmp_path / "quoting"
    shutil.copytree(EXAMPLE, project)
    return project


@pytest.fixture
def checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Task's graders checked and passing."""
    passing = SimpleNamespace(passed=True, problems=())
    monkeypatch.setattr(plural.project.checks, "load_check", lambda _workspace, _task: passing)


@pytest.fixture
def defined(monkeypatch: pytest.MonkeyPatch) -> None:
    """Good is defined and the eval set is built, so the later steps come next."""
    for name, number in (("_define_good", 2), ("_eval_set", 3)):
        step = plural.evaluation.EvalStep(number=number, title=STEPS[number - 1], status="done")
        monkeypatch.setattr(plural.evaluation, name, lambda *_args, step=step: step)


def _statuses(path: Path, **options: Any) -> dict[str, str]:
    return {step.title: step.status for step in eval_status(path, **options).steps}


def test_outside_a_project_the_next_step_is_to_create_one(tmp_path: Path) -> None:
    status = eval_status(tmp_path)
    assert status.project is None
    assert [step.title for step in status.steps] == list(STEPS)
    assert status.next_command == "plural project init <name>"
    assert _statuses(tmp_path) == {
        "Set up": "todo",
        "Define good": "todo",
        "Build the eval set": "todo",
        "Check the graders": "todo",
        "Baseline": "todo",
        "Diagnose": "coming_soon",
        "Improve": "coming_soon",
        "Report": "coming_soon",
    }


def test_an_empty_project_starts_with_an_environment(tmp_path: Path) -> None:
    (tmp_path / "project.yaml").write_text("name: demo\n", encoding="utf-8")
    status = eval_status(tmp_path)
    assert status.project == "demo"
    assert status.steps[0].summary == "0 Environments, 0 Agents"
    assert status.next_command == "plural env init <name>"


def test_a_project_with_its_benchmark_unchecked_is_told_to_check_it(
    quoting: Path, defined: None
) -> None:
    status = eval_status(quoting)
    steps = {step.title: step for step in status.steps}
    assert status.benchmark == "quoting"
    assert steps["Set up"].status == "done"
    assert steps["Check the graders"].status == "todo"
    assert steps["Check the graders"].summary == "0 of 60 Tasks checked"
    assert steps["Baseline"].status == "todo"
    assert status.next_command == "plural eval check -b quoting"


def test_once_the_graders_pass_the_next_step_is_the_baseline(
    quoting: Path, checked: None, defined: None
) -> None:
    status = eval_status(quoting)
    assert {step.title: step.status for step in status.steps}["Check the graders"] == "done"
    assert status.next_command == "plural run -b quoting -a quote-bot"


def test_several_benchmarks_need_one_named(quoting: Path) -> None:
    shutil.copytree(quoting / "benchmarks/quoting", quoting / "benchmarks/another")
    status = eval_status(quoting)
    assert status.benchmark is None
    assert status.steps[2].status == "attention"
    assert status.next_command == "plural eval status --benchmark another"
    assert eval_status(quoting, benchmark="quoting").benchmark == "quoting"


def test_a_missing_or_invalid_benchmark_needs_attention(quoting: Path) -> None:
    missing = eval_status(quoting, benchmark="nope")
    assert missing.steps[2].summary == "No Benchmark 'nope' in this project."
    assert missing.next_command == "plural eval status --benchmark quoting"
    (quoting / "benchmarks/broken").mkdir()
    (quoting / "benchmarks/broken/benchmark.yaml").write_text("name: broken\n", "utf-8")
    broken = eval_status(quoting, benchmark="broken")
    assert broken.steps[2].status == "attention"
    assert broken.next_command == "plural benchmark validate broken"


@pytest.mark.parametrize(
    ("job", "status", "summary"),
    [
        (
            {"status": "succeeded", "score": 0.4166},
            "done",
            "job_1: quote-bot, score 0.42",
        ),
        ({"status": "running", "score": None}, "attention", "job_1 is running"),
        ({"status": "awaiting_review", "score": None}, "attention", "job_1 is awaiting review"),
    ],
)
def test_the_baseline_is_the_latest_local_job_of_the_benchmark(
    quoting: Path,
    monkeypatch: pytest.MonkeyPatch,
    job: dict[str, Any],
    status: str,
    summary: str,
    checked: None,
    defined: None,
) -> None:
    jobs = [
        {"job_id": "job_1", "source": "benchmark/quoting", "agent": "agent/quote-bot", **job},
        {"job_id": "job_0", "source": "task/quote-001", "agent": "agent/quote-bot"},
    ]
    monkeypatch.setattr(plural.evaluation, "local_jobs", lambda _workspace: jobs)
    baseline = eval_status(quoting).steps[4]
    assert (baseline.status, baseline.summary) == (status, summary)
    assert eval_status(quoting).next_command == "plural job show job_1"


def test_the_command_prints_every_step_and_ends_with_next(
    quoting: Path, monkeypatch: pytest.MonkeyPatch, defined: None
) -> None:
    monkeypatch.chdir(quoting)
    text = CliRunner().invoke(app, ["eval", "status"])
    assert text.exit_code == 0, text.output
    lines = text.output.splitlines()
    assert lines[0] == "Evaluation of quoting in quoting"
    assert len(lines) == 1 + len(STEPS) + 1
    assert lines[-1] == "Next: plural eval check -b quoting"
    payload = json.loads(CliRunner().invoke(app, ["eval", "status", "--json"]).output)
    assert payload["next_command"] == "plural eval check -b quoting"


def test_defining_good_starts_from_the_scorecard_in_the_project(quoting: Path) -> None:
    status = eval_status(quoting)
    define = status.steps[1]
    assert (define.status, define.command) == ("todo", "plural scorecard calibrate steel-quoting")
    assert "not on the Benchmark: add `scorecard: steel-quoting`" in define.summary
    assert status.next_command == define.command

    card = quoting / "scorecards/steel-quoting/scorecard.yaml"
    card.write_text(
        card.read_text("utf-8").replace(
            "  - name: tone\n    role: objective\n    weight: 0.5\n", ""
        ),
        encoding="utf-8",
    )
    benchmark = quoting / "benchmarks/quoting/benchmark.yaml"
    benchmark.write_text(
        benchmark.read_text("utf-8") + "scorecard: steel-quoting\n", encoding="utf-8"
    )
    define = eval_status(quoting).steps[1]
    assert define.summary == (
        "steel-quoting@1.0.0: 7 metrics, 0 Trials labeled; calibration needs 20."
    )
    assert define.command == "plural scorecard label steel-quoting --job <job>"

    from plural.project import Project, Workspace
    from plural.project.scorecards import save_labels
    from plural.scorecards import Label

    labeled = [
        Label(scorecard="steel-quoting", trial_id=f"trial_{number}", labeler="KB")
        for number in range(20)
    ]
    save_labels(Workspace(Project.find(quoting)), "steel-quoting", labeled)
    define = eval_status(quoting).steps[1]
    assert define.summary.endswith("20 Trials labeled. The graders are not checked yet.")
    assert define.command == "plural scorecard calibrate steel-quoting"


def test_the_eval_set_asks_for_a_held_out_split_and_counts_peeks(quoting: Path) -> None:
    eval_set = eval_status(quoting).steps[2]
    assert (eval_set.status, eval_set.command) == ("todo", "plural benchmark split quoting")
    assert eval_set.summary == "60 Tasks in 4 categories, none held out to confirm fixes on."

    from plural.heldout import record_peek
    from plural.project import Project
    from plural.project.membership import set_heldout

    project = Project.find(quoting)
    set_heldout(project, "quoting", fraction=0.3)
    record_peek(
        project.state_dir, benchmark="quoting", job_id="job_1", purpose="confirm", tasks=["x"]
    )
    eval_set = eval_status(quoting).steps[2]
    assert eval_set.status == "done"
    assert eval_set.summary == "60 Tasks in 4 categories, 18 held out; 1 peek."
