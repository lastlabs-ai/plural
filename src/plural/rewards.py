"""Rewards: credit attached to trajectory targets, kept in a ledger beside the trajectory.

A reward is credit for part of what happened in an episode. It never reaches the
Agent, and counts toward a score only through a Verifier whose ``check`` is
:func:`~plural.total_reward`. Each one is a :class:`RewardRecord` in
an append-only ledger, ``rewards.jsonl``, stored next to the trajectory rather
than inside it. The trajectory stays immutable, so a Trial can be relabeled any
number of times without rerunning it, and older labels are kept.

A record targets one of three things, through a :class:`RewardTarget`:

- a step: an action and the observation it produced,
- an event: one model call, message, reasoning block, or tool call,
- a span inside an event: character offsets into its text, or a token range on
  the TITO record of that model call.

Both come from the Task's Verifiers. Step rewards are given while the episode
runs, by each Verifier's ``reward`` hook, beside the Apps. Hindsight rewards are
given after it ends, by its ``hindsight`` hook, which reads the whole
trajectory, the Apps' snapshots, and the score. ``plural verifier apply`` runs
both again on stored Trials.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from plural.common import FrozenModel

LEDGER_FILE = "rewards.jsonl"
RewardSource = Literal["step", "environment", "hindsight", "judge", "human"]
# "environment" is kept only so ledgers written before every reward came from a Verifier still read.
TextField = Literal["text", "reasoning"]


def event_id(sequence: int) -> str:
    """The stable id of the episode record at ``sequence``.

    Returns:
        An id unique within one Trial execution.
    """
    return f"e{sequence}"


class RewardTarget(FrozenModel):
    """What a reward is credit for.

    Build one with :meth:`reward`, :meth:`event`, :meth:`span`, or :meth:`tokens`.
    """

    kind: Literal["step", "event", "span"]
    event_id: str = Field(min_length=1)
    field: TextField | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    token_start: int | None = Field(default=None, ge=0)
    token_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valid_range(self) -> RewardTarget:
        characters = (self.start, self.end)
        tokens = (self.token_start, self.token_end)
        if self.kind != "span":
            if any(item is not None for item in (*characters, *tokens, self.field)):
                raise ValueError(f"a {self.kind} target takes no range; use a span target")
            return self
        has_characters = all(item is not None for item in characters)
        has_tokens = all(item is not None for item in tokens)
        if has_characters == has_tokens or (
            any(item is not None for item in characters) and not has_characters
        ):
            raise ValueError(
                "a span target needs exactly one range: start and end characters, "
                "or token_start and token_end"
            )
        low, high = characters if has_characters else tokens
        if low is not None and high is not None and low >= high:
            raise ValueError("a span must end after it starts")
        if has_characters and self.field is None:
            raise ValueError("a character span names the field it covers: text or reasoning")
        return self

    @classmethod
    def step(cls, event_id: str) -> RewardTarget:
        """Target an Environment step: an action and its observation.

        Returns:
            The target.
        """
        return cls(kind="step", event_id=event_id)

    @classmethod
    def event(cls, event_id: str) -> RewardTarget:
        """Target one whole event, such as a model call.

        Returns:
            The target.
        """
        return cls(kind="event", event_id=event_id)

    @classmethod
    def span(
        cls, event_id: str, start: int, end: int, *, field: TextField = "text"
    ) -> RewardTarget:
        """Target characters ``start`` to ``end`` of a model call's text or reasoning.

        Returns:
            The target.
        """
        return cls(kind="span", event_id=event_id, field=field, start=start, end=end)

    @classmethod
    def tokens(cls, event_id: str, start: int, end: int) -> RewardTarget:
        """Target output tokens ``start`` to ``end`` of a model call's TITO record.

        Returns:
            The target.
        """
        return cls(kind="span", event_id=event_id, token_start=start, token_end=end)


class RewardRecord(FrozenModel):
    """One entry in a Trial's reward ledger."""

    record_id: str = Field(default_factory=lambda: uuid4().hex)
    target: RewardTarget
    value: float
    weight: float = 1.0
    source: RewardSource
    verifier: str = Field(min_length=1)
    version: str = ""
    app: str | None = None
    seat: str | None = None
    """The seat credited, when several Agents share the episode."""
    off_recording: bool = False
    """True when a replayed App answered this step from its fallback, not a recording."""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _earlier_ledger(cls, data: Any) -> Any:
        # Ledgers written before Verifiers gave rewards name a rewarder, with source "app".
        if isinstance(data, dict) and "rewarder" in data and "verifier" not in data:
            data = {**data, "verifier": data["rewarder"]}
            del data["rewarder"]
            if data.get("source") == "app":
                data["source"] = "step"
        return data

    @model_validator(mode="after")
    def _finite(self) -> RewardRecord:
        if not math.isfinite(self.value) or not math.isfinite(self.weight):
            raise ValueError("reward value and weight must be finite")
        return self


def read_ledger(path: str | Path) -> list[RewardRecord]:
    """Read a ``rewards.jsonl`` ledger.

    Returns:
        Its records in order, or none when the file does not exist.
    """
    source = Path(path)
    if not source.is_file():
        return []
    return parse_ledger(source.read_bytes())


def parse_ledger(data: bytes | str) -> list[RewardRecord]:
    """Parse ledger JSONL.

    Returns:
        Its records in order.
    """
    text = data.decode() if isinstance(data, bytes) else data
    return [RewardRecord.model_validate_json(line) for line in text.splitlines() if line.strip()]


def dump_ledger(records: Iterable[RewardRecord]) -> bytes:
    """Serialize records as ledger JSONL.

    Returns:
        One JSON object per line.
    """
    return "".join(item.model_dump_json() + "\n" for item in records).encode()


def append_ledger(path: str | Path, records: Iterable[RewardRecord]) -> int:
    """Append records to a ledger, creating it if needed.

    Nothing is overwritten, and a record whose ``record_id`` is already in the
    ledger is skipped, so applying the same Verifier version again adds nothing.

    Returns:
        How many records were added.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    known = {item.record_id for item in read_ledger(target)} if target.is_file() else set()
    fresh = [item for item in records if item.record_id not in known]
    with target.open("ab") as handle:
        handle.write(dump_ledger(fresh))
    return len(fresh)


def online_records(episode: Sequence[Mapping[str, Any]]) -> list[RewardRecord]:
    """The step rewards recorded on each step of an ``episode.jsonl``.

    Each Verifier's ``reward`` signal becomes one record targeting that step,
    including on a step whose action rejected its input. A step's bare
    ``reward`` total is not a record: every reward comes from a Verifier.

    Returns:
        The records, in step order.
    """
    records: list[RewardRecord] = []
    for record in episode:
        if record.get("kind") != "environment.step":
            continue
        identifier = record.get("event_id") or event_id(int(record.get("sequence") or 0))
        target = RewardTarget.step(str(identifier))
        info = record.get("info") if isinstance(record.get("info"), Mapping) else {}
        off_recording = bool((info or {}).get("off_recording"))
        signals = [item for item in record.get("rewards") or () if isinstance(item, Mapping)]
        for signal in signals:
            if signal.get("error"):
                continue
            app = signal.get("app")
            seat = signal.get("seat")
            records.append(
                RewardRecord(
                    target=target,
                    value=float(signal.get("value") or 0),
                    weight=float(signal.get("weight", 1.0)),
                    source="step",
                    verifier=str(signal.get("name") or "reward"),
                    version=str(signal.get("version") or ""),
                    app=str(app) if app else None,
                    seat=str(seat) if seat else None,
                    off_recording=off_recording,
                )
            )
    return records


class RewardFailure(FrozenModel):
    """A Verifier whose ``reward`` function raised during the episode."""

    verifier: str
    steps: int = Field(ge=1)
    """How many steps it raised on. They earned it no reward."""
    error: str
    """The first error, such as ``KeyError: 'done' (at verifier.py:14)``."""


def reward_failures(episode: Sequence[Mapping[str, Any]]) -> tuple[RewardFailure, ...]:
    """Each Verifier whose ``reward`` raised on a step of an ``episode.jsonl``.

    Returns:
        One entry per Verifier, in the order they first failed.
    """
    steps: dict[str, int] = {}
    first: dict[str, str] = {}
    for record in episode:
        if record.get("kind") != "environment.step":
            continue
        for signal in record.get("rewards") or ():
            if isinstance(signal, Mapping) and signal.get("error"):
                name = str(signal.get("name") or "reward")
                steps[name] = steps.get(name, 0) + 1
                first.setdefault(name, str(signal["error"]))
    return tuple(
        RewardFailure(verifier=name, steps=count, error=first[name])
        for name, count in steps.items()
    )


# Hindsight credit.


class Credit(FrozenModel):
    """What a Verifier's ``hindsight`` function returns: a value for one target."""

    target: RewardTarget
    value: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class HindsightTrial:
    """Everything a Verifier's ``hindsight`` function can read about one finished Trial.

    ``events`` is the episode record list, each with an ``event_id``. ``apps``
    maps each App name to its snapshots (``initial``, ``check``, ``control``).
    ``score`` is the Trial's score, or ``None`` when it was not scored.
    ``rewards`` is the ledger so far. Nothing here reaches the Agent, and
    nothing a verifier returns changes the score.
    """

    def __init__(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        apps: Mapping[str, Any] | None = None,
        score: float | None = None,
        rewards: Sequence[RewardRecord] = (),
        task_id: str | None = None,
        trial_id: str | None = None,
    ) -> None:
        self.events = [dict(item) for item in events]
        for item in self.events:
            item.setdefault("event_id", event_id(int(item.get("sequence") or 0)))
        self.apps = dict(apps or {})
        self.score = score
        self.rewards = tuple(rewards)
        self.task_id = task_id
        self.trial_id = trial_id

    def steps(self, action: str | None = None) -> list[dict[str, Any]]:
        """The Environment steps, optionally only those for one action.

        Returns:
            Step records in order.
        """
        return [
            item
            for item in self.events
            if item.get("kind") == "environment.step"
            and (action is None or item.get("action") == action)
        ]

    def model_calls(self) -> list[dict[str, Any]]:
        """The model calls, in order.

        Returns:
            Model call records.
        """
        return [item for item in self.events if item.get("kind") == "model.call"]

    def credit(self, target: RewardTarget | str, value: float, **metadata: Any) -> Credit:
        """Credit ``value`` to a target, or to a step given by its event id.

        Returns:
            The credit to return from the verifier.
        """
        resolved = RewardTarget.step(target) if isinstance(target, str) else target
        return Credit(target=resolved, value=value, metadata=metadata)


class HindsightVerifier:
    """A Verifier's ``hindsight`` hook, ready to run on a finished Trial."""

    def __init__(self, fn: Callable[[HindsightTrial], Any], *, name: str, version: str) -> None:
        self.fn = fn
        self.name = name
        self.version = version
        self.__doc__ = fn.__doc__
        self.__name__ = getattr(fn, "__name__", name)
        self.__qualname__ = getattr(fn, "__qualname__", name)
        self.__module__ = getattr(fn, "__module__", __name__)

    def __call__(self, trial: HindsightTrial) -> Any:
        """Call the wrapped function.

        Returns:
            What the function returns.
        """
        return self.fn(trial)

    def apply(self, trial: HindsightTrial) -> list[RewardRecord]:
        """Run on one Trial and turn its credits into ledger records.

        Returns:
            New records with source ``hindsight``.

        Raises:
            ValueError: When the verifier targets an event the Trial does not have.
        """
        produced = self.fn(trial)
        if produced is None:
            return []
        if isinstance(produced, Credit):
            produced = [produced]
        known = {str(item["event_id"]) for item in trial.events}
        records: list[RewardRecord] = []
        for position, item in enumerate(produced):
            credit = item if isinstance(item, Credit) else Credit.model_validate(item)
            if credit.target.event_id not in known:
                raise ValueError(
                    f"Verifier {self.name!r} hindsight targets event "
                    f"{credit.target.event_id!r}, which this Trial does not have"
                )
            identity = [
                trial.trial_id,
                self.name,
                self.version,
                credit.target.model_dump(mode="json"),
                position,
            ]
            records.append(
                RewardRecord(
                    record_id=hashlib.sha256(
                        json.dumps(identity, sort_keys=True).encode()
                    ).hexdigest()[:32],
                    target=credit.target,
                    value=credit.value,
                    source="hindsight",
                    verifier=self.name,
                    version=self.version,
                    metadata=credit.metadata,
                )
            )
        return records


# Training export.

Aggregate = Literal["sum", "mean", "last"]


def align_tito(
    tito: Sequence[Mapping[str, Any]], episode: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Give each TITO record the ``event_id`` of the model call it captured.

    A record that already names its event keeps it. Otherwise the record for
    model turn ``reward`` lines up with the ``reward``-th model call.

    Returns:
        The TITO records with ``event_id`` set where it can be.
    """
    calls = [
        str(item.get("event_id") or event_id(int(item.get("sequence") or 0)))
        for item in episode
        if item.get("kind") == "model.call"
    ]
    aligned: list[dict[str, Any]] = []
    for record in tito:
        item = dict(record)
        step = item.get("step")
        if not item.get("event_id") and isinstance(step, int) and 0 <= step < len(calls):
            item["event_id"] = calls[step]
        aligned.append(item)
    return aligned


def _field_text(call: Mapping[str, Any], field: str) -> str:
    if field == "reasoning":
        return str(call.get("reasoning") or "")
    return str(call.get("text") or "")


def _to_tokens(
    target: RewardTarget, call: Mapping[str, Any], tito: Mapping[str, Any] | None
) -> tuple[int, int] | None:
    """Convert a character span to an output token range, when TITO allows it.

    Returns:
        The token range, or ``None`` when it cannot be worked out exactly.
    """
    if target.token_start is not None and target.token_end is not None:
        return target.token_start, target.token_end
    offsets = (tito or {}).get("output_token_offsets")
    if not offsets or target.start is None or target.end is None:
        return None
    text = _field_text(call, target.field or "text")
    base = str((tito or {}).get("output_text") or "").find(text) if text else -1
    if base < 0:
        return None
    low, high = base + target.start, base + target.end
    covered = [
        index for index, (start, end) in enumerate(offsets) if int(start) < high and int(end) > low
    ]
    return (covered[0], covered[-1] + 1) if covered else None


def _combine(values: Sequence[float], how: Aggregate) -> float:
    if not values:
        return 0.0
    if how == "mean":
        return sum(values) / len(values)
    if how == "last":
        return values[-1]
    return sum(values)


def training_export(
    episode: Sequence[Mapping[str, Any]],
    ledger: Sequence[RewardRecord],
    *,
    tito: Sequence[Mapping[str, Any]] = (),
    verifiers: Mapping[str, str | None] | Sequence[str] | None = None,
    aggregate: Aggregate = "sum",
    include_off_recording: bool = False,
) -> dict[str, Any]:
    """Join a trajectory with its reward ledger for training.

    ``verifiers`` picks which labels to use: a list of names, or a mapping of
    name to the version to use (``None`` for the latest). By default every
    verifier is used, at its latest version. A step reward is credited to the
    model call whose turn issued the action. Rewards on the same target are
    combined with ``aggregate``, after applying each record's weight.

    Returns:
        ``turns``: one entry per model call with its reward, any token-level
        rewards, and its TITO record when there is one; and ``rewards``: the
        records used.
    """
    selected = _select(ledger, verifiers, include_off_recording)
    by_id = {
        str(item.get("event_id") or event_id(int(item.get("sequence") or 0))): item
        for item in episode
    }
    calls = [item for item in episode if item.get("kind") == "model.call"]
    call_ids = [
        str(item.get("event_id") or event_id(int(item.get("sequence") or 0))) for item in calls
    ]
    call_by_turn = {item.get("turn"): call_ids[index] for index, item in enumerate(calls)}
    tito_by_event = {
        str(item["event_id"]): item for item in align_tito(tito, episode) if item.get("event_id")
    }
    whole: dict[str, list[float]] = {}
    spans: dict[str, list[dict[str, Any]]] = {}
    for record in selected:
        event = by_id.get(record.target.event_id)
        if event is None:
            continue
        value = record.value * record.weight
        if event.get("kind") == "environment.step":
            owner = call_by_turn.get(event.get("turn"))
            if owner is not None:
                whole.setdefault(owner, []).append(value)
            continue
        identifier = record.target.event_id
        if record.target.kind != "span":
            whole.setdefault(identifier, []).append(value)
            continue
        tokens = _to_tokens(record.target, event, tito_by_event.get(identifier))
        spans.setdefault(identifier, []).append(
            {
                "start": record.target.start,
                "end": record.target.end,
                "field": record.target.field,
                "token_start": tokens[0] if tokens else None,
                "token_end": tokens[1] if tokens else None,
                "value": value,
                "verifier": record.verifier,
            }
        )
    turns = [
        {
            "event_id": identifier,
            "turn": calls[index].get("turn"),
            "reward": _combine(whole.get(identifier, []), aggregate),
            "span_rewards": spans.get(identifier, []),
            "tito": tito_by_event.get(identifier),
        }
        for index, identifier in enumerate(call_ids)
    ]
    return {
        "schema": "plural.training/v1",
        "aggregate": aggregate,
        "turns": turns,
        "rewards": [item.model_dump(mode="json") for item in selected],
    }


def _select(
    ledger: Sequence[RewardRecord],
    verifiers: Mapping[str, str | None] | Sequence[str] | None,
    include_off_recording: bool,
) -> list[RewardRecord]:
    usable = [item for item in ledger if include_off_recording or not item.off_recording]
    wanted: Mapping[str, str | None] | None
    if verifiers is None:
        wanted = None
    elif isinstance(verifiers, Mapping):
        wanted = verifiers
    else:
        wanted = dict.fromkeys(verifiers)
    # The ledger is append-only, so the last version written is the latest. A
    # Verifier's step and hindsight rewards are written at different times, so
    # each source keeps its own latest version.
    latest: dict[tuple[str, str], str] = {}
    for item in usable:
        latest[(item.verifier, item.source)] = item.version
    chosen: list[RewardRecord] = []
    for item in usable:
        if wanted is not None and item.verifier not in wanted:
            continue
        version = wanted.get(item.verifier) if wanted is not None else None
        if version is None:
            version = latest.get((item.verifier, item.source), "")
        if item.version == version:
            chosen.append(item)
    return chosen


def trial_from_artifacts(folder: Path, *, score: float | None = None) -> HindsightTrial:
    """Build a :class:`HindsightTrial` from one stored execution's artifacts.

    Returns:
        The Trial view.
    """
    episode_file = folder / "episode.jsonl"
    events = (
        [json.loads(line) for line in episode_file.read_text().splitlines() if line.strip()]
        if episode_file.is_file()
        else []
    )
    apps_file = folder / "apps.json"
    apps = json.loads(apps_file.read_text()) if apps_file.is_file() else {}
    from plural.verifiers import Episode

    return HindsightTrial(
        events,
        apps=Episode.from_apps(apps).apps if apps else {},
        score=score,
        rewards=read_ledger(folder / LEDGER_FILE),
    )


__all__ = [
    "LEDGER_FILE",
    "Credit",
    "HindsightVerifier",
    "HindsightTrial",
    "RewardFailure",
    "RewardRecord",
    "RewardSource",
    "RewardTarget",
    "align_tito",
    "append_ledger",
    "dump_ledger",
    "event_id",
    "online_records",
    "parse_ledger",
    "read_ledger",
    "reward_failures",
    "training_export",
    "trial_from_artifacts",
]
