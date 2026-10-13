"""A Harness cannot act after its run, re-roll a timeout, or plant what the Job stores."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider
from test_apps import Wordle
from test_apps import workspace as workspace  # noqa: F401 - the fixture

from plural import App, Runtime, action
from plural.agents import AgentBinding, AgentDefinition
from plural.apps import daemon
from plural.apps.definition import AppAction, AppDefinition, SecretReference
from plural.apps.host import EPISODE_OVER, AppHost
from plural.common import ErrorCode, FileDeclaration, HarnessBinding
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.environments.env import Environment
from plural.execution import JobRunner, JobStore
from plural.execution.steps import merge_host_steps
from plural.harness.packages import native_actions_v1
from plural.jobs import JobSpec, RetryPolicy, TaskJobSource
from plural.sandbox import (
    DaytonaProvider,
    DockerProvider,
    DownloadedFile,
    ExecRequest,
    ExecResult,
    SandboxHandle,
    SandboxRequirements,
)
from plural.sandbox.base import KILL_USER_PROCESSES
from plural.sandbox.daytona import _CHECK_ARTIFACT
from plural.tasks import TaskDefinition
from plural.verifiers import DeterministicVerifier, Episode, Step, VerifierOutput, WeightedVerifier

SECRET = "admin-secret-value"


def _progress(step: Step) -> float:
    return 1.0


def _scored(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1, evidence=("ok",))


def _task(verifier: DeterministicVerifier) -> TaskDefinition:
    game = AppDefinition(
        name="game",
        kind="python",
        python="game.py:Game",
        actions=(AppAction(name="move", description="Make a move."),),
        secrets=(SecretReference(name="GAME_ADMIN"),),
    )
    return TaskDefinition(
        task_id="desk-task",
        instructions="Do the work.",
        environment=EnvironmentDefinition(
            name="desk", apps=(game,), runtime=EnvironmentRuntime(provider="docker")
        ),
        verifiers=(WeightedVerifier(verifier=verifier),),
    )


def _spec(task: TaskDefinition, agent: AgentDefinition | None = None, **fields: Any) -> JobSpec:
    return JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=agent or AgentDefinition(name="agent", model="test/model")),),
        **fields,
    )


def _host_step(number: int, **info: Any) -> dict[str, Any]:
    return {
        "protocol": "plural-step-v1",
        "kind": "step",
        "app": "game",
        "action": "move",
        "arguments": {"to": number},
        "observation": {"text": f"moved {number}"},
        "rendered": f"moved {number}",
        "reward": 1.0,
        "rewards": [{"name": "progress", "version": "1", "app": "game", "value": 1.0}],
        "terminated": False,
        "truncated": False,
        "info": {"step": number, **info},
        "step": number,
    }


def _artifacts(store: JobStore, spec: JobSpec) -> Path:
    return store.trial_path(spec.plan().trials[0]) / "executions/0/artifacts"


def _environ(**values: str) -> dict[str, str]:
    return {**os.environ, "GAME_ADMIN": SECRET, **values}


# The App host after the Job's finish.


def test_a_finished_host_runs_no_action_reset_or_turn() -> None:
    host = AppHost(Environment(apps=[Wordle()], runtime=Runtime.local()), seats=())
    host.reset(initial_state={"wordle": {"secret": "slate"}})
    host.step("guess", {"word": "crane"})
    host.finish()

    late = host.step("guess", {"word": "slate"})

    assert late["info"] == {"error": EPISODE_OVER}
    assert host.agent_reset()["info"]["error"] == EPISODE_OVER
    assert [step["action"] for step in host.report()["steps"]] == ["guess"]
    assert host.apps["wordle"].state.solved is False


def test_a_finished_seat_host_tells_no_seat_it_may_act() -> None:
    host = AppHost(Environment(apps=[Wordle()], runtime=Runtime.local()), seats=("seat_1",))
    host.reset()
    host.finish()

    assert host.seat_view("seat_1")["your_turn"] is False
    assert host.step("guess", {"word": "slate"}, seat="seat_1")["info"]["error"] == EPISODE_OVER


def test_after_the_jobs_finish_the_daemon_refuses_the_harness(workspace: Path) -> None:  # noqa: F811
    daemon.start(workspace, token="job-only")
    try:
        daemon.call("step", root=workspace, action="guess", arguments={"word": "crane"})
        daemon.call("finish", root=workspace, token="job-only")
        for operation, fields in (
            ("step", {"action": "guess", "arguments": {"word": "slate"}}),
            ("reset", {}),
            ("turn", {}),
        ):
            with pytest.raises(RuntimeError, match="episode is over"):
                daemon.call(operation, root=workspace, **fields)
        report = daemon.call("finish", root=workspace, token="job-only")
        assert [step["action"] for step in report["steps"]] == ["guess"]
        # Verifiers still read the Apps.
        listed = daemon.call(
            "query", root=workspace, token="job-only", app="crm", action="list_records"
        )
        assert listed == {"records": []}
    finally:
        daemon.call("stop", root=workspace, token="job-only")


def test_a_job_host_outlives_the_harness_deleting_the_workspace(workspace: Path) -> None:  # noqa: F811
    daemon.start(workspace, token="job-only")
    try:
        shutil.rmtree(workspace)
        time.sleep(1.5)
        assert daemon.running(workspace)
    finally:
        daemon.call("stop", root=workspace, token="job-only")
    deadline = time.monotonic() + 5
    while daemon.running(workspace) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not daemon.running(workspace)


class _Ordered(FakeProvider):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.order: list[str] = []
        self.stopped: list[Sequence[str | None]] = []

    async def stop_user_processes(self, handle: SandboxHandle, users: Sequence[str | None]) -> None:
        self.order.append("stop")
        self.stopped.append(tuple(users))

    async def download_artifacts(
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str = "/workspace",
        user: str | None = None,
    ) -> tuple[DownloadedFile, ...]:
        self.order.append("download")
        return await super().download_artifacts(handle, paths, root=root, user=user)

    def _app_host(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.command[3] == "control":
            self.order.append("host")
        return super()._app_host(handle, request)


async def test_the_job_kills_harness_processes_before_reading_files_or_finishing(
    tmp_path: Path,
) -> None:
    spec = _spec(_task(DeterministicVerifier(name="progress", check=_scored, reward=_progress)))
    provider = _Ordered("docker")

    result = await JobRunner(
        spec, provider=provider, store=JobStore(tmp_path / "jobs"), environ=_environ()
    ).run()

    assert result.status == "succeeded", result.trials[0].error_message
    after = provider.order[provider.order.index("stop") :]
    assert after[:2] == ["stop", "download"]
    assert "host" in after
    assert provider.stopped == [(None,)]


class _Docker(DockerProvider):
    def __init__(self) -> None:
        super().__init__()
        self._containers.add("c1")
        self.calls: list[tuple[str, ...]] = []

    async def _run(self, *args: str, **_: Any) -> tuple[int, bytes, bytes]:
        self.calls.append(args)
        return 0, b"", b""


async def test_docker_kills_each_harness_users_processes_as_that_user() -> None:
    provider = _Docker()
    handle = SandboxHandle(sandbox_id="c1", provider="docker")

    await provider.stop_user_processes(handle, [None, "65400:65400", None])

    assert provider.calls == [
        ("exec", "--user", user, "c1", "sh", "-c", KILL_USER_PROCESSES, "plural", uid)
        for user, uid in (("65532:65532", "65532"), ("65400:65400", "65400"))
    ]


class _Remote:
    def __init__(self, answer: tuple[int, str, str] = (0, "", "")) -> None:
        self.answer = answer
        self.calls: list[tuple[str, ...]] = []
        self.downloads: list[str] = []
        self.sandbox_id = "sb-1"
        self.image_identity = None

    async def exec(self, command: tuple[str, ...], **_: Any) -> tuple[int, str, str]:
        self.calls.append(command)
        return self.answer

    async def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        return b"data"


class _Client:
    def __init__(self, remote: _Remote) -> None:
        self.remote = remote

    async def create(self, requirements: SandboxRequirements) -> _Remote:
        return self.remote

    async def delete(self, sandbox: Any) -> None:
        return None


async def _daytona(remote: _Remote) -> tuple[DaytonaProvider, SandboxHandle]:
    provider = DaytonaProvider(adapter=_Client(remote))  # type: ignore[arg-type]
    return provider, await provider.create(SandboxRequirements(image="python:3.12"))


async def test_daytona_kills_the_harness_users_processes_as_root() -> None:
    remote = _Remote()
    provider, handle = await _daytona(remote)

    await provider.stop_user_processes(handle, [None])
    assert remote.calls == []
    await provider.stop_user_processes(handle, ["plural-seat-0", "plural-seat-1"])

    (command,) = remote.calls
    assert command[:4] == ("sudo", "-n", "sh", "-c")
    assert command[-2:] == ("plural-seat-0", "plural-seat-1")


# Harness-declared files on Daytona.


async def test_daytona_checks_an_artifact_as_the_harness_user_and_reads_what_it_resolved() -> None:
    remote = _Remote((0, "/workspace/harness/out/result.json", ""))
    provider, handle = await _daytona(remote)

    (file,) = await provider.download_artifacts(
        handle, ["out/result.json"], root="/workspace/harness", user="plural-agent"
    )

    assert file.path == "out/result.json"
    assert remote.calls[0][:6] == ("sudo", "-n", "-E", "-u", "plural-agent", "--")
    assert remote.downloads == ["/workspace/harness/out/result.json"]


@pytest.mark.parametrize(
    "answer",
    [(3, "", ""), (0, "/workspace/.plural-apps-x/bootstrap.json", ""), (0, "", "")],
)
async def test_daytona_refuses_an_artifact_that_is_a_link_or_leaves_its_folder(
    answer: tuple[int, str, str],
) -> None:
    remote = _Remote(answer)
    provider, handle = await _daytona(remote)

    with pytest.raises(FileNotFoundError, match="not a regular file"):
        await provider.download_artifacts(handle, ["result.json"], root="/workspace/harness")
    assert remote.downloads == []


def _realpath_e() -> bool:
    if shutil.which("realpath") is None:
        return False
    probe = subprocess.run(["realpath", "-e", "--", "/"], capture_output=True, check=False)
    return probe.returncode == 0


@pytest.mark.skipif(not _realpath_e(), reason="needs GNU realpath -e")
def test_the_artifact_check_refuses_links_and_paths_outside_the_folder(tmp_path: Path) -> None:
    root = (tmp_path / "harness").resolve()
    (root / "out").mkdir(parents=True)
    (root / "out" / "result.json").write_text("{}")
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.json").write_text("{}")
    (root / "link.json").symlink_to(outside / "secret.json")
    (root / "folder").symlink_to(outside)

    def check(path: str) -> tuple[int, str]:
        done = subprocess.run(
            ["sh", "-c", _CHECK_ARTIFACT, "plural", str(root), path],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.returncode, done.stdout

    assert check("out/result.json") == (0, str(root / "out" / "result.json"))
    for path in ("link.json", "folder/secret.json", "missing.json", "out"):
        assert check(path)[0] != 0, path


# The merged episode.


def test_merged_steps_take_action_and_arguments_from_the_host_and_never_share_a_target() -> None:
    merged = merge_host_steps(
        [
            {"kind": "model.call", "sequence": 1, "event_id": "e1"},
            {
                "kind": "environment.step",
                "sequence": 2,
                "event_id": "e2",
                "action": "win",
                "arguments": {"forged": True},
                "info": {"step": 1},
            },
            {
                "kind": "environment.step",
                "sequence": 2,
                "event_id": "e2",
                "action": "win",
                "info": {"step": 2},
            },
        ],
        [_host_step(1), _host_step(2)],
    )

    steps = [item for item in merged if item["kind"] == "environment.step"]
    assert [(item["action"], item["arguments"]) for item in steps] == [
        ("move", {"to": 1}),
        ("move", {"to": 2}),
    ]
    assert [item["event_id"] for item in merged] == ["e1", "e2", "e3"]
    assert [item["sequence"] for item in merged] == [1, 2, 3]


# Retries.


class _TimesOut(FakeProvider):
    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.stdin is None or request.command[:3] == ("python", "-m", "plural.apps.daemon"):
            return await super().exec(handle, request)
        self.harness_runs += 1
        return ExecResult(exit_code=-1, duration_seconds=0.001, timed_out=True)


@pytest.mark.parametrize(("steps", "runs"), [(1, 1), (0, 2)])
async def test_a_timeout_is_retried_only_when_the_host_ran_no_step(
    tmp_path: Path, steps: int, runs: int
) -> None:
    spec = _spec(
        _task(DeterministicVerifier(name="progress", check=_scored, reward=_progress)),
        retry=RetryPolicy(max_retries=1, initial_backoff_seconds=0, max_backoff_seconds=0),
    )
    provider = _TimesOut("docker")
    provider.host_steps = [_host_step(number) for number in range(1, steps + 1)]

    result = await JobRunner(
        spec, provider=provider, store=JobStore(tmp_path / "jobs"), environ=_environ()
    ).run()

    assert result.trials[0].error_code is ErrorCode.TIMEOUT
    assert provider.harness_runs == runs


# What the Job stores and the Verifiers read.


_PLANTED = ("final-observation.json", "observation.json", "final-state.json", "state.json")


def _planting_agent() -> AgentDefinition:
    """An Agent whose Harness declares observation and State files of its own."""
    package = native_actions_v1()
    definition = package.definition.model_copy(
        update={
            "artifacts": (
                *package.definition.artifacts,
                *(FileDeclaration(path=name, required=False) for name in _PLANTED),
            )
        }
    )
    package = package.model_copy(update={"definition": definition})
    return AgentDefinition(
        name="agent",
        model="test/model",
        harness=HarnessBinding.from_package(package),
        harness_package=package,
    )


class _Planted(FakeProvider):
    """A Harness that declares its own observation and State files, and a host that saw none."""

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        result = await super().exec(handle, request)
        if request.stdin is None or request.command[:3] == ("python", "-m", "plural.apps.daemon"):
            return result
        files = self.files[handle.sandbox_id]
        files["final-observation.json"] = b'{"text": "I won"}'
        files["final-state.json"] = b'{"game": {"won": true}}'
        event = json.loads(result.stdout)
        event["artifacts"] = [*event["artifacts"], *_PLANTED]
        return result.model_copy(update={"stdout": (json.dumps(event) + "\n").encode()})

    def _app_host(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        answer = super()._app_host(handle, request)
        if request.command[3] != "control":
            return answer
        sent = self.control_requests[-1]
        if sent["op"] != "finish":
            return answer
        payload = json.loads(answer.stdout)
        payload.pop("mac")
        payload["result"]["observation"] = {}
        token = str(self.bootstraps[handle.sandbox_id]["token"])
        signed = {**payload, "mac": daemon._mac(token, sent["nonce"], payload)}
        return answer.model_copy(update={"stdout": (json.dumps(signed) + "\n").encode()})


async def test_with_apps_the_harness_files_never_stand_in_for_the_host(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def check(episode: Episode) -> VerifierOutput:
        seen["observation"] = episode.observation
        seen["total"] = episode.outcome.total_reward
        return VerifierOutput(score=1, evidence=("ok",))

    spec = _spec(
        _task(DeterministicVerifier(name="progress", check=check, reward=_progress)),
        _planting_agent(),
    )
    provider = _Planted("docker")
    provider.result = b'{"total_reward": 500, "terminated": true}'
    store = JobStore(tmp_path / "jobs")

    result = await JobRunner(spec, provider=provider, store=store, environ=_environ()).run()

    assert result.status == "succeeded", result.trials[0].error_message
    assert seen == {"observation": {}, "total": 0.0}
    artifacts = _artifacts(store, spec)
    assert (artifacts / "steps.jsonl").read_text() == ""
    for name in _PLANTED[:3]:
        assert not (artifacts / name).exists(), name
    assert "won" not in (artifacts / "state.json").read_text()


# Secrets in what the Job stores.


class _Quoting(App):
    """An App whose failure quotes its admin token."""

    @action
    def move(self) -> str:
        """Fail, quoting the token."""
        raise RuntimeError(f"login failed for {SECRET}")


def test_the_hosts_step_log_masks_a_secret_an_app_error_or_reward_hook_quoted() -> None:
    def leaky(step: Step) -> float:
        raise RuntimeError(f"cannot score with {SECRET}")

    from plural.apps.host import RewardHook

    host = AppHost(
        Environment(apps=[_Quoting()], runtime=Runtime.local()),
        verifiers=[RewardHook(name="leaky", version="1", fn=leaky)],
    )
    host.redact_values([SECRET])
    host.reset()
    host.step("move", {})

    logged = json.dumps(host.report()["steps"])
    assert SECRET not in logged
    assert "internal_error" in logged and "cannot score" in logged


async def test_the_job_masks_secrets_in_host_steps_and_verifier_errors(tmp_path: Path) -> None:
    def check(episode: Episode) -> VerifierOutput:
        raise ValueError("judge key judge-key-value was rejected")

    verifier = DeterministicVerifier(
        name="progress",
        check=check,
        reward=_progress,
        secrets=(SecretReference(name="JUDGE_KEY"),),
    )
    spec = _spec(_task(verifier))
    provider = FakeProvider("docker")
    provider.host_steps = [_host_step(1, internal_error=f"RuntimeError: {SECRET}")]
    store = JobStore(tmp_path / "jobs")

    result = await JobRunner(
        spec, provider=provider, store=store, environ=_environ(JUDGE_KEY="judge-key-value")
    ).run()

    trial = result.trials[0]
    assert trial.error_code is ErrorCode.VERIFIER_FAILED
    assert "judge-key-value" not in (trial.error_message or "")
    artifacts = _artifacts(store, spec)
    for name in ("steps.jsonl", "episode.jsonl"):
        text = (artifacts / name).read_text()
        assert SECRET not in text and "RuntimeError: ***" in text, name


def test_the_app_hosts_private_copy_is_its_own_even_from_a_shared_workspace(
    tmp_path: Path,
) -> None:
    public = tmp_path / "environment"
    public.mkdir()
    (public / "app.py").write_text("SECRET_RULE = 1\n", encoding="utf-8")
    public.chmod(0o755)
    private = daemon._private_root(public)
    assert private.stat().st_mode & 0o777 == 0o700
    assert (private / "app.py").read_text(encoding="utf-8") == "SECRET_RULE = 1\n"
