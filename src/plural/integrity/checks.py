"""A Task's grader check: the probes' verdicts and the leak scan, kept per Task version.

``plural task check`` writes one :class:`TaskCheck` per Task version to
``.plural/checks/<task>@<version>.json``. The rules:

- the ``reference`` probe must reach the success threshold;
- ``noop`` and ``echo`` must stay below it, because a grader that passes an
  Agent doing nothing is checking something other than the work;
- no critical or warning leak.

``random`` is a warning only: a random action is sometimes the right one, such as
a handoff on a request that should be handed off.

A probe that crashed is reported as an error, not as a pass or a failure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from plural.common import FrozenModel
from plural.harness.probes import ProbeKind
from plural.integrity.leaks import LeakFinding
from plural.jobs import TrialResult

ProbeStatus = Literal["passed", "failed", "error", "skipped"]


class ProbeResult(FrozenModel):
    """How one probe fared on one Task.

    Attributes:
        probe: Which probe.
        status: ``passed`` when the graders treated it as they should,
            ``failed`` when they didn't, ``error`` when it couldn't run, and
            ``skipped`` when it doesn't apply, such as a Task with no reference.
        score: The Trial's score.
        threshold: The score that counts as success.
        detail: What happened, in one line.
        feedback: The Verifiers' feedback on the probe's Trial.
        failed_checks: The Verifier sub-scores that were zero.
        trial_id: The probe's Trial, kept with the check's local Jobs.
    """

    probe: ProbeKind
    status: ProbeStatus
    score: float | None = None
    threshold: float = 1.0
    detail: str = ""
    feedback: str = ""
    failed_checks: tuple[str, ...] = ()
    trial_id: str | None = None


class TaskCheck(FrozenModel):
    """One Task version's grader check.

    Attributes:
        task: The Task's name.
        version: The Task's version.
        content_hash: The Task revision the check ran on.
        checked_at: When it ran.
        probes: Each probe's result.
        leaks: What the leak scan found, most severe first.
    """

    task: str
    version: str
    content_hash: str
    checked_at: datetime
    probes: tuple[ProbeResult, ...] = ()
    leaks: tuple[LeakFinding, ...] = ()

    @property
    def problems(self) -> tuple[str, ...]:
        """One line per thing to fix, probes first.

        Examples:
            >>> from datetime import timezone
            >>> check = TaskCheck(
            ...     task="t",
            ...     version="1.0.0",
            ...     content_hash="sha256:0",
            ...     checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ...     probes=(ProbeResult(probe="noop", status="failed", detail="noop passes"),),
            ... )
            >>> check.problems
            ('noop passes',)
        """
        lines = [
            item.detail
            for item in self.probes
            if item.status == "error" or (item.status == "failed" and item.probe != "random")
        ]
        lines.extend(item.message for item in self.leaks if item.severity != "info")
        return tuple(lines)

    @property
    def warnings(self) -> tuple[str, ...]:
        """What may be fine but deserves a look: a random probe that passed."""
        return tuple(
            item.detail
            for item in self.probes
            if item.probe == "random" and item.status == "failed"
        )

    @property
    def not_scanned(self) -> tuple[str, ...]:
        """Paths the leak scan could not read, which are never reported as clean."""
        return tuple(item.path for item in self.leaks if item.kind == "not_scanned")

    @property
    def passed(self) -> bool:
        """Whether nothing needs fixing."""
        return not self.problems

    def probe(self, kind: ProbeKind) -> ProbeResult | None:
        """This check's result for one probe, if it ran.

        Returns:
            The result, or ``None``.
        """
        return next((item for item in self.probes if item.probe == kind), None)


def judge_probe(kind: ProbeKind, trial: TrialResult, threshold: float) -> ProbeResult:
    """Apply the probe rules to one probe Trial.

    Returns:
        ``passed`` when the reference reached the threshold or another probe
        stayed below it.

    Examples:
        >>> from plural.jobs import TrialResult
        >>> trial = TrialResult.model_construct(
        ...     status="succeeded", score=1.0, verifier_results=(), receipt=None
        ... )
        >>> judge_probe("noop", trial, 1.0).detail
        'noop passes: the graders gave 1.00 to an Agent that did nothing'
    """
    trial_id = trial.receipt.trial_id if trial.receipt is not None else None
    if trial.status != "succeeded" or trial.score is None:
        reason = (trial.error_message or trial.status).strip().splitlines()
        return ProbeResult(
            probe=kind,
            status="error",
            threshold=threshold,
            detail=f"{kind} could not run: {reason[0] if reason else trial.status}",
            trial_id=trial_id,
        )
    zero = tuple(
        name
        for result in trial.verifier_results
        for name, value in sorted(result.scores.items())
        if value == 0.0
    )
    feedback = "; ".join(
        result.feedback.strip() for result in trial.verifier_results if result.feedback.strip()
    )
    score = float(trial.score)
    if kind == "reference":
        passed = score >= threshold
        checks = ", ".join(zero) or f"the threshold ({threshold:g})"
        detail = (
            f"reference passes ({score:.2f})"
            if passed
            else f"reference fails {checks}: {feedback or f'scored {score:.2f}'}"
        )
    else:
        passed = score < threshold
        what = {
            "noop": "an Agent that did nothing",
            "echo": "an Agent that repeated the instructions",
            "random": "an Agent taking random actions",
        }[kind]
        detail = (
            f"{kind} fails, as it should ({score:.2f})"
            if passed
            else f"{kind} passes: the graders gave {score:.2f} to {what}"
        )
    return ProbeResult(
        probe=kind,
        status="passed" if passed else "failed",
        score=score,
        threshold=threshold,
        detail=detail,
        feedback=feedback,
        failed_checks=zero,
        trial_id=trial_id,
    )


__all__ = ["ProbeResult", "ProbeStatus", "TaskCheck", "judge_probe"]
