"""Findings: the Inspector's conclusion about one failed Trial.

A Finding names the critical step, a cause dimension, the cause in words, the
evidence, and the forks that tested it. Its status is computed here from those
forks, never chosen by the model:

- ``confirmed``: a fork that made the proposed change beat its controls;
- ``refuted``: every fork that decided ruled out any improvement: the top of its
  interval is at or below zero;
- ``inconclusive``: forks ran, but too few to decide, or their intervals still
  allow an improvement;
- ``inferred``: no fork tested it.

A Job's Findings are saved beside it, in ``findings.json``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from plural.agents.models import ContextPolicy, context_into_harness_config, context_policy
from plural.agents.tool_overrides import ToolOverride
from plural.common import FrozenModel
from plural.stats import ForkVerdict

FindingStatus = Literal["confirmed", "inferred", "refuted", "inconclusive"]

FINDINGS_FILE = "findings.json"
"""Beside a Job's ``result.json``: the Findings ``plural job inspect`` recorded."""


def mentions(text: str, name: str) -> bool:
    """Whether lowercased ``text`` names ``name`` as a whole word or identifier.

    Returns:
        True when it does.
    """
    return re.search(rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])", text) is not None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


class Remedy(FrozenModel):
    """A change to the Agent that a Finding proposes, and ``plural agent revise`` applies.

    Attributes:
        instructions: The Agent's whole new instructions.
        tool_overrides: How tools are described to the model, by tool name.
        model: Another model.
        harness_config: Harness settings to set, including ``context``, the Agent's
            whole new context policy, such as summary instructions that keep what a
            summary lost.
        note: What to change, in words, for an External Agent's team.
    """

    instructions: str | None = Field(default=None, min_length=1)
    tool_overrides: dict[str, ToolOverride] = Field(default_factory=dict)
    model: str | None = Field(default=None, min_length=1)
    harness_config: dict[str, Any] = Field(default_factory=dict)
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def _context_in_harness_config(cls, value: Any) -> Any:
        return context_into_harness_config(value)

    @field_validator("harness_config")
    @classmethod
    def _valid_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        policy = context_policy(value)
        return value if policy is None else {**value, "context": policy.model_dump(mode="json")}

    @property
    def context(self) -> ContextPolicy | None:
        """The context policy the remedy chooses in ``harness_config.context``."""
        return context_policy(self.harness_config)

    @property
    def empty(self) -> bool:
        """Whether the remedy changes nothing Plural can edit."""
        return (
            self.instructions is None
            and not self.tool_overrides
            and self.model is None
            and not self.harness_config
        )

    @property
    def text(self) -> str:
        """Every word the remedy would ship to the Agent, lowercased.

        That is its instructions, tool descriptions, string Harness settings (such as
        context summary instructions), and note.
        """
        parts = [self.instructions or "", self.note]
        parts += [item.description or "" for item in self.tool_overrides.values()]
        parts += _strings(self.harness_config)
        return "\n".join(parts).lower()

    def names(self, entities: Iterable[str]) -> list[str]:
        """Which of ``entities`` the remedy names, as whole words.

        Returns:
            The names it mentions, sorted.
        """
        text = self.text
        return sorted(name for name in entities if mentions(text, name))

    def describe(self) -> list[str]:
        """The remedy in short lines.

        Returns:
            One line per thing it changes.
        """
        lines = []
        if self.model is not None:
            lines.append(f"model: {self.model}")
        if self.instructions is not None:
            lines.append("instructions: rewritten")
        for name, item in sorted(self.tool_overrides.items()):
            lines.append(
                f"tool {name}: hidden" if item.hidden else f"tool {name}: {item.description}"
            )
        for key, value in sorted(self.harness_config.items()):
            if key == "context" and self.context is not None:
                lines.append(f"harness_config.context: {self.context.strategy}, rewritten")
            else:
                lines.append(f"harness_config.{key}: {json.dumps(value)}")
        if self.note:
            lines.append(self.note)
        return lines


class ForkTest(FrozenModel):
    """One fork the Inspector ran to test a cause, and how it came out.

    Attributes:
        test_id: The test's id within the inspection, such as ``X1``.
        job_id: The fork Job.
        step: The step the forks continued after.
        remedy: The change to the Agent the candidates ran with.
        change: A diagnostic change's name, when the fork changed what the
            Agent saw instead.
        payload: The diagnostic change's payload.
        gates: The gates each side was judged on, or none for the whole Trial.
        verdict: The candidates against the controls.
        candidate: The candidates' pass rate.
        control: The controls' pass rate.
        low: Lower end of the 95% interval of the difference.
        high: Upper end of the 95% interval of the difference.
        candidates: How many candidate forks finished.
        controls: How many controls finished.
        controls_reproduced: The share of controls that failed as the Trial did.
        outcomes: For each side (``candidate``, ``control``), how many of its
            Trials passed whole (``passed``) and how many failed each gate.
        cost_usd: What the fork Job's model calls cost.
    """

    test_id: str
    job_id: str
    step: int
    remedy: Remedy | None = None
    change: str | None = None
    payload: Any = None
    gates: tuple[str, ...] = ()
    verdict: ForkVerdict
    candidate: float | None = None
    control: float | None = None
    low: float | None = None
    high: float | None = None
    candidates: int = 0
    controls: int = 0
    controls_reproduced: float | None = None
    outcomes: dict[str, dict[str, int]] = Field(default_factory=dict)
    cost_usd: float = 0.0

    @property
    def beat_controls(self) -> bool:
        """Whether the candidates passed clearly more often than the controls."""
        return (
            self.verdict == "likely_matters"
            and self.candidate is not None
            and self.control is not None
            and self.candidate > self.control
        )

    @property
    def ruled_out(self) -> bool:
        """Whether the fork decided the change doesn't help: no improvement is in its interval."""
        if self.verdict == "too_few":
            return False
        if self.high is None:
            return not self.beat_controls
        return self.high <= 0


class Finding(FrozenModel):
    """The Inspector's conclusion about one failed Trial.

    Attributes:
        finding_id: Its id within the Job, such as ``F1``.
        job_id: The inspected Job.
        trial_id: The failed Trial.
        task: The Trial's Task.
        agent: The Agent the Trial ran.
        critical_step: The step where the Trial went wrong, or ``None`` when
            the Agent's work was right and the grading was wrong.
        cause: The cause dimension, such as ``tools``.
        gates: The Trial's failed gates this cause explains.
        summary: The cause, in a sentence or two.
        evidence: What shows it, each with the step or record it comes from.
        forks: The forks that tested it.
        status: How far the forks support it.
        remedy: The change to the Agent it proposes, if any.
        inspector_trial_id: The Inspector's own Trial that recorded it.
    """

    finding_id: str = Field(pattern=r"^F[0-9]+$")
    job_id: str
    trial_id: str
    task: str
    agent: str
    critical_step: int | None = None
    cause: str
    gates: tuple[str, ...] = ()
    summary: str = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    forks: tuple[ForkTest, ...] = ()
    status: FindingStatus
    remedy: Remedy | None = None
    inspector_trial_id: str | None = None


class InspectionRecord(FrozenModel):
    """What ``plural job inspect`` recorded for one Job.

    Attributes:
        job_id: The inspected Job.
        inspected_at: When.
        inspector_job_id: The Job the Inspector ran as, in the Inspector's folder.
        depth: How deep it looked.
        failed: How many dev Trials failed.
        findings: One per failed Trial the Inspector concluded on.
        uninspected: Failed Trials it recorded nothing for.
        cost_usd: What the Inspector and its forks cost.
    """

    job_id: str
    inspected_at: datetime
    inspector_job_id: str | None = None
    depth: Literal["quick", "standard", "deep"] = "standard"
    failed: int = 0
    findings: tuple[Finding, ...] = ()
    uninspected: tuple[str, ...] = ()
    cost_usd: float = 0.0


def finding_status(
    forks: Sequence[ForkTest], *, agent_cause: bool = True, gates: Sequence[str] = ()
) -> FindingStatus:
    """A Finding's status, from the forks that tested it.

    A fork changes the Agent, so it can only test a cause a change to the Agent
    can fix. A cause outside the Agent, such as ``grader``, stays ``inferred``
    whatever its forks showed. A fork judged on other gates than the Finding's
    tested another cause, and doesn't count.

    A fork with an interval that still allows an improvement hasn't decided, so
    two out of four against none out of four is ``inconclusive``, not ``refuted``.

    Returns:
        ``confirmed`` when a fork beat its controls; ``refuted`` when every
        fork that decided ruled out any improvement; ``inconclusive``
        otherwise; ``inferred`` with no forks, or for a cause outside the Agent.

    Examples:
        >>> finding_status([])
        'inferred'
    """
    if gates:
        forks = [item for item in forks if not item.gates or set(item.gates) & set(gates)]
    if not forks or not agent_cause:
        return "inferred"
    if any(item.beat_controls for item in forks):
        return "confirmed"
    decided = [item for item in forks if item.verdict != "too_few"]
    if decided and all(item.ruled_out for item in decided):
        return "refuted"
    return "inconclusive"


def stronger_model_won(fork: ForkTest, model: str, gates: Sequence[str] = ()) -> bool:
    """Whether a fork shows the Trial failed for want of a stronger model.

    The candidates must have run another model and changed nothing else, beaten
    their controls, and been judged on the gates the Finding explains (or on the
    whole Trial). Beating the controls is what shows the model is stronger here.

    Returns:
        Whether it backs a ``model`` Finding.

    Examples:
        >>> fork = ForkTest(test_id="X1", job_id="j", step=0, verdict="too_few")
        >>> stronger_model_won(fork, "openai/gpt-5.6-luna")
        False
    """
    remedy = fork.remedy
    if remedy is None or remedy.model is None or remedy.model == model or fork.change:
        return False
    if remedy.instructions is not None or remedy.tool_overrides or remedy.harness_config:
        return False
    if gates and fork.gates and not set(fork.gates) & set(gates):
        return False
    return fork.beat_controls


class CauseRow(FrozenModel):
    """One cause dimension's share of a Job's failed Trials.

    A Trial that failed for two independent causes has a Finding for each, so
    shares can add up to more than one.

    Attributes:
        cause: The dimension, or ``uninspected`` for failed Trials with no Finding.
        findings: How many Findings name it.
        share: The share of the failed Trials with such a Finding.
        confirmed: How many of its Findings a fork confirmed.
        statuses: How many Findings have each status.
        trial_ids: Those failed Trials.
    """

    cause: str
    findings: int
    share: float | None = None
    confirmed: int = 0
    statuses: dict[str, int] = Field(default_factory=dict)
    trial_ids: tuple[str, ...] = ()


def breakdown(record: InspectionRecord) -> list[CauseRow]:
    """The failed Trials by cause dimension.

    Returns:
        One row per cause, most frequent first. Failed Trials with no Finding
        are counted under ``uninspected``.
    """
    counts = Counter(item.cause for item in record.findings)
    rows = []
    for cause, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
        members = [item for item in record.findings if item.cause == cause]
        trials = tuple(dict.fromkeys(item.trial_id for item in members))
        rows.append(
            CauseRow(
                cause=cause,
                findings=count,
                share=len(trials) / record.failed if record.failed else None,
                confirmed=sum(1 for item in members if item.status == "confirmed"),
                statuses=dict(Counter(item.status for item in members)),
                trial_ids=trials,
            )
        )
    if record.uninspected:
        rows.append(
            CauseRow(
                cause="uninspected",
                findings=len(record.uninspected),
                share=len(record.uninspected) / record.failed if record.failed else None,
                trial_ids=tuple(record.uninspected),
            )
        )
    return rows


def restatus(findings: Iterable[Finding], agent_causes: Iterable[str]) -> tuple[Finding, ...]:
    """Findings with each status computed from its forks, never as recorded.

    Returns:
        The Findings, statuses recomputed.
    """
    agent = set(agent_causes)
    return tuple(
        item.model_copy(
            update={
                "status": finding_status(
                    item.forks, agent_cause=item.cause in agent, gates=item.gates
                )
            }
        )
        for item in findings
    )


def number_findings(job_id: str, drafts: Iterable[dict[str, Any]]) -> tuple[Finding, ...]:
    """Number a Job's Findings F1, F2, ... in Trial order.

    Returns:
        The Findings.
    """
    return tuple(
        Finding.model_validate({**item, "job_id": job_id, "finding_id": f"F{index}"})
        for index, item in enumerate(drafts, start=1)
    )


def save_findings(job_directory: Path, record: InspectionRecord) -> Path:
    """Write a Job's Findings beside its result.

    Returns:
        The file.
    """
    path = job_directory / FINDINGS_FILE
    path.write_text(record.model_dump_json(indent=2) + "\n", "utf-8")
    return path


def load_findings(job_directory: Path) -> InspectionRecord | None:
    """A Job's Findings, if it was inspected.

    Returns:
        The record, or ``None``.
    """
    path = job_directory / FINDINGS_FILE
    if not path.is_file():
        return None
    return InspectionRecord.model_validate_json(path.read_text("utf-8"))


def now() -> datetime:
    """The current time, in UTC.

    Returns:
        The time.
    """
    return datetime.now(timezone.utc)


__all__ = [
    "FINDINGS_FILE",
    "CauseRow",
    "Finding",
    "FindingStatus",
    "ForkTest",
    "InspectionRecord",
    "Remedy",
    "breakdown",
    "finding_status",
    "load_findings",
    "mentions",
    "now",
    "number_findings",
    "restatus",
    "save_findings",
    "stronger_model_won",
]
