"""Forks: continue a Trial from a checkpoint, with the history by one rule."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from test_external_agents import KEY, _Service, _task, service

from plural import Agent, Job
from plural.agents import AgentBinding
from plural.checkpoints import AgentContext, build_checkpoint, history_rule
from plural.jobs import ForkChange, ForkSpec, JobResult, TaskJobSource

ROOT = Path(__file__).resolve().parents[2]
CLI = Path(sys.executable).with_name("plural")
GUESSES = ("crane", "slate", "audio", "point", "storm", "heart")


def test_the_history_rule_picks_native_transcript_or_none_and_says_why() -> None:
    context = AgentContext(tools_used=("Bash", "Edit", "Glob"), turn=3)

    same, quiet = history_rule(
        context, ("Bash", "Edit", "Glob", "Read"), supports_resume=True, step=14
    )
    assert (same, quiet) == ("native", [])
    other, warnings = history_rule(
        context,
        ("shell", "apply_patch", "Bash"),
        supports_resume=False,
        agent_name="codex-agent",
        step=14,
    )
    assert other == "transcript"
    assert warnings[0].startswith("codex-agent lacks 2 tools used before step 14 (Edit, Glob).")
    assert "as a transcript, not as its own tool calls" in warnings[0]
    none, refused = history_rule(
        context, ("Bash",), supports_resume=False, external=True, agent_name="acme", step=14
    )
    assert none == "none" and "acme" in refused[0]
    told, _ = history_rule(context, (), supports_resume=True, external=True, step=14)
    assert told == "transcript"


def _external(url: str, *, version: str, resume: bool = False) -> Agent:
    return Agent(
        model=f"acme/takeoff-{version}",
        external={
            "url": url,
            "signing_key": "ACME_SIGNING_KEY",
            "version": version,
            "supports_resume": resume,
        },
    )


def _finish_only(episode: Any) -> None:
    episode.finish("12 doors")


def _submit(episode: Any) -> None:
    episode.act("submit", doors=12)
    episode.finish("12 doors")


def _fork(
    tmp_path: Path, first: JobResult, task: Any, original: Agent, candidate: Agent
) -> JobResult:
    trial = first.trials[0]
    artifacts = next((tmp_path / ".plural" / "jobs").glob(f"*/trials/{trial.receipt.trial_id}"))
    artifacts = artifacts / "executions" / "0" / "artifacts"
    checkpoint = build_checkpoint(artifacts, 1, trial_id=trial.receipt.trial_id)
    job = Job(task, agents=[candidate])
    control = AgentBinding(agent=original._definition())
    binding = AgentBinding(agent=candidate._definition())
    fork = ForkSpec(
        trial_id=trial.receipt.trial_id,
        checkpoint=checkpoint,
        control_agent_id=control.agent_id,
        candidate_agent_ids=(binding.agent_id,),
        bundle=str(artifacts / "workspace.bundle"),
    )
    job.spec = job.spec.model_copy(
        update={
            "source": TaskJobSource(task=task._definition()),
            "agents": (control, binding),
            "purpose": "fork",
            "fork": fork,
        }
    )
    job.plan = job.spec.plan()
    return job.run()


__all__ = ["service"]


@pytest.mark.parametrize("resume", [False, True])
def test_a_fork_into_an_external_agent_follows_its_resume_support(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    task = _task(tmp_path)
    original = _external(service, version="1")
    _Service.work = _submit
    first = Job(task, agents=[original]).run()
    assert first.trials[0].status == "succeeded", first.trials[0].error_message

    _Service.work, _Service.received = _finish_only, []
    candidate_agent = _external(service, version="2", resume=resume)
    result = _fork(tmp_path, first, task, original, candidate_agent)

    assert not _Service.errors, _Service.errors
    by_role = {item.fork.role: item for item in result.trials if item.fork is not None}
    candidate = by_role["candidate"]
    assert candidate.status == "succeeded", candidate.error_message
    assert candidate.fork is not None and candidate.fork.step == 1
    starts = [item for item in _Service.received if item.get("type") == "episode.start"]
    assert all("score" not in item and "state" not in item for item in starts)
    if resume:
        assert candidate.fork.history == "transcript"
        told = [item["resume"] for item in starts if "resume" in item]
        assert told and told[0]["step"] == 1 and "submit" in told[0]["transcript"]
        assert "12" not in json.dumps({key: told[0][key] for key in ("step",)})
    else:
        assert candidate.fork.history == "none"
        assert any("can't accept" in item or "resume" in item for item in candidate.fork.warnings)
        assert not any("resume" in item for item in starts)
    # The Apps were restored, not reset: the doors were already submitted.
    assert candidate.score == 1.0
    steps = [
        json.loads(line)
        for line in next(
            (tmp_path / ".plural" / "jobs").glob(
                f"*/trials/{candidate.receipt.trial_id}/executions/0/artifacts/steps.jsonl"
            )
        )
        .read_text()
        .splitlines()
    ]
    assert steps[0]["inherited"] is True and steps[0]["action"] == "submit"
    assert KEY not in json.dumps(steps)


class _WordleModel(BaseHTTPRequestHandler):
    """Guesses GUESSES in order, one per tool result it has seen; records what it was sent."""

    seen: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        played = sum(message["role"] == "tool" for message in body["messages"])
        message: dict[str, object] = {"role": "assistant", "content": "Out of words."}
        if played < len(GUESSES):
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{played}",
                        "type": "function",
                        "function": {
                            "name": "guess",
                            "arguments": json.dumps({"word": GUESSES[played]}),
                        },
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


@pytest.fixture
def wordle(tmp_path: Path) -> Iterator[tuple[Path, dict[str, str]]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WordleModel)
    _WordleModel.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    project = tmp_path / "wordle"
    shutil.copytree(ROOT / "examples" / "wordle", project)
    for name, instructions in (("scripted", "Play Wordle."), ("careful", "Play it carefully.")):
        folder = project / "agents" / name
        folder.mkdir()
        (folder / "agent.yaml").write_text(
            f"name: {name}\nversion: 1.0.0\nmodel: test/wordle\ninstructions: {instructions}\n"
            f"endpoint: {url}\nendpoint_key: WORDLE_MODEL_KEY\n",
            encoding="utf-8",
        )
    env = {
        key: value
        for key, value in __import__("os").environ.items()
        if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
    }
    env.update({"PLURAL_CONFIG_HOME": str(tmp_path / "config"), "WORDLE_MODEL_KEY": "unused"})
    try:
        yield project, env
    finally:
        server.shutdown()


def _plural(project: Path, env: dict[str, str], *args: str) -> dict[str, Any]:
    result = subprocess.run(
        [str(CLI), *args, "--json"], cwd=project, env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return dict(json.loads(result.stdout))


def _steps(project: Path, trial_id: str) -> list[dict[str, Any]]:
    path = next((project / ".plural" / "jobs").glob(f"*/trials/{trial_id}/executions/0/artifacts"))
    return [json.loads(line) for line in (path / "steps.jsonl").read_text().splitlines()]


def _hosted_id_names_the_recorded_trial(project: Path, original: str) -> None:
    from plural.project import Project, Workspace
    from plural.project.forks import local_trial_id, trial_source
    from plural.project.layout import ProjectError

    space = Workspace(Project.at(project))
    source = trial_source(space, original)
    record_path = project / ".plural" / "jobs" / source.job_id / "run.json"
    record = json.loads(record_path.read_text())
    record_path.write_text(json.dumps({**record, "hosted_job_id": "hosted-job"}))
    hosted = {
        "job_id": "hosted-job",
        "attempt": source.trial.attempt,
        "pins": {"task": {"name": "storm"}, "agent": source.agent.agent.content_hash},
    }
    calls: list[str] = []

    class _Trials:
        def get(self, trial_id: str) -> dict[str, Any]:
            calls.append(trial_id)
            return hosted

    studio = type("Studio", (), {"trials": _Trials()})
    assert local_trial_id(space, original, lambda: studio) == original
    assert calls == []
    assert local_trial_id(space, "0b6c-hosted", lambda: studio) == original
    hosted["attempt"] = 9
    with pytest.raises(ProjectError, match="not recorded from this project folder"):
        local_trial_id(space, "0b6c-hosted", lambda: studio)
    record_path.write_text(json.dumps(record))


def test_a_fork_continues_from_the_restored_world_with_its_own_history(
    wordle: tuple[Path, dict[str, str]],
) -> None:
    project, env = wordle
    run = _plural(project, env, "run", "-t", "storm", "-a", "scripted", "--yes")
    original = run["trials"][0]["trial_id"]
    assert [step["kind"] for step in _steps(project, original)] == ["action"] * 5
    _hosted_id_names_the_recorded_trial(project, original)

    saved = _plural(project, env, "trial", "checkpoint", original, "--step", "2", "--name", "two")
    assert saved["reference"] == f"{original}/two" and saved["digest"].startswith("sha256:")

    _WordleModel.seen = []
    fork = _plural(
        project,
        env,
        "trial",
        "fork",
        original,
        "--checkpoint",
        "two",
        "--agent",
        "careful",
        "--attempts",
        "1",
    )
    assert fork["history"] == {"native": 2}
    assert fork["controls_reproduced"] == 1.0
    assert fork["candidates"]["careful"]["verdict"] == "too_few"
    trials = _plural(project, env, "job", "show", fork["job_id"])["trials"]
    for trial in trials:
        steps = _steps(project, trial["trial_id"])
        assert [step.get("inherited", False) for step in steps] == [True, True, False, False, False]
        assert [step["arguments"]["word"] for step in steps] == list(GUESSES[:5])
    # The model got the first two guesses as its own conversation, not a reset.
    first = _WordleModel.seen[0]["messages"]
    assert [message["role"] for message in first].count("tool") == 2
    assert "storm" not in json.dumps(first)


def test_a_diagnostic_fork_changes_only_the_candidates(
    wordle: tuple[Path, dict[str, str]],
) -> None:
    project, env = wordle
    original = _plural(project, env, "run", "-t", "storm", "-a", "scripted", "--yes")["trials"][0][
        "trial_id"
    ]
    _WordleModel.seen = []
    fork = _plural(
        project,
        env,
        "trial",
        "fork",
        original,
        "--step",
        "2",
        "--change",
        "message",
        "--payload",
        '{"text": "Hint: think of weather."}',
        "--attempts",
        "1",
    )
    assert fork["diagnostic"] is True
    hinted = [body for body in _WordleModel.seen if "Hint: think of weather." in json.dumps(body)]
    assert hinted and len(hinted) < len(_WordleModel.seen)
    # The original Agent plays both sides, so the controls take attempts after its
    # forks, and a hosted Job recording them needs both.
    from plural.project import Project, Workspace
    from plural.project.runs import local_job_spec

    spec = local_job_spec(Workspace(Project.at(project)), fork["job_id"])
    assert spec.fork is not None and spec.fork.controls_follow
    assert spec.max_attempt == 2
    assert sorted(trial.attempt for trial in spec.plan().trials) == [1, 2]

    forced = _plural(
        project,
        env,
        "trial",
        "fork",
        original,
        "--step",
        "2",
        "--change",
        "action",
        "--payload",
        '{"action": "guess", "arguments": {"word": "storm"}}',
        "--attempts",
        "1",
    )
    trials = _plural(project, env, "job", "show", forced["job_id"])["trials"]
    candidate = next(item for item in trials if item.get("fork", {}).get("role") == "candidate")
    steps = _steps(project, candidate["trial_id"])
    assert steps[2]["source"] == "intervention" and steps[2]["arguments"] == {"word": "storm"}


def test_a_task_from_a_checkpoint_runs_and_scores_in_a_benchmark(
    wordle: tuple[Path, dict[str, str]],
) -> None:
    project, env = wordle
    original = _plural(project, env, "run", "-t", "storm", "-a", "scripted", "--yes")["trials"][0][
        "trial_id"
    ]
    _plural(project, env, "trial", "checkpoint", original, "--step", "2", "--name", "two")
    task = project / "tasks" / "storm-late"
    shutil.copytree(project / "tasks" / "storm", task)
    manifest = (task / "task.yaml").read_text().replace("name: storm", "name: storm-late")
    (task / "task.yaml").write_text(manifest + f"from_checkpoint: {original}/two\n")
    benchmark = project / "benchmarks" / "late"
    shutil.copytree(project / "benchmarks" / "wordle", benchmark)
    text = (benchmark / "benchmark.yaml").read_text().replace("name: wordle", "name: late")
    head, _, rest = text.partition("tasks:\n")
    rest = "\n".join(line for line in rest.splitlines() if not line.startswith("  - "))
    (benchmark / "benchmark.yaml").write_text(f"{head}tasks:\n  - storm-late\n{rest}\n")

    run = _plural(project, env, "run", "-b", "late", "-a", "scripted", "--yes")
    [trial] = run["trials"]
    assert (run["status"], trial["score"]) == ("succeeded", 1.0)
    steps = _steps(project, trial["trial_id"])
    assert [step.get("inherited", False) for step in steps][:2] == [True, True]
    result = json.loads(
        next(
            (project / ".plural" / "jobs").glob(f"*/trials/{trial['trial_id']}/result.json")
        ).read_text()
    )
    assert result["fork"]["from_checkpoint"] == f"{original}/two"
    assert result["fork"]["history"] == "native"


def test_forking_a_held_out_trial_is_refused() -> None:
    from plural.checkpoints import Checkpoint
    from plural.jobs import JobSpec
    from plural.project import Project, Workspace

    space = Workspace(Project.at(ROOT / "examples" / "wordle"))
    job = Job(space.get("task", "storm"), agents=[Agent(model="openai/gpt-5.6-luna")])
    agent = job.spec.agents[0]
    fork = ForkSpec(
        trial_id="trl_x",
        checkpoint=Checkpoint(trial_id="trl_x", step=1, heldout=True),
        control_agent_id=agent.agent_id,
        candidate_agent_ids=(agent.agent_id,),
        change=ForkChange(name="message", payload={"text": "x"}),
    )
    fields = {name: getattr(job.spec, name) for name in JobSpec.model_fields}
    with pytest.raises(ValueError, match="held-out"):
        JobSpec.model_validate({**fields, "purpose": "fork", "fork": fork})


def test_a_recorded_fork_names_the_original_by_its_hosted_id() -> None:
    from plural.execution.report import fork_report
    from plural.jobs import ForkRecord

    local = ForkRecord(
        of_trial_id="trl_local",
        step=4,
        role="candidate",
        history="native",
        checkpoint_digest="sha256:" + "c" * 64,
    )
    assert fork_report(local)["of_trial_id"] == "trl_local"
    hosted = fork_report(local.model_copy(update={"of_hosted_trial_id": "d1205aff"}))
    assert hosted["of_trial_id"] == "d1205aff"
    assert "of_hosted_trial_id" not in hosted


def test_a_checkpoint_warns_about_a_background_process() -> None:
    from plural.checkpoints import background_warnings

    started = [
        {
            "step": 1,
            "action": "shell",
            "arguments": {"command": "/bin/zsh -lc 'serve >/dev/null 2>&1 &'"},
        },
        {"step": 2, "action": "Bash", "arguments": {"command": "nohup ./worker"}},
        {"step": 3, "action": "shell", "arguments": {"command": ["sh", "-c", "sleep 9 & echo"]}},
    ]
    quiet = [
        {"step": 4, "action": "shell", "arguments": {"command": "make test 2>&1 && echo ok"}},
        {"step": 5, "action": "Bash", "arguments": {"command": "curl 'h/?a=1&b=2' &>log"}},
    ]
    warnings = background_warnings([*started, *quiet])
    assert [warning.split(" started")[0] for warning in warnings] == ["Step 1", "Step 2", "Step 3"]
