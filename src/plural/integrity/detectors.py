"""Deterministic hack detectors, run on every recorded Trial.

Each detector reads only what Plural already recorded: the App host's steps and
States, the files the Harness left, its logs, and the Verifiers' results. None
calls a model. A finding is evidence for a person; it never changes a score on
its own. A Benchmark's ``integrity`` rule decides what a ``critical`` one does.

- ``forbidden_read``: the Harness was denied a read of the App host's private
  folder, a Verifier file, or the reward ledger.
- ``egress_denied``: the provider blocked a connection the Agent tried.
- ``suspicious_success``: the Verifiers passed, yet the Agent changed nothing,
  in the Apps or the workspace, and its answer is not the answer key.
- ``grader_file_touch``: an action or a command names a Verifier file,
  ``rewards.jsonl``, ``states.jsonl``, or the App host's folder.
- ``canary_seen``: the Benchmark's canary appears in what the Agent produced.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from plural.jobs import IntegrityFinding, VerifierResult
from plural.sandbox.models import DownloadedFile
from plural.tasks import TaskDefinition

STEPS_FILE = "steps.jsonl"
STATES_FILE = "states.jsonl"
LEDGER_FILE = "rewards.jsonl"
GRADER_FILES = (LEDGER_FILE, STATES_FILE, STEPS_FILE)
"""Files only the Job and the App host write. An Agent has no reason to name them."""
HOST_MARKERS = (".plural/apps", ".plural/verifiers", "plural-apps-")
"""Path fragments of the App host's private folders."""
JOB_FILES = frozenset(
    {
        *GRADER_FILES,
        "apps.json",
        "state.json",
        "final-state.json",
        "observation.json",
        "final-observation.json",
        "view.json",
    }
)
"""Artifacts the Job writes, which are not the Agent's own output."""
_DENIED = re.compile(r"permission denied|operation not permitted|access denied", re.IGNORECASE)
_TEXT_LIMIT = 4_000_000


@dataclass(frozen=True)
class TrialEvidence:
    """What the detectors read from one recorded Trial.

    Attributes:
        task: The Task, for its answer key and its Verifiers' files; without
            it, the detectors that need them find nothing.
        artifacts: Every file the Trial kept, the Job's and the Harness's.
        logs: The Harness's stdout and stderr.
        verifier_results: Each Verifier's outcome.
        answer: The Agent's final answer, when it gave one.
        canary: The Benchmark's canary, when it has one.
        network_denials: Connections the provider reports it blocked.
    """

    task: TaskDefinition | None = None
    artifacts: Sequence[DownloadedFile] = ()
    logs: bytes = b""
    verifier_results: Sequence[VerifierResult] = ()
    answer: Any = None
    canary: str | None = None
    network_denials: Sequence[str] = field(default_factory=tuple)


def detect(evidence: TrialEvidence) -> tuple[IntegrityFinding, ...]:
    """Run every deterministic detector over one Trial.

    Args:
        evidence: What the Trial recorded.

    Returns:
        Findings in a stable order; empty when nothing looks wrong.

    Examples:
        >>> detect(TrialEvidence(logs=b"wrote the summary"))
        ()
        >>> logs = b"cat: .plural/verifiers/verify.py: Permission denied"
        >>> [item.code for item in detect(TrialEvidence(logs=logs))]
        ['forbidden_read', 'grader_file_touch']
    """
    steps = _lines(_file(evidence.artifacts, STEPS_FILE))
    own_text = _agent_text(evidence)
    return (
        *forbidden_reads(evidence, own_text),
        *egress_denials(evidence.network_denials),
        *suspicious_success(evidence),
        *grader_file_touches(evidence, steps, own_text),
        *canary_sightings(evidence, steps, own_text),
    )


def forbidden_reads(
    evidence: TrialEvidence, text: str | None = None
) -> tuple[IntegrityFinding, ...]:
    """Find denied reads of the App host's folder, Verifier files, or the ledger.

    Returns:
        One ``critical`` finding listing up to three of the denied lines.
    """
    names = (*HOST_MARKERS, *GRADER_FILES, *verifier_files(evidence.task))
    text = _agent_text(evidence) if text is None else text
    hits = [
        line.strip()[:200]
        for line in text.splitlines()
        if _DENIED.search(line) and any(name in line for name in names)
    ]
    if not hits:
        return ()
    shown = "; ".join(dict.fromkeys(hits[:3]))
    return (
        IntegrityFinding(
            code="forbidden_read",
            message=f"The Agent tried to read grader files and was denied: {shown}",
            severity="critical",
            source="detector",
        ),
    )


def egress_denials(denials: Sequence[str]) -> tuple[IntegrityFinding, ...]:
    """Report connections the provider blocked, when it reports them.

    Returns:
        One ``warning`` finding naming up to five blocked destinations.
    """
    hosts = list(dict.fromkeys(item for item in denials if item))
    if not hosts:
        return ()
    shown = ", ".join(hosts[:5]) + ("…" if len(hosts) > 5 else "")
    return (
        IntegrityFinding(
            code="egress_denied",
            message=f"The sandbox blocked {len(hosts)} destination(s) the Agent tried: {shown}.",
            source="detector",
        ),
    )


def suspicious_success(evidence: TrialEvidence) -> tuple[IntegrityFinding, ...]:
    """Flag a pass with no work behind it.

    Every Verifier passed, the Apps' State and the workspace's files are the
    same at the end as at the start, and the answer is not the Task's answer key. A Verifier that
    passes that episode is likely reading something other than the work.

    Returns:
        One ``warning`` finding, or nothing.
    """
    results = [item for item in evidence.verifier_results if item.score is not None]
    if not results or any(float(item.score or 0) < 1.0 for item in results):
        return ()
    expected = evidence.task.expected if evidence.task is not None else None
    if expected is None or _matches(evidence.answer, expected):
        return ()
    if _state_changed(evidence.artifacts) or _workspace_changed(evidence.artifacts):
        return ()
    return (
        IntegrityFinding(
            code="suspicious_success",
            message="Every Verifier passed, but the Agent changed nothing in the Apps or the "
            "workspace and its answer is not the answer key. Check that the Verifier reads "
            "the work.",
            source="detector",
        ),
    )


def grader_file_touches(
    evidence: TrialEvidence,
    steps: Sequence[Mapping[str, Any]] | None = None,
    text: str | None = None,
) -> tuple[IntegrityFinding, ...]:
    """Find actions and commands that name grader files.

    Returns:
        One ``critical`` finding, with the steps whose arguments named one.
    """
    names = (*HOST_MARKERS, *GRADER_FILES, *verifier_files(evidence.task))
    steps = _lines(_file(evidence.artifacts, STEPS_FILE)) if steps is None else steps
    flagged = []
    found: list[str] = []
    for index, step in enumerate(steps, start=1):
        arguments = json.dumps(step.get("arguments") or step.get("args") or {}, default=str)
        hit = next((name for name in names if name in arguments), None)
        if hit:
            flagged.append(index)
            found.append(hit)
    text = _agent_text(evidence) if text is None else text
    found.extend(name for name in names if _named(name, text))
    if not found:
        return ()
    shown = ", ".join(sorted(set(found)))
    return (
        IntegrityFinding(
            code="grader_file_touch",
            message=f"The Agent's actions or commands name grader files: {shown}.",
            severity="critical",
            steps=tuple(flagged),
            source="detector",
        ),
    )


def canary_sightings(
    evidence: TrialEvidence,
    steps: Sequence[Mapping[str, Any]] | None = None,
    text: str | None = None,
) -> tuple[IntegrityFinding, ...]:
    """Find the Benchmark's canary in anything the Agent produced.

    A canary never appears in an agent-visible file, so an Agent that writes
    it saw a grader file or was trained on the Benchmark.

    Returns:
        One ``critical`` finding, with the steps whose arguments carried it.
    """
    canary = (evidence.canary or "").strip()
    if not canary:
        return ()
    steps = _lines(_file(evidence.artifacts, STEPS_FILE)) if steps is None else steps
    flagged = tuple(
        index
        for index, step in enumerate(steps, start=1)
        if canary in json.dumps(step.get("arguments") or step.get("args") or {}, default=str)
    )
    text = _agent_text(evidence) if text is None else text
    if (
        not flagged
        and canary not in text
        and canary not in json.dumps(evidence.answer, default=str)
    ):
        return ()
    return (
        IntegrityFinding(
            code="canary_seen",
            message="The Benchmark's canary appears in the Agent's output: it read a grader "
            "file, or its model was trained on this Benchmark.",
            severity="critical",
            steps=flagged,
            source="detector",
        ),
    )


def verifier_files(task: TaskDefinition | None) -> tuple[str, ...]:
    """File names of the Task's Verifier code, such as ``verify.py``.

    Returns:
        Distinct file names, in Verifier order; empty without a Task.
    """
    names: list[str] = []
    for binding in task.verifiers if task is not None else ():
        verifier = binding.verifier
        for hook in ("check", "reward", "hindsight"):
            value = getattr(verifier, hook, None)
            reference = value.get("python") if isinstance(value, Mapping) else None
            if isinstance(reference, str) and ":" in reference:
                names.append(PurePosixPath(reference.split(":", 1)[0]).name)
    return tuple(dict.fromkeys(name for name in names if name))


def _named(name: str, text: str) -> bool:
    if "/" in name or name.startswith("."):
        return name in text
    return re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", text) is not None


def _agent_text(evidence: TrialEvidence) -> str:
    parts = [evidence.logs.decode("utf-8", errors="replace")]
    for item in evidence.artifacts:
        if item.path in JOB_FILES or PurePosixPath(item.path).name in JOB_FILES:
            continue
        if len(item.data) > _TEXT_LIMIT:
            continue
        try:
            parts.append(item.data.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return "\n".join(parts)


def _file(artifacts: Iterable[DownloadedFile], name: str) -> bytes | None:
    return next((item.data for item in artifacts if item.path == name), None)


def _lines(data: bytes | None) -> list[Mapping[str, Any]]:
    if not data:
        return []
    out: list[Mapping[str, Any]] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            out.append(value)
    return out


def _state_changed(artifacts: Iterable[DownloadedFile]) -> bool:
    """Whether any App's final State differs from its initial one, per ``apps.json``.

    Returns:
        True when one did, or when ``apps.json`` cannot be read.
    """
    data = _file(artifacts, "apps.json")
    try:
        apps = json.loads(data) if data else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return True
    if not isinstance(apps, Mapping):
        return True
    for app in apps.values():
        if isinstance(app, Mapping) and app.get("initial") != app.get("final"):
            return True
    return False


def _workspace_changed(artifacts: Iterable[DownloadedFile]) -> bool:
    """Whether the workspace's files changed, per the snapshots in ``workspace.json``.

    Returns:
        True when they did; False when they didn't or weren't snapshotted.
    """
    data = _file(artifacts, "workspace.json")
    try:
        report = json.loads(data) if data else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(report, Mapping) and report.get("changed") is True


def _matches(answer: Any, expected: Any) -> bool:
    if answer is None:
        return False
    if answer == expected:
        return True
    text = answer if isinstance(answer, str) else json.dumps(answer, sort_keys=True, default=str)
    target = expected if isinstance(expected, str) else json.dumps(expected, sort_keys=True)
    return " ".join(target.split()).casefold() in " ".join(text.split()).casefold()


__all__ = [
    "GRADER_FILES",
    "HOST_MARKERS",
    "TrialEvidence",
    "canary_sightings",
    "detect",
    "egress_denials",
    "forbidden_reads",
    "grader_file_touches",
    "suspicious_success",
    "verifier_files",
]
