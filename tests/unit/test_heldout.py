"""The held-out lock: a Benchmark's ``heldout:`` Tasks, kept out of plain runs, and every
peek at them counted."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from plural.heldout import peeks, record_peek
from plural.project.layout import BENCHMARK

ROOT = Path(__file__).resolve().parents[2]
QUOTING = ROOT / "examples" / "quoting"


def test_every_task_held_out_is_refused(split_project: Path) -> None:
    from plural.project import Project, Workspace
    from plural.project.layout import ProjectError

    path = split_project.parent / "all-held"
    shutil.copytree(split_project, path, ignore=shutil.ignore_patterns(".plural"))
    manifest_path = path / "benchmarks/quoting/benchmark.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["heldout"] = list(manifest["tasks"])
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProjectError, match="Every Task is held out"):
        Workspace(Project.at(path)).get("benchmark", "quoting")


def test_peeks_are_counted(tmp_path: Path) -> None:
    record_peek(tmp_path, benchmark="quoting", job_id="job_1", purpose="eval", tasks=["q-1"])
    record_peek(tmp_path, benchmark="other", job_id="job_2", purpose="confirm", tasks=["o-1"])
    assert [item["job_id"] for item in peeks(tmp_path, "quoting")] == ["job_1"]


@pytest.fixture(scope="module")
def split_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project = tmp_path_factory.mktemp("heldout") / "quoting"
    shutil.copytree(QUOTING, project, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    path = project / "benchmarks/quoting/benchmark.yaml"
    manifest = yaml.safe_load(path.read_text())
    manifest["heldout"] = manifest["tasks"][-18:]
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return project


def test_a_plain_benchmark_job_runs_only_dev_tasks(split_project: Path) -> None:
    from plural import Agent, Job
    from plural.project import Project, Workspace

    space = Workspace(Project.at(split_project))
    benchmark = space.get("benchmark", "quoting")
    agent = Agent(name="a", model="openai/gpt-5.6-luna")
    plain = Job(benchmark, agents=[agent])
    assert {task.task_id for task in plain.spec.tasks}.isdisjoint(benchmark.heldout)
    assert len(plain.plan.trials) == 62
    peek = Job(benchmark, agents=[agent], heldout=True)
    # --heldout runs the held-out Tasks alone: dev results come from the plain run.
    assert {task.task_id for task in peek.spec.tasks} == set(benchmark.heldout)
    assert len(peek.plan.trials) == 18
    assert peek.spec.job_id != plain.spec.job_id
    # Diagnosis never sees a held-out Task, and the refusal names the confirm command.
    with pytest.raises(ValueError, match="plural run --benchmark BENCHMARK --heldout"):
        Job(benchmark, agents=[agent], heldout=True, purpose="diagnose")
    # Nor does a learn Job: an Agent that learned from a held-out Task can't be confirmed on it.
    with pytest.raises(ValueError, match="A learn Job cannot run held-out Tasks"):
        Job(benchmark, agents=[agent], heldout=True, purpose="learn")
    learn = Job(benchmark, agents=[agent], purpose="learn")
    assert len(learn.plan.trials) == 62
    assert learn.spec.job_id != plain.spec.job_id
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
    assert len(spec.tasks) == 18
    from plural.jobs import JobSpec
    from plural.project.runs import _rebind_checks

    saved = _rebind_checks(space, JobSpec.model_validate_json(spec.model_dump_json()))
    assert saved.source.include_heldout and len(saved.tasks) == 18
    (peek,) = peeks(space.project.state_dir, "quoting")
    assert peek["job_id"] == spec.job_id
    assert len(peek["tasks"]) == 18


def test_a_benchmark_without_heldout_tasks_keeps_its_hash() -> None:
    from plural.project import Project, Workspace

    space = Workspace(Project.at(ROOT / "examples" / "wordle"))
    benchmark = space.get("benchmark", space.project.names(BENCHMARK)[0])
    assert benchmark.heldout == ()
    # The hash the SDK computed for this Benchmark before held-out Tasks existed.
    assert benchmark.content_hash == (
        "sha256:d34aa4716b050bcd1c8e62816c2761837e2352e63f2c0f8a5a6a3419b7517334"
    )


def test_a_task_a_local_job_ran_cannot_be_held_out(tmp_path: Path) -> None:
    """A held-out Task must be untouched: the CLI checks the project's own run records."""
    from plural.heldout import local_uses

    def job(name: str, tasks: list[str], *, heldout: list[str], peek: bool) -> None:
        folder = tmp_path / "jobs" / name
        folder.mkdir(parents=True)
        source = {
            "kind": "benchmark",
            "benchmark": {"tasks": [{"task_id": t} for t in tasks], "heldout": heldout},
            "include_heldout": peek,
        }
        (folder / "config.json").write_text(json.dumps({"source": source}))
        trials = [{"receipt": {"task_pin": {"name": t}}} for t in tasks]
        (folder / "result.json").write_text(json.dumps({"trials": trials}))

    job("job_dev", ["q-1", "q-2"], heldout=["q-3"], peek=False)
    job("job_peek", ["q-3"], heldout=["q-3"], peek=True)
    # q-1 ran as a dev Task; q-3 was only ever held out; q-4 never ran.
    assert local_uses(tmp_path, ["q-1", "q-3", "q-4"]) == {"q-1": "job_dev"}


def test_a_held_out_run_where_every_trial_errored_revealed_nothing() -> None:
    from types import SimpleNamespace

    from plural.heldout import revealed_nothing

    errored = SimpleNamespace(status="failed", score=None, stop_reason="error")
    judged = SimpleNamespace(status="failed", score=0.0, stop_reason="submitted")
    assert revealed_nothing([errored, errored]) is True  # type: ignore[list-item]
    assert revealed_nothing([errored, judged]) is False  # type: ignore[list-item]
    assert revealed_nothing([]) is None
