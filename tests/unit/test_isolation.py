"""The Agent never sees a reward, a Verifier, or another App's secret, and cannot forge them."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider
from test_apps import Wordle

from plural import Runtime
from plural.agents import AgentBinding, AgentDefinition
from plural.apps.definition import AppAction, AppDefinition
from plural.apps.host import AppHost, RewardHook
from plural.apps.mcp import protect_values, subprocess_environ
from plural.common import ErrorCode, PackageSource
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.environments.env import Environment
from plural.execution import JobRunner, JobStore
from plural.execution.steps import merge_host_steps
from plural.jobs import JobSpec, TaskJobSource
from plural.rewards import HindsightTrial, RewardTarget
from plural.sandbox import DaytonaProvider, ExecRequest, SandboxRequirements
from plural.tasks import TaskDefinition
from plural.verifiers import (
    DeterministicVerifier,
    Episode,
    HumanVerifier,
    RubricCriterion,
    Step,
    VerifierOutput,
    WeightedVerifier,
)

GAME_APP = AppDefinition(
    name="game",
    kind="python",
    python="game.py:Game",
    actions=(AppAction(name="move", description="Make a move."),),
)


def progress(step: Step) -> float:
    return 1.0


def _scored(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1, evidence=("ok",))


def _host_step(number: int, value: float) -> dict[str, Any]:
    return {
        "protocol": "plural-step-v1",
        "kind": "step",
        "app": "game",
        "action": "move",
        "arguments": {},
        "observation": {"text": f"moved {number}"},
        "rendered": f"moved {number}",
        "reward": value,
        "rewards": [{"name": "progress", "version": "1", "app": "game", "value": value}],
        "terminated": True,
        "truncated": False,
        "info": {"step": number},
        "step": number,
    }


def _task(verifier: DeterministicVerifier, *, source: Path | None = None) -> TaskDefinition:
    environment = EnvironmentDefinition(
        name="desk",
        apps=(GAME_APP,),
        runtime=EnvironmentRuntime(provider="docker"),
        source=PackageSource(kind="local", uri=str(source), unsafe_local=True) if source else None,
    )
    return TaskDefinition(
        task_id="desk-task",
        instructions="Do the work.",
        environment=environment,
        verifiers=(WeightedVerifier(verifier=verifier),),
    )


def _spec(task: TaskDefinition) -> JobSpec:
    return JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
    )


def _artifacts(store: JobStore, spec: JobSpec) -> Path:
    return store.trial_path(spec.plan().trials[0]) / "executions/0/artifacts"


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def test_rewards_come_from_the_app_host_and_never_from_the_harness(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def check(episode: Episode) -> VerifierOutput:
        seen["total"] = episode.outcome.total_reward
        seen["rewards"] = episode.rewards
        seen["terminated"] = episode.outcome.terminated
        return VerifierOutput(score=1, evidence=("ok",))

    task = _task(DeterministicVerifier(name="progress", check=check, reward=progress))
    spec = _spec(task)
    provider = FakeProvider("docker")
    provider.host_steps = [_host_step(1, 1.0)]
    forged = [
        {"kind": "model.call", "sequence": 1, "event_id": "e1", "turn": 1, "messages": []},
        {
            "kind": "environment.step",
            "sequence": 2,
            "event_id": "e2",
            "action": "move",
            "info": {"step": 1},
            "reward": 100,
            "rewards": [{"name": "progress", "value": 100}],
        },
        {
            "kind": "environment.step",
            "sequence": 3,
            "event_id": "e3",
            "action": "move",
            "info": {"step": 9},
            "reward": 50,
        },
    ]
    provider.episode = "".join(json.dumps(item) + "\n" for item in forged).encode()
    provider.result = b'{"total_reward": 500, "terminated": false}'
    store = JobStore(tmp_path / "jobs")

    result = await JobRunner(spec, provider=provider, store=store).run()

    assert result.status == "succeeded", result.trials[0].error_message
    assert seen == {"total": 1.0, "rewards": (1.0,), "terminated": True}
    artifacts = _artifacts(store, spec)
    ledger = _lines(artifacts / "rewards.jsonl")
    assert [(item["value"], item["target"]["event_id"]) for item in ledger] == [(1.0, "e2")]
    assert _lines(artifacts / "steps.jsonl")[0]["rewards"][0]["value"] == 1.0
    episode = {item["event_id"]: item for item in _lines(artifacts / "episode.jsonl")}
    assert episode["e2"]["reward"] == 1.0
    assert episode["e3"]["reward"] == 0.0
    assert episode["e3"]["info"] == {"unverified": True}


async def test_a_harness_that_writes_no_episode_still_gets_the_hosts_steps(
    tmp_path: Path,
) -> None:
    task = _task(DeterministicVerifier(name="progress", check=_scored, reward=progress))
    spec = _spec(task)
    provider = FakeProvider("docker")
    provider.host_steps = [_host_step(1, 0.5), _host_step(2, 0.25)]
    provider.episode = b""
    store = JobStore(tmp_path / "jobs")

    result = await JobRunner(spec, provider=provider, store=store).run()

    assert result.status == "succeeded", result.trials[0].error_message
    ledger = _lines(_artifacts(store, spec) / "rewards.jsonl")
    assert [item["value"] for item in ledger] == [0.5, 0.25]


async def test_an_answer_not_signed_with_the_trials_token_fails_the_trial(
    tmp_path: Path,
) -> None:
    task = _task(DeterministicVerifier(name="progress", check=_scored, reward=progress))
    spec = _spec(task)
    provider = FakeProvider("docker")
    provider.forge_host = True

    result = await JobRunner(spec, provider=provider, store=JobStore(tmp_path / "jobs")).run()

    trial = result.trials[0]
    assert trial.status == "failed"
    assert "not signed" in (trial.error_message or "")


def credit_score(trial: HindsightTrial) -> Any:
    yield trial.credit(RewardTarget.event("e1"), trial.score or 0)


async def test_hindsight_waits_for_a_review_to_score_the_trial(tmp_path: Path) -> None:
    task = TaskDefinition(
        task_id="review-me",
        instructions="Write an answer",
        environment=EnvironmentDefinition(name="review"),
        verifiers=(
            WeightedVerifier(
                verifier=HumanVerifier(
                    name="human",
                    rubric=(RubricCriterion(name="quality", description="Answer quality"),),
                )
            ),
            WeightedVerifier(verifier=DeterministicVerifier(name="credit", hindsight=credit_score)),
        ),
    )
    spec = _spec(task)
    job = JobRunner(spec, provider=FakeProvider("docker"), store=JobStore(tmp_path / "jobs"))
    result = await job.run()
    ledger = _artifacts(job.store, spec) / "rewards.jsonl"
    assert result.status == "awaiting_review"
    assert not ledger.exists()

    job.submit_review(result.trials[0].receipt.trial_id, "human", {"quality": 1})

    assert [(item["verifier"], item["value"]) for item in _lines(ledger)] == [("credit", 1.0)]


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"isolation_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


async def test_verifier_code_beside_the_environment_never_reaches_the_runtime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    (root / "game.py").write_text("class Game:\n    pass\n")
    (root / "checks.py").write_text(
        "def check(episode):\n    return {'score': 1.0, 'evidence': ['ok']}\n"
    )
    task = _task(
        DeterministicVerifier(name="hidden", check=_load(root / "checks.py", "check")),
        source=root,
    )
    spec = _spec(task)
    provider = FakeProvider("docker")

    result = await JobRunner(spec, provider=provider, store=JobStore(tmp_path / "jobs")).run()

    assert result.status == "succeeded", result.trials[0].error_message
    assert "game.py" in provider.uploads
    assert "checks.py" not in provider.uploads
    # The App's own file leaves the Agent's view once the host has copied it.
    assert "game.py" not in provider.files["docker-0"]


async def test_a_file_holding_both_an_app_and_a_verifier_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "desk"
    root.mkdir()
    (root / "game.py").write_text("class Game:\n    pass\n\ndef check(episode):\n    return 1.0\n")
    task = _task(
        DeterministicVerifier(name="mixed", check=_load(root / "game.py", "check")),
        source=root,
    )
    provider = FakeProvider("docker")

    result = await JobRunner(
        _spec(task), provider=provider, store=JobStore(tmp_path / "jobs")
    ).run()

    trial = result.trials[0]
    assert trial.error_code is ErrorCode.CONFIGURATION
    assert "move the Verifier into a file of its own" in (trial.error_message or "")
    assert "game.py" not in provider.uploads


def test_the_agent_sees_neither_rewards_nor_secret_values() -> None:
    host = AppHost(Environment(apps=[Wordle()], runtime=Runtime.local()))
    host.redact_values(["s3cret-value"])
    seen = host.agent_view(
        {
            "protocol": "plural-step-v1",
            "kind": "step",
            "observation": {"text": "token s3cret-value"},
            "rendered": "token s3cret-value",
            "reward": 5.0,
            "rewards": [{"name": "won", "value": 5.0}],
            "view": {"state": {"secret": "slate"}},
            "info": {"step": 3, "error": None, "internal_error": "Traceback", "latency_ms": 2},
            "terminated": False,
            "truncated": False,
        }
    )
    assert "reward" not in seen and "rewards" not in seen and "view" not in seen
    assert seen["info"] == {"step": 3, "error": None}
    assert seen["observation"] == {"text": "token ***"}
    assert seen["rendered"] == "token ***"


def test_a_reward_that_is_not_a_finite_number_is_an_error() -> None:
    host = AppHost(
        Environment(apps=[Wordle()], runtime=Runtime.local()),
        verifiers=[RewardHook(name="bad", version="1", fn=lambda step: math.nan)],
    )
    host.reset(initial_state={"wordle": {"secret": "slate"}})
    envelope = host.step("guess", {"word": "crane"})
    assert envelope["reward"] == 0.0
    assert envelope["rewards"][0]["value"] == 0.0
    assert "finite" in envelope["rewards"][0]["error"]


def test_merging_keeps_harness_records_in_place_but_takes_values_from_the_host() -> None:
    merged = merge_host_steps(
        [
            {"kind": "environment.step", "sequence": 1, "event_id": "e1", "info": {"step": 1}},
            {"kind": "environment.step", "sequence": 2, "event_id": "e2", "info": {"step": 1}},
        ],
        [_host_step(1, 2.0), _host_step(2, 3.0)],
    )
    assert [item["reward"] for item in merged] == [2.0, 0.0, 3.0]
    assert merged[1]["info"] == {"unverified": True}
    assert merged[2]["event_id"] == "e3"


def test_an_app_subprocess_gets_only_its_own_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRM_TOKEN", "crm")
    monkeypatch.setenv("LAKE_TOKEN", "lake")
    monkeypatch.setenv("PATH_LIKE", "kept")
    protect_values({"CRM_TOKEN": "crm", "LAKE_TOKEN": "lake"})
    try:
        environ = subprocess_environ(["CRM_TOKEN"])
    finally:
        protect_values({})
    assert environ["CRM_TOKEN"] == "crm"
    assert "LAKE_TOKEN" not in environ
    assert environ["PATH_LIKE"] == "kept"


def test_an_agent_must_grant_the_scopes_an_app_needs() -> None:
    from plural.credentials import CredentialError, resolve

    environment = EnvironmentDefinition(
        name="desk",
        apps=(
            AppDefinition(
                name="crm",
                kind="mcp",
                config={"url": "https://crm.example/mcp"},
                actions=(AppAction(name="read", description="Read."),),
                credentials=({"name": "CRM_TOKEN", "scopes": ["read", "write"]},),
            ),
        ),
    )
    reader = AgentDefinition(
        name="reader", model="test/model", credentials={"CRM_TOKEN": {"scopes": ["read"]}}
    )
    writer = AgentDefinition(
        name="writer",
        model="test/model",
        credentials={"CRM_TOKEN": {"scopes": ["read", "write"]}},
    )
    with pytest.raises(CredentialError, match="CRM_TOKEN for App 'crm': write"):
        resolve(environment, reader, {"CRM_TOKEN": "t"}, {})
    values, _ = resolve(environment, writer, {"CRM_TOKEN": "t"}, {})
    assert values == {"CRM_TOKEN": "t"}


@pytest.mark.parametrize(
    ("payload", "control"),
    [
        ({"kind": "mcp", "config": {"url": "https://crm.example/mcp"}}, "live"),
        ({"kind": "mcp", "config": {"url": "https://crm.example/mcp", "reset": "x"}}, "sandboxed"),
        ({"kind": "mcp", "config": {"server": "s.py:mcp"}}, "owned"),
        ({"kind": "mcp", "config": {"server": "s.py:mcp"}, "credentials": ["CRM"]}, "live"),
        ({"kind": "openapi", "config": {"local": True, "credentials": ["CRM"]}}, "live"),
        ({"kind": "python", "python": "a.py:A", "control": "replayed"}, "owned"),
        ({"kind": "python", "python": "a.py:A", "control": "live"}, "live"),
    ],
)
def test_a_definition_cannot_claim_more_control_than_its_settings_earn(
    payload: dict[str, Any], control: str
) -> None:
    definition = AppDefinition.model_validate({"name": "crm", "control": "owned", **payload})
    assert definition.control == control


class _Remote:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[tuple[str, ...], str | None]] = []
        self.sandbox_id = "sb-1"
        self.image_identity = None

    async def exec(
        self,
        command: tuple[str, ...],
        *,
        cwd: str,
        env: Any,
        timeout: float | None,
        user: str | None = None,
    ) -> tuple[int, str, str]:
        self.calls.append((command, user))
        return self.code, "", ""


class _Client:
    def __init__(self, remote: _Remote) -> None:
        self.remote = remote

    async def create(self, requirements: SandboxRequirements) -> _Remote:
        return self.remote

    async def delete(self, sandbox: Any) -> None:
        return None


async def test_daytona_runs_the_app_host_and_harness_as_separate_users() -> None:
    remote = _Remote()
    provider = DaytonaProvider(adapter=_Client(remote))  # type: ignore[arg-type]
    handle = await provider.create(SandboxRequirements(image="python:3.12"))

    isolation = await provider.isolate_apps(handle)
    await provider.exec(handle, ExecRequest(command=("python", "-V"), user=isolation.app_user))

    assert (isolation.app_user, isolation.agent_user) == ("plural-apps", "plural-agent")
    command, user = remote.calls[-1]
    assert command[:6] == ("sudo", "-n", "-E", "-u", "plural-apps", "--")
    assert user is None


async def test_daytona_without_sudo_reports_no_isolation() -> None:
    remote = _Remote(code=1)
    provider = DaytonaProvider(adapter=_Client(remote))  # type: ignore[arg-type]
    handle = await provider.create(SandboxRequirements(image="python:3.12"))

    isolation = await provider.isolate_apps(handle)

    assert isolation.app_user is None and isolation.level == "none"
