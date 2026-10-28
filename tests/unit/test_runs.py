"""`plural run`, Jobs, Trials, and reruns in the standard project layout, offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural.cli.main import app
from plural.environments import Party
from plural.project import Project, ProjectError, Workspace
from plural.project.layout import ResourceRef
from plural.project.runs import DEFAULT_HARNESS, RunRequest, plan_run

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path) -> Project:
    created = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(created.root)
    return created


def cli(*args: str) -> tuple[int, str, Any]:
    result = runner.invoke(app, list(args))
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    payload = None
    if "--json" in args and result.exit_code == 0:
        payload = json.loads(result.stdout)
    return result.exit_code, result.output, payload


def plan(project: Project, **fields: Any) -> Any:
    return plan_run(Workspace(project), RunRequest(**fields))


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"model": "openai/gpt-5.6-luna"}, "exactly one of --task or --benchmark"),
        (
            {"task": "refund", "benchmark": "basics", "model": "openai/gpt-5.6-luna"},
            "exactly one of --task or --benchmark",
        ),
        ({"task": "refund"}, "--model"),
        (
            {"task": "refund", "agent": "baseline", "model": "openai/gpt-5.6-luna"},
            "Use --agent alone",
        ),
        ({"task": "refund", "agent": "baseline", "harness": "native"}, "Use --agent alone"),
    ],
)
def test_run_sources_and_agents_are_validated(
    project: Project, fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(ProjectError, match=message):
        plan(project, **fields)


def test_an_environment_party_reaches_the_task_and_plural_run_names_the_way_to_run_it(
    project: Project,
) -> None:
    manifest = project.root / "environments/queue/environment.yaml"
    local = manifest.read_text()
    manifest.write_text(local + "party: {min: 2, max: 8}\n")
    with pytest.raises(ProjectError, match="OS user of its own"):
        Workspace(project).load(ResourceRef("task", "refund"))
    docker = local.replace("provider: local", "provider: docker")
    manifest.write_text(docker + "party: {min: 2, max: 8}\n")
    task = Workspace(project).load(ResourceRef("task", "refund")).value
    assert task._environment_definition().party == Party(min=2, max=8)
    with pytest.raises(ProjectError, match="party of Agents.*Job"):
        plan(project, task="refund", model="openai/gpt-5.6-luna")


def test_model_runs_default_to_the_documented_harness_and_respect_the_policy(
    project: Project,
) -> None:
    default = plan(project, task="refund", model="openai/gpt-5.6-luna")
    assert default.harness == DEFAULT_HARNESS == "native"

    manifest = project.root / "environments/queue/environment.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "mode: allow_all", "mode: allowlist\n  allowed_harnesses: [scripted]"
        )
    )
    with pytest.raises(ProjectError, match="does not allow Harness 'native'.*--harness"):
        plan(project, task="refund", model="openai/gpt-5.6-luna")
    chosen = plan(project, task="refund", model="openai/gpt-5.6-luna", harness="scripted")
    assert chosen.harness == "scripted"


def test_every_plan_is_a_new_job_with_pinned_inputs(project: Project) -> None:
    first = plan(project, benchmark="basics", agent="baseline")
    second = plan(project, benchmark="basics", agent="baseline")
    assert first.spec.job_id != second.spec.job_id
    assert first.pins == second.pins
    pinned = first.pins
    assert set(pinned) == {
        "environment/queue",
        "verifier/resolved",
        "task/refund",
        "task/deny",
        "harness/scripted",
        "agent/baseline",
        "benchmark/basics",
    }
    assert all(item["content_hash"].startswith("sha256:") for item in pinned.values())
    assert len(first.job.plan.trials) == 2


def test_dry_run_reports_the_plan_without_creating_a_job(project: Project) -> None:
    code, output, payload = cli("run", "-b", "basics", "-a", "baseline", "--dry-run", "--json")
    assert code == 0, output
    assert payload["location"] == "local"
    assert payload["harness"] == "scripted"
    assert len(payload["trials"]) == 2
    assert not project.jobs_dir.exists() or not any(project.jobs_dir.iterdir())


def test_an_endpoint_agent_needs_its_own_key_and_no_plural_key(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = project.root / "agents/tuned/agent.yaml"
    agent.parent.mkdir(parents=True)
    agent.write_text(
        "name: tuned\nversion: 0.1.0\nmodel: tuned-v1\n"
        "endpoint: http://127.0.0.1:9/v1\nendpoint_key: TUNED_KEY\n"
    )
    monkeypatch.delenv("TUNED_KEY", raising=False)
    code, output, _ = cli("run", "--task", "refund", "--agent", "tuned")
    assert code == 1
    assert "needs TUNED_KEY for its endpoint" in output
    assert not project.jobs_dir.exists() or not any(project.jobs_dir.iterdir())

    monkeypatch.setenv("TUNED_KEY", "sk-tuned")
    code, output, _ = cli("run", "--task", "refund", "--agent", "tuned")
    assert code == 1
    assert "Cannot reach the model server at http://127.0.0.1:9/v1" in output
    assert "Plural API key" not in output
    assert "sk-tuned" not in output


def test_an_app_credential_comes_from_the_agent_that_runs(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = project.root / "environments/queue/environment.py"
    app.write_text(
        app.read_text().replace(
            '''    """A refund queue."""\n''',
            '''    """A refund queue."""\n\n    credentials = ["QUEUE_TOKEN"]\n''',
        )
    )
    monkeypatch.setenv("QUEUE_TOKEN", "queue-token-value")

    code, output, _ = cli("run", "--task", "refund", "--model", "openai/gpt-5.6-luna")
    assert code == 1
    assert "does not carry" in output
    assert "QUEUE_TOKEN, for App queue" in output
    assert "This run used --model" in output

    code, output, _ = cli("run", "--task", "refund", "--agent", "baseline")
    assert code == 1
    assert "Agent 'baseline' does not carry" in output
    assert not project.jobs_dir.exists() or not any(project.jobs_dir.iterdir())

    agent = project.root / "agents/baseline/agent.yaml"
    agent.write_text(agent.read_text() + "credentials:\n  QUEUE_TOKEN:\n    scopes: [read:queue]\n")
    monkeypatch.delenv("QUEUE_TOKEN")
    code, output, _ = cli("run", "--task", "refund", "--agent", "baseline")
    assert code == 1
    assert "plural credential set NAME" in output

    monkeypatch.setenv("QUEUE_TOKEN", "queue-token-value")
    code, output, job = cli("run", "--task", "refund", "--agent", "baseline", "--json")
    assert code == 0, output
    assert "queue-token-value" not in output
    [trial] = job["trials"]
    code, output, shown = cli("trial", "show", trial["trial_id"], "--json")
    assert code == 0, output
    [used] = shown["credentials"]
    assert used["app"] == "queue"
    assert used["agent"] == "baseline"
    assert used["scopes"] == ["read:queue"]
    assert used["source"] == "environment"
    assert used["fingerprint"].startswith("sha256:")
    code, output, _ = cli("trial", "show", trial["trial_id"])
    assert "Credential QUEUE_TOKEN for App queue: Agent baseline" in output
    for path in project.jobs_dir.rglob("*"):
        if path.is_file():
            assert b"queue-token-value" not in path.read_bytes(), path


def test_local_run_records_a_job_and_trials_can_be_inspected(project: Project) -> None:
    code, output, job = cli("run", "--task", "refund", "--agent", "baseline", "--json")
    assert code == 0, output
    assert job["location"] == "local"
    assert job["status"] == "succeeded"
    [trial] = job["trials"]
    assert trial["score"] == 1.0

    record = json.loads((project.jobs_dir / job["job_id"] / "run.json").read_text())
    assert record["source"] == "task/refund"
    assert set(record["inputs"]) >= {"task/refund", "agent/baseline", "harness/scripted"}
    assert record["harness"] == "scripted"

    code, output, listed = cli("job", "list", "--json")
    assert code == 0, output
    assert [item["job_id"] for item in listed] == [job["job_id"]]
    assert listed[0]["location"] == "local"

    code, output, shown = cli("trial", "show", trial["trial_id"], "--json")
    assert code == 0, output
    assert shown["job_id"] == job["job_id"]
    assert shown["verifiers"][0]["score"] == 1.0

    code, output, again = cli("run", "--task", "refund", "--agent", "baseline", "--json")
    assert code == 0, output
    assert again["job_id"] != job["job_id"]


def test_reruns_use_the_pinned_inputs_and_link_to_the_original(project: Project) -> None:
    code, output, job = cli("run", "--benchmark", "basics", "--agent", "baseline", "--json")
    assert code == 0, output
    scores = sorted(item["score"] for item in job["trials"])
    assert scores == [0.0, 1.0]

    # Local edits after the run must not change what a rerun executes.
    harness = project.root / "harnesses/scripted/harness.yaml"
    harness.write_text(harness.read_text().replace("answer: refunded", "answer: denied"))
    verifier = project.root / "verifiers/resolved/verify.py"
    verifier.write_text(verifier.read_text().replace("float(correct)", "0.5"))

    code, output, rerun = cli("job", "rerun", job["job_id"], "--json")
    assert code == 0, output
    assert rerun["job_id"] != job["job_id"]
    assert rerun["rerun_of_job_id"] == job["job_id"]
    assert rerun["inputs"] == job["inputs"]
    assert sorted(item["score"] for item in rerun["trials"]) == scores
    assert {item["trial_id"] for item in rerun["trials"]}.isdisjoint(
        item["trial_id"] for item in job["trials"]
    )

    original = next(item for item in job["trials"] if item["task"] == "refund")
    code, output, trial_rerun = cli("trial", "rerun", original["trial_id"], "--json")
    assert code == 0, output
    assert trial_rerun["rerun_of_trial_id"] == original["trial_id"]
    [only] = trial_rerun["trials"]
    assert only["task"] == "refund"
    assert only["trial_id"] != original["trial_id"]
    assert only["score"] == 1.0

    code, output, fresh = cli("run", "--benchmark", "basics", "--agent", "baseline", "--json")
    assert code == 0, output
    assert sorted(item["score"] for item in fresh["trials"]) == [0.5, 0.5]


def test_live_model_runs_need_a_model_credential(project: Project) -> None:
    code, output, _ = cli("run", "-t", "refund", "-m", "openai/gpt-5.6-luna")
    assert code == 1
    assert "Plural gateway" in output
    assert "PLURAL_API_KEY" in output


def test_a_provider_key_is_never_sent_to_the_plural_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plural.auth import Credential, Session
    from plural.cli.run_commands import _run_environ

    for name in ("PLURAL_API_KEY", "PLURAL_GATEWAY_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-provider")

    def session(credential: Credential | None) -> Session:
        return Session(
            profile="default",
            api_url="https://plural.example",
            credential=credential,
            environment_key=None,
            account_id=None,
            project=None,
            project_slug=None,
        )

    login = _run_environ(session(Credential(access_token="login-token")))
    assert "PLURAL_GATEWAY_URL" not in login
    assert "PLURAL_API_KEY" not in login
    assert login["OPENAI_API_KEY"] == "sk-provider"

    keyed = _run_environ(session(Credential(api_key="plural_key")))
    assert keyed["PLURAL_API_KEY"] == "plural_key"
    assert keyed["PLURAL_GATEWAY_URL"] == "https://plural.example/v1"


def test_verifier_data_never_reaches_the_harness(project: Project, tmp_path: Path) -> None:
    seen = tmp_path / "seen.json"
    harness = project.root / "harnesses/scripted/harness.py"
    harness.write_text(
        harness.read_text().replace(
            "environment.reset()",
            "environment.reset()\n"
            "        import json, pathlib\n"
            "        pathlib.Path(self.config['seen']).write_text(json.dumps({\n"
            "            'task': task.raw, 'agent': repr(agent),\n"
            "            'environment': environment.raw}, default=str))",
        )
    )
    manifest = project.root / "harnesses/scripted/harness.yaml"
    manifest.write_text(manifest.read_text() + f"  seen: {seen}\n")
    verifier = project.root / "verifiers/resolved/verify.py"
    verifier.write_text(verifier.read_text().replace("expected={expected}", "SECRET-{expected}"))

    code, output, job = cli("run", "--task", "refund", "--agent", "baseline", "--json")
    assert code == 0, output
    assert job["trials"][0]["score"] == 1.0
    visible = seen.read_text()
    assert "Review order A-1" in visible
    for private in ("SECRET", "verify.py", "resolved", '"score"', "refundable"):
        assert private not in visible, private


def test_a_verifier_tries_and_applies_its_rewards_on_a_stored_trial(
    project: Project,
) -> None:
    code, output, job = cli("run", "--task", "refund", "--agent", "baseline", "--json")
    assert code == 0, output
    [trial] = job["trials"]
    directory = project.root / "verifiers/resolved"
    (directory / "verifier.yaml").write_text(
        (directory / "verifier.yaml")
        .read_text()
        .replace("version: 0.1.0", "version: 0.2.0")
        .replace(
            "reward: verify.py:reward", "reward: verify.py:reward\nhindsight: verify.py:scored"
        )
    )
    source = (directory / "verify.py").read_text()
    (directory / "verify.py").write_text(
        source.replace(
            'return 1.0 if step.current_state["done"] else 0.0',
            'return 0.5 if step.apps["queue"].state.done else 0.0',
        )
        + "\n\nfrom plural import HindsightTrial, RewardTarget\n\n\n"
        "def scored(trial: HindsightTrial):\n"
        "    for step in trial.steps('submit'):\n"
        "        yield trial.credit(RewardTarget.step(step['event_id']), trial.score or 0)\n"
    )
    ledger_before = cli("reward", "show", trial["trial_id"], "--json")[2]

    code, output, tried = cli("verifier", "try", "resolved", "--trial", trial["trial_id"], "--json")
    assert code == 0, output
    [result] = tried["trials"]
    assert result["problems"] == []
    assert result["score"] == 1.0
    assert result["step_total"] == 0.5
    assert result["hindsight_total"] == 1.0
    assert cli("reward", "show", trial["trial_id"], "--json")[2] == ledger_before

    code, output, applied = cli(
        "verifier", "apply", "resolved", "--trial", trial["trial_id"], "--json"
    )
    assert code == 0, output
    assert applied["version"] == "0.2.0"
    assert applied["trials"][0]["new_records"] == 2
    code, output, ledger = cli("reward", "show", trial["trial_id"], "--json")
    assert [(item["source"], item["version"], item["value"]) for item in ledger] == [
        ("step", "0.1.0", 1.0),
        ("step", "0.2.0", 0.5),
        ("hindsight", "0.2.0", 1.0),
    ]
    assert ledger[0]["target"] == ledger[1]["target"] == ledger[2]["target"]

    code, output, again = cli(
        "verifier", "apply", "resolved", "--trial", trial["trial_id"], "--json"
    )
    assert code == 0, output
    assert again["trials"][0]["new_records"] == 0
    assert again["trials"][0]["skipped"] == ["hindsight", "step"]

    out = project.root / "train.jsonl"
    code, output, _ = cli(
        "reward",
        "export",
        "--job",
        job["job_id"],
        "--verifier",
        "resolved@0.2.0",
        "--out",
        str(out),
    )
    assert code == 0, output
    [line] = out.read_text().splitlines()
    exported = json.loads(line)
    assert exported["trial_id"] == trial["trial_id"]
    assert exported["score"] == 1.0
    assert sorted(item["value"] for item in exported["rewards"]) == [0.5, 1.0]


def test_run_has_no_traces_option(project: Project) -> None:
    code, output, _ = cli("run", "--task", "refund", "--traces", "traces.jsonl")

    assert code != 0
    assert "No such option" in output
