"""Several Agents share one episode: each acts for its own seat, in turn, and sees only its own."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider
from test_isolation import _artifacts, _lines, _task

from plural import App, Runtime, State, action
from plural.agents import AgentBinding, AgentDefinition
from plural.apps.daemon import _Control, _handle
from plural.apps.definition import AppAction, AppDefinition, SecretReference
from plural.apps.host import AppHost, RewardHook
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime, Party
from plural.environments.env import Environment
from plural.execution import JobRunner, JobStore
from plural.execution.seats import SEAT_STAGE
from plural.jobs import JobSpec, TaskJobSource
from plural.sandbox import DownloadedFile, ExecRequest, ExecResult, SandboxHandle
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import (
    DeterministicVerifier,
    Episode,
    Step,
    VerifierOutput,
    WeightedVerifier,
    total_reward,
)


class Table(State):
    hands: dict[str, str] = {}
    pot: int = 0
    to_act: int = 0
    folded: str | None = None


class HeadsUp(App[Table]):
    """Two seats take turns; each holds a card the other must never see."""

    @action
    def bet(self, chips: int) -> str:
        self.state.pot += chips
        self.state.to_act += 1
        return f"{self.seat} bets {chips}"

    @action
    def fold(self) -> str:
        self.state.folded = self.seat
        return f"{self.seat} folds"

    def turn(self) -> str:
        return self.seats[self.state.to_act % len(self.seats)]

    def observe(self, seat: str) -> dict[str, Any]:
        return {"card": self.state.hands.get(seat), "pot": self.state.pot}

    def terminated(self) -> bool:
        return self.state.folded is not None


class Votes(State):
    cast: dict[str, str] = {}


class Ballot(App[Votes]):
    """Every seat moves at once, and each only once."""

    @action
    def vote(self, choice: str) -> str:
        assert self.seat is not None
        self.state.cast[self.seat] = choice
        return "counted"

    def turn(self) -> list[str]:
        return [seat for seat in self.seats if seat not in self.state.cast]


SEATS = ("seat_1", "seat_2")
HANDS = {"heads_up": {"hands": {"seat_1": "As", "seat_2": "7d"}}}


def _table(**kwargs: Any) -> AppHost:
    host = AppHost(Environment(apps=[HeadsUp()], runtime=Runtime.local()), seats=SEATS, **kwargs)
    host.start(initial_state=HANDS)
    return host


def test_a_seat_acts_only_on_its_turn_and_a_refusal_is_not_a_step() -> None:
    host = _table()
    early = host.step("bet", {"chips": 5}, seat="seat_2")
    assert "not your turn" in early["info"]["error"]
    assert "seat_1" in early["info"]["error"]
    assert host.steps == 0
    assert host.apps["heads_up"].state.pot == 0

    host.step("bet", {"chips": 5}, seat="seat_1")
    assert host.turn() == ("seat_2",)
    host.step("fold", {}, seat="seat_2")
    assert host.apps["heads_up"].state.folded == "seat_2"
    assert [item["seat"] for item in host.report()["steps"]] == ["seat_1", "seat_2"]
    ended = host.step("bet", {"chips": 1}, seat="seat_1")
    assert "ended" in ended["info"]["error"]


def test_an_action_without_a_seat_is_refused() -> None:
    host = _table()
    refused = host.step("bet", {"chips": 5})
    assert "names no seat" in refused["info"]["error"]
    assert host.steps == 0


def test_each_seat_sees_its_own_card_and_never_the_others() -> None:
    host = _table()
    seat_1 = host.seat_view("seat_1")
    blind = host.seat_view("seat_2")
    assert seat_1["observation"] == {"card": "As", "pot": 0}
    assert blind["observation"] == {"card": "7d", "pot": 0}
    assert seat_1["your_turn"] and not blind["your_turn"]
    assert blind["waiting_for"] == ["seat_1"]


def test_a_reward_credits_the_acting_seat_or_each_seat_named() -> None:
    def pot_share(step: Step) -> dict[str, float] | None:
        if step.action != "fold":
            return None
        winner = next(seat for seat in step.seats if seat != step.seat)
        return {winner: 1.0, step.seat or "": -1.0}

    def acted(step: Step) -> float:
        return 0.1

    host = _table(
        verifiers=[
            RewardHook(name="chips", version="1", fn=pot_share),
            RewardHook(name="tempo", version="1", fn=acted),
        ]
    )
    opened = host.step("bet", {"chips": 5}, seat="seat_1")
    assert opened["rewards"] == [
        {"name": "tempo", "version": "1", "app": "heads_up", "seat": "seat_1", "value": 0.1}
    ]
    folded = host.step("fold", {}, seat="seat_2")
    credited = {(item["name"], item["seat"]): item["value"] for item in folded["rewards"]}
    assert credited == {
        ("chips", "seat_1"): 1.0,
        ("chips", "seat_2"): -1.0,
        ("tempo", "seat_2"): 0.1,
    }
    # The step's own reward is the acting seat's.
    assert folded["reward"] == -0.9


def test_a_reward_naming_no_seat_is_an_error() -> None:
    host = _table(verifiers=[RewardHook(name="bad", version="1", fn=lambda step: {"dealer": 1.0})])
    envelope = host.step("bet", {"chips": 5}, seat="seat_1")
    assert envelope["rewards"][0]["value"] == 0.0
    assert "dealer" in envelope["rewards"][0]["error"]


def test_simultaneous_moves_let_every_seat_act_once() -> None:
    host = AppHost(Environment(apps=[Ballot()], runtime=Runtime.local()), seats=("a", "b", "c"))
    host.start()
    assert host.turn() == ("a", "b", "c")
    host.step("vote", {"choice": "x"}, seat="b")
    assert host.turn() == ("a", "c")
    again = host.step("vote", {"choice": "y"}, seat="b")
    assert "not your turn" in again["info"]["error"]
    host.step("vote", {"choice": "z"}, seat="a")
    host.step("vote", {"choice": "z"}, seat="c")
    assert host.apps["ballot"].state.cast == {"a": "z", "b": "x", "c": "z"}
    assert host.seat_view("a")["waiting_for"] == []


def test_the_seat_is_the_one_its_token_names(tmp_path: Path) -> None:
    host = _table()
    control = _Control(None, {"seat_1": "tok-seat_1", "seat_2": "tok-two"})

    def step(token: str | None, **arguments: Any) -> dict[str, Any]:
        request: dict[str, Any] = {"op": "step", "action": "bet", "arguments": arguments}
        if token is not None:
            request["seat_token"] = token
        response, _ = _handle(host, tmp_path, request, control)
        return dict(response["result"])

    assert "not your turn" in step("tok-two", chips=1)["info"]["error"]
    assert "names no seat" in step("forged", chips=1)["info"]["error"]
    assert "names no seat" in step(None, chips=1)["info"]["error"]
    seen = step("tok-seat_1", chips=2)
    assert seen["info"].get("error") is None
    assert "reward" not in seen and "rewards" not in seen

    turn, _ = _handle(host, tmp_path, {"op": "turn", "seat_token": "tok-two"}, control)
    assert turn["result"]["your_turn"] is True
    assert turn["result"]["observation"]["card"] == "7d"
    stranger, _ = _handle(host, tmp_path, {"op": "turn", "seat_token": "nope"}, control)
    assert stranger["ok"] is False and stranger["kind"] == "PermissionError"


# A Job whose Task several Agents share.


class SeatedProvider(FakeProvider):
    """A fake Runtime that keeps each seat's Harness output in its own folder."""

    def __init__(self) -> None:
        super().__init__("docker")
        self.seat_users = {"seat_1": "65400:65400", "seat_2": "65401:65401"}
        self.seat_requests: dict[str, dict[str, Any]] = {}
        self.seat_env: dict[str, dict[str, str]] = {}
        self.seat_user: dict[str, str | None] = {}

    async def isolate_seats(self, handle: SandboxHandle, seats: Sequence[str]) -> dict[str, str]:
        return {seat: self.seat_users[seat] for seat in seats if seat in self.seat_users}

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.stdin is None or request.command[:2] in {
            ("python", "-m"),
            ("python", "-c"),
        }:
            return await super().exec(handle, request)
        payload = json.loads(request.stdin)
        seat = payload["task"]["seat"]
        self.seat_requests[seat] = payload
        self.seat_env[seat] = dict(request.env)
        self.seat_user[seat] = request.user
        number = 1 if seat == "seat_1" else 2
        episode = [
            {"kind": "model.call", "sequence": 1, "event_id": "e1", "turn": 1, "messages": []},
            {
                "kind": "environment.step",
                "sequence": 2,
                "event_id": "e2",
                "action": "bet",
                "info": {"step": number},
                "reward": 99,
            },
        ]
        root = request.cwd
        files = self.files[handle.sandbox_id]
        files[f"{root}/episode.jsonl"] = "".join(
            json.dumps(item) + "\n" for item in episode
        ).encode()
        files[f"{root}/result.json"] = json.dumps({"seat": seat}).encode()
        event = {
            "protocol": "plural-harness-v1",
            "type": "result",
            "status": "succeeded",
            "outputs": ["result.json"],
            "artifacts": ["episode.jsonl"],
            "trace_id": f"trace-{seat}",
        }
        return ExecResult(
            exit_code=0, stdout=(json.dumps(event) + "\n").encode(), duration_seconds=0
        )

    async def download_files(
        self, handle: SandboxHandle, paths: Sequence[str], *, root: str = "/workspace"
    ) -> tuple[DownloadedFile, ...]:
        files = self.files[handle.sandbox_id]
        if root.startswith("/workspace/seats/"):
            return tuple(DownloadedFile(path=path, data=files[f"{root}/{path}"]) for path in paths)
        return await super().download_files(handle, paths, root=root)


def _seat_step(number: int, seat: str, rewards: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "protocol": "plural-step-v1",
        "kind": "step",
        "app": "game",
        "action": "bet",
        "arguments": {"chips": number},
        "observation": {"text": f"{seat} bet"},
        "rendered": f"{seat} bet",
        "reward": sum(item["value"] for item in rewards if item.get("seat") == seat),
        "rewards": rewards,
        "terminated": number == 2,
        "truncated": False,
        "info": {"step": number},
        "step": number,
        "seat": seat,
    }


SEATED_APP = AppDefinition(
    name="game",
    kind="python",
    python="game.py:Game",
    actions=(AppAction(name="bet", description="Bet chips."),),
)


def chips(step: Step) -> float:
    return 0.0


def _seated_task(check: Any, party: Party | int | None = None) -> TaskDefinition:
    return TaskDefinition(
        task_id="heads-up",
        instructions="Play one hand of poker.",
        environment=EnvironmentDefinition(
            name="table",
            apps=(SEATED_APP,),
            runtime=EnvironmentRuntime(provider="docker"),
            party=Party(min=2, max=8) if party is None else Party.model_validate(party),
        ),
        verifiers=(
            WeightedVerifier(
                verifier=DeterministicVerifier(name="chips", check=check, reward=chips)
            ),
        ),
        seat_instructions={"seat_1": "You are on the button; your card is private."},
    )


def _agents(*names: str) -> tuple[AgentBinding, ...]:
    return tuple(
        AgentBinding(agent=AgentDefinition(name=name, model="test/model")) for name in names
    )


def _lineups(spec: JobSpec) -> list[tuple[tuple[str, str], ...]]:
    return [
        tuple((seat.seat, seat.agent_name) for seat in trial.seats) for trial in spec.plan().trials
    ]


def test_the_job_names_the_party_and_every_attempt_seats_it_the_same_way() -> None:
    spec = JobSpec(
        source=TaskJobSource(task=_seated_task(total_reward)),
        agents=_agents("a", "b", "c", "d"),
        party=("c", "a", "d"),
        attempts=2,
    )
    party = (("seat_1", "c"), ("seat_2", "a"), ("seat_3", "d"))
    assert _lineups(spec) == [party, party]
    assert [trial.agent_name for trial in spec.plan().trials] == ["c", "c"]
    assert len({trial.trial_id for trial in spec.plan().trials}) == 2


def test_without_a_named_party_every_agent_plays_once() -> None:
    spec = JobSpec(source=TaskJobSource(task=_seated_task(total_reward)), agents=_agents("a", "b"))
    assert _lineups(spec) == [(("seat_1", "a"), ("seat_2", "b"))]


def test_an_agent_named_twice_plays_against_itself() -> None:
    spec = JobSpec(
        source=TaskJobSource(task=_seated_task(total_reward)),
        agents=_agents("solo"),
        party=("solo", "solo", "solo"),
    )
    assert _lineups(spec) == [(("seat_1", "solo"), ("seat_2", "solo"), ("seat_3", "solo"))]


def test_a_party_the_environment_cannot_seat_is_refused() -> None:
    task = _seated_task(total_reward)
    with pytest.raises(ValueError, match="party of 1"):
        JobSpec(source=TaskJobSource(task=task), agents=_agents("solo"))
    with pytest.raises(ValueError, match="party of 9"):
        JobSpec(source=TaskJobSource(task=task), agents=_agents(*"abcdefghi"))
    with pytest.raises(ValueError, match="zed"):
        JobSpec(source=TaskJobSource(task=task), agents=_agents("a", "b"), party=("a", "zed"))
    exact = _seated_task(total_reward, party=2)
    with pytest.raises(ValueError, match="party of 3"):
        JobSpec(source=TaskJobSource(task=exact), agents=_agents("a", "b", "c"))


def test_a_solo_task_ignores_the_party_and_keeps_its_identity() -> None:
    task = _task(DeterministicVerifier(name="progress", check=_scored_one, reward=chips))
    assert "seat_instructions" not in task.model_dump()
    assert "party" not in task.environment.model_dump()
    assert '"party"' not in task.model_dump_json()
    spec = JobSpec(source=TaskJobSource(task=task), agents=_agents("a", "b"))
    assert "party" not in spec.model_dump()
    assert [trial.seats for trial in spec.plan().trials] == [(), ()]
    assert [trial.agent_name for trial in spec.plan().trials] == ["a", "b"]


def test_the_party_is_checked() -> None:
    assert Party.model_validate(4) == Party(min=4, max=4)
    assert Party(min=2, max=8).check(8) is None
    assert "takes 2 to 8" in (Party(min=2, max=8).check(9) or "")
    with pytest.raises(ValueError):
        Party(min=5, max=3)
    with pytest.raises(ValueError):
        Party(min=1, max=3)
    with pytest.raises(ValueError, match="App"):
        EnvironmentDefinition(name="empty", party=Party())


def test_seat_instructions_name_numbered_seats_the_party_can_fill() -> None:
    task = _seated_task(total_reward)
    payload = task.seat_payload("seat_1", ("seat_1", "seat_2"))
    assert "your card is private" in payload["instructions"]
    assert payload["seat"] == "seat_1" and payload["seats"] == ["seat_1", "seat_2"]
    assert "private" not in task.seat_payload("seat_2", ("seat_1", "seat_2"))["instructions"]
    with pytest.raises(ValueError, match="seat_9"):
        task.model_validate({**task.model_dump(), "seat_instructions": {"seat_9": "x"}})
    with pytest.raises(ValueError, match="dealer"):
        task.model_validate({**task.model_dump(), "seat_instructions": {"dealer": "x"}})
    solo = _task(DeterministicVerifier(name="progress", check=_scored_one, reward=chips))
    with pytest.raises(ValueError, match="party"):
        solo.model_validate({**solo.model_dump(), "seat_instructions": {"seat_1": "x"}})


async def test_each_seat_runs_its_own_harness_apart_and_is_scored_alone(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def check(episode: Episode) -> VerifierOutput:
        seen["seats"] = episode.seats
        seen["seat_rewards"] = episode.seat_rewards
        seen["took"] = [item.get("seat") for item in episode.trajectory]
        return total_reward(episode)

    task = _seated_task(check)
    spec = JobSpec(source=TaskJobSource(task=task), agents=_agents("alice", "bob"))
    provider = SeatedProvider()
    provider.host_steps = [
        _seat_step(
            1,
            "seat_1",
            [{"name": "chips", "version": "1", "app": "game", "seat": "seat_1", "value": 0.5}],
        ),
        _seat_step(
            2,
            "seat_2",
            [
                {"name": "chips", "version": "1", "app": "game", "seat": "seat_1", "value": 1.0},
                {
                    "name": "chips",
                    "version": "1",
                    "app": "game",
                    "seat": "seat_2",
                    "value": -1.0,
                },
            ],
        ),
    ]
    store = JobStore(tmp_path / "jobs")

    result = await JobRunner(spec, provider=provider, store=store).run()

    (trial,) = result.trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.seat_isolation == "os_user"
    assert seen["seats"] == ("seat_1", "seat_2")
    assert seen["seat_rewards"] == {"seat_1": (0.5, 1.0), "seat_2": (-1.0,)}
    assert seen["took"] == ["seat_1", "seat_2"]
    by_seat = {item.seat: item for item in trial.seats}
    assert by_seat["seat_1"].agent_name == "alice" and by_seat["seat_1"].score == 1.5
    assert by_seat["seat_2"].agent_name == "bob" and by_seat["seat_2"].score == -1.0
    assert by_seat["seat_1"].step_reward_total == 1.5
    assert by_seat["seat_1"].trace_id == "trace-seat_1"

    # Each seat has its own token, user, folder, and directions; none sees another's.
    tokens = {seat: env["PLURAL_SEAT_TOKEN"] for seat, env in provider.seat_env.items()}
    assert len(set(tokens.values())) == 2
    assert provider.bootstraps["docker-0"]["seats"] == tokens
    assert provider.seat_user == provider.seat_users
    assert provider.seat_env["seat_1"]["HOME"] == "/workspace/seats/seat_1"
    seat_1 = provider.seat_requests["seat_1"]
    assert seat_1["workspace"] == "/workspace/seats/seat_1"
    assert "your card is private" in seat_1["task"]["instructions"]
    assert "your card is private" not in provider.seat_requests["seat_2"]["task"]["instructions"]
    assert "turn_command" in seat_1["environment"]
    for payload in provider.seat_requests.values():
        assert tokens["seat_1"] not in json.dumps(payload)

    # The shared episode is the host's; each seat's transcript is its own.
    artifacts = _artifacts(store, spec)
    shared = _lines(artifacts / "episode.jsonl")
    assert [(item["seat"], item["reward"]) for item in shared] == [
        ("seat_1", 0.5),
        ("seat_2", -1.0),
    ]
    mine = _lines(artifacts / "seats/seat_1/episode.jsonl")
    steps = [item for item in mine if item["kind"] == "environment.step"]
    assert [(item["seat"], item["reward"]) for item in steps] == [("seat_1", 0.5)]
    theirs = _lines(artifacts / "seats/seat_2/episode.jsonl")
    assert [item.get("seat") for item in theirs if item["kind"] == "environment.step"] == ["seat_2"]
    ledger = _lines(artifacts / "rewards.jsonl")
    assert sorted((item["seat"], item["value"]) for item in ledger) == [
        ("seat_1", 0.5),
        ("seat_1", 1.0),
        ("seat_2", -1.0),
    ]

    rows = {row.agent_name: row.mean_score for row in result.aggregates}
    assert rows == {"alice": 1.5, "bob": -1.0}


async def test_a_verifier_scoring_a_seat_the_task_lacks_fails(tmp_path: Path) -> None:
    def check(episode: Episode) -> VerifierOutput:
        return VerifierOutput(score=0, seats={"dealer": 1.0}, evidence=("x",))

    spec = JobSpec(source=TaskJobSource(task=_seated_task(check)), agents=_agents("alice", "bob"))
    result = await JobRunner(spec, provider=SeatedProvider(), store=JobStore(tmp_path / "j")).run()
    assert result.trials[0].status == "failed"
    assert "dealer" in (result.trials[0].error_message or "")


async def test_harness_setup_runs_before_any_secret_or_seat_is_in_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    class Recording(SeatedProvider):
        async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
            if request.command[:3] == ("python", "-m", "plural.apps.daemon"):
                order.append(f"host {request.command[3]}")
            elif any(SEAT_STAGE in part for part in request.command):
                order.append("seats")
            return await super().exec(handle, request)

    async def setup(self: Any, handle: Any, definition: Any, request: Any, **_: Any) -> None:
        order.append(f"setup {request.workspace}")

    monkeypatch.setattr("plural.execution.engine.HarnessRunner.setup", setup)
    spec = JobSpec(
        source=TaskJobSource(task=_seated_task(total_reward)), agents=_agents("alice", "bob")
    )
    result = await JobRunner(spec, provider=Recording(), store=JobStore(tmp_path / "j")).run()
    assert result.trials[0].status == "succeeded", result.trials[0].error_message
    assert order[:2] == [f"setup {SEAT_STAGE}/seat_1", f"setup {SEAT_STAGE}/seat_2"]
    assert "host start" in order[2:] and "seats" in order[2:]


async def test_a_party_never_plays_when_its_seats_cannot_be_kept_apart(tmp_path: Path) -> None:
    provider = SeatedProvider()
    provider.seat_users = {}
    spec = JobSpec(
        source=TaskJobSource(task=_seated_task(total_reward)), agents=_agents("alice", "bob")
    )
    result = await JobRunner(spec, provider=provider, store=JobStore(tmp_path / "j")).run()
    (trial,) = result.trials
    assert trial.status == "failed"
    assert "OS user of its own" in (trial.error_message or "")
    assert provider.seat_requests == {}


def test_a_party_refuses_the_local_runtime() -> None:
    with pytest.raises(ValueError, match="OS user of its own"):
        EnvironmentDefinition(
            name="table",
            apps=(SEATED_APP,),
            runtime=EnvironmentRuntime.local(),
            party=Party(),
        )
    EnvironmentDefinition(name="solo", apps=(SEATED_APP,), runtime=EnvironmentRuntime.local())
    shared = EnvironmentDefinition(
        name="team",
        apps=(SEATED_APP,),
        runtime=EnvironmentRuntime.local(),
        party=Party(min=2, max=3, isolation="shared"),
    )
    assert shared.party is not None and shared.party.isolation == "shared"
    assert Party.model_validate(2).isolation == "isolated"


@pytest.mark.parametrize("isolation", ["isolated", "shared"])
def test_a_benchmark_refuses_a_party_until_benchmarks_for_several_agents_ship(
    isolation: str,
) -> None:
    task = _seated_task(_scored_one, Party(min=2, max=2, isolation=isolation))
    with pytest.raises(ValueError, match="coming soon"):
        BenchmarkDefinition(name="poker", tasks=(task,))


async def test_a_shared_party_plays_as_one_user_and_says_so(tmp_path: Path) -> None:
    class Recording(SeatedProvider):
        asked_for_users = False

        async def isolate_seats(
            self, handle: SandboxHandle, seats: Sequence[str]
        ) -> dict[str, str]:
            self.asked_for_users = True
            return await super().isolate_seats(handle, seats)

    task = _seated_task(total_reward)
    task = task.model_copy(
        update={
            "environment": task.environment.model_copy(
                update={"party": Party(min=2, max=8, isolation="shared")}
            )
        }
    )
    provider = Recording()
    spec = JobSpec(source=TaskJobSource(task=task), agents=_agents("alice", "bob"))
    result = await JobRunner(spec, provider=provider, store=JobStore(tmp_path / "j")).run()
    (trial,) = result.trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.seat_isolation == "none"
    assert not provider.asked_for_users
    assert set(provider.seat_user.values()) == {None}


def test_a_party_refuses_apps_that_need_agent_credentials() -> None:
    app = SEATED_APP.model_copy(update={"credentials": (SecretReference(name="TOKEN"),)})
    with pytest.raises(ValueError, match="credentials"):
        EnvironmentDefinition(name="e", apps=(app,), party=Party())


def _scored_one(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1, evidence=("ok",))


def test_the_native_harness_waits_for_its_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.harness import native_runner

    counter = tmp_path / "polls"
    script = tmp_path / "turn.py"
    script.write_text(
        "import json, os, pathlib, sys\n"
        f"path = pathlib.Path({str(counter)!r})\n"
        "count = int(path.read_text()) + 1 if path.exists() else 1\n"
        "path.write_text(str(count))\n"
        "assert os.environ['PLURAL_SEAT_TOKEN'] == 'tok'\n"
        "print(json.dumps({'your_turn': count >= 3, 'observation': {'card': 'As'}}))\n"
    )
    monkeypatch.setenv("PLURAL_SEAT_TOKEN", "tok")
    monkeypatch.setattr(native_runner, "_TURN_POLL_SECONDS", (0.0,))
    environment = {"turn_command": [sys.executable, str(script)], "workspace": str(tmp_path)}
    answer = native_runner._await_turn(environment, time.monotonic() + 30)
    assert answer is not None and answer["observation"] == {"card": "As"}
    assert counter.read_text() == "3"


def test_a_custom_harness_waits_for_its_turn_and_sees_only_its_view(tmp_path: Path) -> None:
    from plural.harness.interface import HarnessEnvironment

    counter = tmp_path / "asked"
    script = (
        "import json, pathlib, sys\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) + 1 if p.exists() else 1\n"
        "p.write_text(str(n))\n"
        "print(json.dumps({'seat': 'seat_2', 'your_turn': n >= 3, 'waiting_for': "
        "[] if n >= 3 else ['seat_1'], 'observation': {'note': 'mine'}, "
        "'terminated': False, 'truncated': False}))\n"
    )
    environment = HarnessEnvironment(
        {"workspace": str(tmp_path), "turn_command": [sys.executable, "-c", script]}
    )
    assert environment.seated
    view = environment.wait_for_turn(poll_seconds=0)
    assert view.your_turn and view.seat == "seat_2"
    assert environment.observation == {"note": "mine"}
    assert counter.read_text() == "3"
    alone = HarnessEnvironment({"workspace": str(tmp_path)})
    assert not alone.seated
    with pytest.raises(RuntimeError, match="no party"):
        alone.turn()
