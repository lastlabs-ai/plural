"""Run a Verifier again on a stored Trial, without running the Agent.

``reward`` is replayed step by step from the Trial's ``episode.jsonl`` and the
App State recorded around each step in ``states.jsonl``. ``hindsight`` and an
in-process ``check`` run on the stored artifacts as they did live. Apps are
gone by then, so ``step.apps`` and ``episode.apps`` hold recorded State, and
``query`` cannot be called.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plural.apps.host import STATES_FILE
from plural.rewards import (
    LEDGER_FILE,
    HindsightVerifier,
    RewardRecord,
    RewardTarget,
    event_id,
    read_ledger,
    trial_from_artifacts,
)
from plural.verifiers import (
    DeterministicVerifier,
    Episode,
    Step,
    StepTask,
    VerifierOutput,
    coerce_verifier_output,
)

__all__ = ["RecordedState", "Replay", "replay_verifier"]


class RecordedState(dict[str, Any]):
    """An App's recorded State. Read fields as keys or attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class _RecordedApp:
    """One App as a replayed ``reward`` sees it: its State at that step, read-only."""

    def __init__(self, name: str, state: Any) -> None:
        self.name = name
        self._state = state

    @property
    def state(self) -> Any:
        """The App's recorded State."""
        return RecordedState(self._state) if isinstance(self._state, Mapping) else self._state

    def snapshot(self) -> Any:
        """The App's recorded snapshot.

        Returns:
            The snapshot, or ``None`` when the App recorded none.
        """
        return self._state

    def query(self, action: str, /, **arguments: Any) -> Any:
        """Unavailable: a stored Trial's Apps are no longer running.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError(
            f"{self.name}.{action} cannot be queried on a stored Trial: its Apps are no "
            "longer running. Read step.apps[...].state instead, or run the Task again."
        )


@dataclass
class Replay:
    """What one Verifier gives a stored Trial."""

    rewards: list[RewardRecord] = field(default_factory=list)
    output: VerifierOutput | None = None
    problems: list[str] = field(default_factory=list)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _step_rewards(
    verifier: DeterministicVerifier,
    events: Sequence[Mapping[str, Any]],
    states: Sequence[Mapping[str, Any]],
    task: StepTask,
) -> list[RewardRecord]:
    fn = verifier.reward_fn
    assert fn is not None
    by_step = {int(line["step"]): line for line in states if "step" in line}
    current: dict[str, Any] = dict((by_step.get(0) or {}).get("state") or {})
    records: list[RewardRecord] = []
    turns = 0
    for record in events:
        if record.get("kind") != "environment.step":
            continue
        info = record.get("info") if isinstance(record.get("info"), Mapping) else {}
        line = by_step.get(int((info or {}).get("step") or 0))
        if line is None or not line.get("app"):
            continue
        app = str(line["app"])
        previous = current.get(app)
        current.update(line.get("state") or {})
        turns += 1
        step = Step(
            task=task,
            turn=turns,
            app=app,
            action=str(line.get("action") or record.get("action") or ""),
            arguments=dict(record.get("arguments") or {}),
            observation=None if record.get("error") else record.get("observation"),
            error=record.get("error") or line.get("error"),
            previous_state=previous,
            current_state=current.get(app),
            apps={name: _RecordedApp(name, state) for name, state in current.items()},
        )
        value = fn(step)
        if value is None:
            continue
        identifier = record.get("event_id") or event_id(int(record.get("sequence") or 0))
        records.append(
            RewardRecord(
                target=RewardTarget.step(str(identifier)),
                value=float(value),
                source="step",
                verifier=verifier.name,
                version=verifier.version,
                app=app,
            )
        )
    return records


def replay_verifier(
    verifier: DeterministicVerifier,
    artifacts: Path,
    *,
    task: StepTask | None = None,
    trial_id: str = "",
    score: float | None = None,
) -> Replay:
    """Run ``verifier``'s hooks on one stored execution's artifacts.

    A hook that cannot run on stored artifacts, or that raises, is reported in
    ``problems`` and the others still run.

    Returns:
        The rewards it gives, step and hindsight, and its check's output.
    """
    result = Replay()
    events = _jsonl(artifacts / "episode.jsonl")
    if verifier.reward is not None:
        states = _jsonl(artifacts / STATES_FILE)
        if verifier.reward_fn is None:
            result.problems.append(f"reward {verifier.reward_ref} could not be imported.")
        elif not states:
            result.problems.append(
                "This Trial has no recorded State per step, so reward cannot be replayed. "
                "It ran before Plural recorded it, or its Apps do not snapshot each step."
            )
        else:
            try:
                result.rewards.extend(_step_rewards(verifier, events, states, task or StepTask()))
            except Exception as exc:  # noqa: BLE001 - report it and keep going
                result.problems.append(f"reward failed: {type(exc).__name__}: {exc}")
    if verifier.hindsight is not None:
        fn = verifier.hindsight_fn
        if fn is None:
            result.problems.append(f"hindsight {verifier.hindsight_ref} could not be imported.")
        else:
            trial = trial_from_artifacts(artifacts, score=score)
            trial.trial_id = trial_id
            mine = {(record.target.event_id, record.verifier) for record in result.rewards}
            trial.rewards = (
                *(
                    record
                    for record in read_ledger(artifacts / LEDGER_FILE)
                    if (record.target.event_id, record.verifier) not in mine
                ),
                *result.rewards,
            )
            try:
                hook = HindsightVerifier(fn, name=verifier.name, version=verifier.version)
                result.rewards.extend(hook.apply(trial))
            except Exception as exc:  # noqa: BLE001 - report it and keep going
                result.problems.append(f"hindsight failed: {type(exc).__name__}: {exc}")
    if verifier.check is not None:
        fn = verifier.check_fn
        if fn is None:
            result.problems.append(
                "check runs as a command or an unimported reference, so it only runs in a Trial."
            )
        else:
            apps_file = artifacts / "apps.json"
            apps = json.loads(apps_file.read_text("utf-8")) if apps_file.is_file() else {}
            observation: Any = next(
                (
                    json.loads(path.read_text("utf-8"))
                    for path in (
                        artifacts / "final-observation.json",
                        artifacts / "observation.json",
                    )
                    if path.is_file()
                ),
                {},
            )
            episode = Episode.from_apps(
                apps,
                observation=observation if isinstance(observation, dict) else {},
                trajectory=events,
                rewards=tuple(r.value for r in result.rewards if r.source == "step"),
            )
            try:
                result.output = coerce_verifier_output(fn(episode), verifier_name=verifier.name)
            except Exception as exc:  # noqa: BLE001 - report it and keep going
                result.problems.append(f"check failed: {type(exc).__name__}: {exc}")
    return result
