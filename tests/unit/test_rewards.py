from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider
from pydantic import ValidationError

from plural import (
    Credit,
    DeterministicVerifier,
    Episode,
    HindsightTrial,
    RewardTarget,
    Step,
    total_reward,
)
from plural.agents import AgentBinding, AgentDefinition
from plural.execution import JobRunner, JobStore
from plural.execution.replay import replay_verifier
from plural.jobs import JobSpec, TaskJobSource, TITORecord
from plural.rewards import (
    LEDGER_FILE,
    HindsightVerifier,
    RewardRecord,
    align_tito,
    append_ledger,
    online_records,
    read_ledger,
    reward_failures,
    training_export,
)
from plural.sandbox import ExecRequest, ExecResult, SandboxHandle
from plural.verifiers import WeightedVerifier

EPISODE: list[dict[str, Any]] = [
    {"sequence": 1, "event_id": "e1", "kind": "environment.reset", "turn": None},
    {
        "sequence": 2,
        "event_id": "e2",
        "kind": "model.call",
        "turn": 1,
        "text": "I will guess crane because it covers common letters.",
        "reasoning": "Start with vowels.",
    },
    {
        "sequence": 3,
        "event_id": "e3",
        "kind": "environment.step",
        "turn": 1,
        "action": "game__guess",
        "reward": 0.5,
        "rewards": [
            {"name": "progress", "version": "1.0.0", "app": "game", "value": 0.25},
            {"name": "careful", "version": "2", "app": "game", "value": 0.25},
            {"name": "broken", "version": "1", "app": "game", "value": 0, "error": "boom"},
        ],
        "info": {},
    },
    {"sequence": 4, "event_id": "e4", "kind": "model.call", "turn": 2, "text": "Done."},
    {
        "sequence": 5,
        "event_id": "e5",
        "kind": "environment.step",
        "turn": 2,
        "action": "crm__delete_record",
        "reward": 0.0,
        "rewards": [],
        "info": {"off_recording": True},
    },
]


def test_a_reward_that_raised_is_reported_not_recorded() -> None:
    assert [item.verifier for item in online_records(EPISODE)] == ["progress", "careful"]
    [failure] = reward_failures([*EPISODE, EPISODE[2]])
    assert (failure.verifier, failure.steps, failure.error) == ("broken", 2, "boom")


def test_targets_name_one_thing_and_spans_need_exactly_one_range() -> None:
    assert RewardTarget.step("e3").kind == "step"
    assert RewardTarget.span("e2", 0, 5).field == "text"
    assert RewardTarget.tokens("e2", 1, 4).token_end == 4
    with pytest.raises(ValidationError, match="takes no range"):
        RewardTarget(kind="step", event_id="e3", start=0, end=1)
    with pytest.raises(ValidationError, match="exactly one range"):
        RewardTarget(kind="span", event_id="e2")
    with pytest.raises(ValidationError, match="end after it starts"):
        RewardTarget.span("e2", 5, 5)
    with pytest.raises(ValidationError, match="finite"):
        RewardRecord(
            target=RewardTarget.step("e3"), value=float("nan"), source="step", verifier="x"
        )


def test_online_records_come_from_each_step_signal() -> None:
    records = online_records(EPISODE)
    assert [(item.source, item.verifier, item.app, item.value) for item in records] == [
        ("step", "progress", "game", 0.25),
        ("step", "careful", "game", 0.25),
    ]
    assert [item.version for item in records] == ["1.0.0", "2"]
    assert {item.target.event_id for item in records} == {"e3"}


def test_a_rejected_action_still_gets_its_step_rewards() -> None:
    rejected = {
        "sequence": 1,
        "event_id": "e1",
        "kind": "environment.step",
        "error": "a guess must have five letters",
        "reward": -0.1,
        "rewards": [{"name": "solved", "version": "1", "app": "game", "value": -0.1}],
    }
    bare = {"sequence": 2, "event_id": "e2", "kind": "environment.step", "reward": 0.5}
    records = online_records([rejected, bare])
    assert [(item.source, item.verifier, item.value) for item in records] == [
        ("step", "solved", -0.1),
    ]


def test_hindsight_credits_any_event_and_rejects_unknown_ones() -> None:
    def deletes(trial: HindsightTrial):
        for step in trial.steps("crm__delete_record"):
            yield trial.credit(step["event_id"], -1.0, reason="deleted a record")
        yield trial.credit(RewardTarget.span("e2", 0, 13), 0.5)

    no_deletes = HindsightVerifier(deletes, name="no_deletes", version="2")

    trial = HindsightTrial(EPISODE, score=1.0)
    records = no_deletes.apply(trial)
    assert [(item.target.kind, item.value, item.version) for item in records] == [
        ("step", -1.0, "2"),
        ("span", 0.5, "2"),
    ]
    assert all(item.source == "hindsight" for item in records)
    assert records[0].metadata == {"reason": "deleted a record"}

    def missing(trial: HindsightTrial) -> Credit:
        return trial.credit("e99", 1.0)

    stray = HindsightVerifier(missing, name="stray", version="1")

    with pytest.raises(ValueError, match="does not have"):
        stray.apply(trial)


def test_the_ledger_is_append_only(tmp_path: Path) -> None:
    path = tmp_path / LEDGER_FILE
    first = online_records(EPISODE)
    append_ledger(path, first)
    append_ledger(path, [first[0].model_copy(update={"value": 9.0, "record_id": "later"})])
    assert [item.value for item in read_ledger(path)] == [0.25, 0.25, 9.0]


def test_applying_hindsight_again_adds_nothing(tmp_path: Path) -> None:
    solved = HindsightVerifier(lambda trial: trial.credit("e3", 1.0), name="solved", version="1")
    solved_v2 = HindsightVerifier(lambda trial: trial.credit("e3", 0.5), name="solved", version="2")

    path = tmp_path / LEDGER_FILE
    trial = HindsightTrial(EPISODE, score=1.0, trial_id="trl_a")
    assert append_ledger(path, solved.apply(trial)) == 1
    assert append_ledger(path, solved.apply(trial)) == 0
    assert append_ledger(path, solved_v2.apply(trial)) == 1
    other = HindsightTrial(EPISODE, score=1.0, trial_id="trl_b")
    assert solved.apply(other)[0].record_id != solved.apply(trial)[0].record_id
    assert [(item.version, item.value) for item in read_ledger(path)] == [("1", 1.0), ("2", 0.5)]


def _tito(step: int, text: str, offsets: list[tuple[int, int]]) -> dict[str, Any]:
    size = len(offsets)
    return TITORecord(
        step=step,
        tokenizer="t",
        model="m",
        input_token_ids=(1,),
        output_token_ids=tuple(range(size)),
        observation_token_ids=(),
        output_logprobs=(0.0,) * size,
        output_top_logprobs=({},) * size,
        output_text=text,
        assistant_message={"role": "assistant", "content": text},
        input_len=1,
        output_len=size,
        observation_len=0,
        output_token_offsets=tuple(offsets),
    ).model_dump(mode="json")


def test_training_export_lines_up_steps_spans_and_tokens() -> None:
    text = "I will guess crane because it covers common letters."
    words = [(0, 1), (1, 6), (6, 12), (12, 18), (18, 26), (26, 52)]
    tito = [_tito(0, text, words), _tito(1, "Done.", [(0, 5)])]
    assert [item["event_id"] for item in align_tito(tito, EPISODE)] == ["e2", "e4"]

    ledger = [
        *online_records(EPISODE),
        RewardRecord(
            target=RewardTarget.span("e2", 7, 18),
            value=1.0,
            source="hindsight",
            verifier="good_guess",
            version="1",
        ),
        RewardRecord(
            target=RewardTarget.span("e2", 7, 18),
            value=3.0,
            source="hindsight",
            verifier="good_guess",
            version="2",
        ),
        RewardRecord(
            target=RewardTarget.step("e5"),
            value=-1.0,
            source="hindsight",
            verifier="no_deletes",
            off_recording=True,
        ),
    ]
    exported = training_export(EPISODE, ledger, tito=tito)
    first, second = exported["turns"]
    assert first["event_id"] == "e2"
    assert first["reward"] == 0.5
    assert first["tito"]["event_id"] == "e2"
    assert first["span_rewards"] == [
        {
            "start": 7,
            "end": 18,
            "field": "text",
            "token_start": 2,
            "token_end": 4,
            "value": 3.0,
            "verifier": "good_guess",
        }
    ]
    assert second["reward"] == 0.0

    older = training_export(EPISODE, ledger, tito=tito, verifiers={"good_guess": "1"})
    assert older["turns"][0]["reward"] == 0.0
    assert older["turns"][0]["span_rewards"][0]["value"] == 1.0

    kept = training_export(EPISODE, ledger, verifiers=["no_deletes"], include_off_recording=True)
    assert kept["turns"][1]["reward"] == -1.0


class _StepProvider(FakeProvider):
    """A fake Runtime whose Harness records one rewarded step."""

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        result = await super().exec(handle, request)
        files = self.files[handle.sandbox_id]
        if "episode.jsonl" in files:
            files["episode.jsonl"] = "".join(json.dumps(item) + "\n" for item in EPISODE).encode()
        return result


async def test_a_job_writes_step_and_hindsight_rewards_to_the_trial_ledger(
    tmp_path: Path,
) -> None:
    from test_package_execution import make_task

    def finished(trial: HindsightTrial):
        assert trial.score == 1.0
        yield trial.credit(RewardTarget.event("e4"), 1.0)

    def broken(trial: HindsightTrial):
        raise RuntimeError("bad label")

    task = make_task("one", "docker")
    task = task.model_copy(
        update={
            "verifiers": (
                *task.verifiers,
                WeightedVerifier(verifier=DeterministicVerifier(name="broken", hindsight=broken)),
                WeightedVerifier(
                    verifier=DeterministicVerifier(
                        name="finished", version="0.2.0", hindsight=finished
                    )
                ),
            )
        }
    )
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(spec, provider=_StepProvider("docker"), store=store).run()

    assert result.status == "succeeded"
    trial = spec.plan().trials[0]
    ledger = read_ledger(store.trial_path(trial) / "executions/0/artifacts" / LEDGER_FILE)
    assert [(item.source, item.verifier, item.version) for item in ledger] == [
        ("step", "progress", "1.0.0"),
        ("step", "careful", "2"),
        ("hindsight", "finished", "0.2.0"),
    ]
    events = (store.job_path(spec.job_id) / "events.jsonl").read_text()
    assert "bad label" in events
    assert result.trials[0].score == 1.0


def test_a_verifier_may_give_only_hindsight_credit() -> None:
    verifier = DeterministicVerifier(name="efficiency", hindsight="verify.py:efficiency")
    assert not verifier.scores
    assert verifier.model_dump(mode="json")["hindsight"] == {"python": "verify.py:efficiency"}
    with pytest.raises(ValueError, match="accepts one HindsightTrial"):
        DeterministicVerifier(name="bad", hindsight=42)
    assert "hindsight" not in DeterministicVerifier(name="plain", check=["true"])._hash_payload()


def _progress(step: Step) -> float:
    return 0.25


async def test_total_reward_scores_a_trial_by_its_own_verifiers_rewards(tmp_path: Path) -> None:
    from test_package_execution import make_task

    verifier = DeterministicVerifier(name="progress", check=total_reward, reward=_progress)
    task = make_task("one", "docker").model_copy(
        update={"verifiers": (WeightedVerifier(verifier=verifier),)}
    )
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
    )
    result = await JobRunner(
        spec, provider=_StepProvider("docker"), store=JobStore(tmp_path / "jobs")
    ).run()

    assert result.status == "succeeded"
    # The episode also holds 0.25 from another Verifier, "careful", which is not counted.
    assert result.trials[0].score == 0.25


def test_total_reward_is_a_builtin_check_that_needs_a_reward() -> None:
    verifier = DeterministicVerifier(name="return", check="total_reward", reward=_progress)
    assert verifier.check is total_reward
    assert verifier.model_dump(mode="json")["check"] == {"builtin": "total_reward"}
    restored = DeterministicVerifier.model_validate(
        {**verifier.model_dump(mode="json"), "reward": _progress}
    )
    assert restored.check is total_reward
    assert total_reward(Episode(rewards=(0.25, -0.1, 1.0))).score == pytest.approx(1.15)
    with pytest.raises(ValueError, match="needs a reward function too"):
        DeterministicVerifier(name="return", check=total_reward)


def test_a_verifier_needs_a_check_a_reward_or_both() -> None:
    rewards_only = DeterministicVerifier(name="progress", reward=_progress)
    assert not rewards_only.scores
    with pytest.raises(ValueError, match="Give it check"):
        DeterministicVerifier(name="empty")


def test_an_earlier_ledger_reads_its_rewarder_as_the_verifier() -> None:
    record = RewardRecord.model_validate(
        {
            "target": {"kind": "step", "event_id": "evt-1"},
            "value": 0.5,
            "source": "app",
            "rewarder": "solved",
            "version": "1",
        }
    )
    assert (record.verifier, record.source) == ("solved", "step")
    assert "rewarder" not in record.model_dump()


def test_replaying_a_verifier_reports_what_a_stored_trial_cannot_support(tmp_path: Path) -> None:
    (tmp_path / "episode.jsonl").write_text(
        json.dumps({"kind": "environment.step", "event_id": "e1", "action": "guess"}) + "\n"
    )
    replay = replay_verifier(
        DeterministicVerifier(name="solved", check=["true"], reward=lambda step: 1.0),
        tmp_path,
    )

    assert replay.rewards == []
    assert replay.output is None
    assert any("no recorded State per step" in item for item in replay.problems)
    assert any("check runs as a command" in item for item in replay.problems)
