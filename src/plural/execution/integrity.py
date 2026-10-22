"""Where an External Agent's own account of an episode departs from what Plural observed.

Plural observes every action an External Agent takes, because each one runs
through the App host. What it cannot observe is the agent's reasoning and model
calls, so the agent reports those as a trace. The audit sets that trace beside
the host's record and lists each disagreement. A finding is evidence for a
person to read; it never changes a score.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from plural.execution.external import AGENT_TRACE_FILE
from plural.execution.steps import STEPS_FILE
from plural.jobs import IntegrityFinding
from plural.sandbox import DownloadedFile

CLOCK_SKEW = timedelta(seconds=60)


def audit_external(
    artifacts: Sequence[DownloadedFile],
    *,
    actions: Iterable[str],
    started_at: datetime,
    finished_at: datetime,
) -> tuple[IntegrityFinding, ...]:
    """Compare an External Agent's trace with the episode Plural observed.

    Returns:
        One finding per disagreement, in a stable order; empty when they agree.
    """
    files = {item.path: item.data for item in artifacts}
    trace = _json(files.get(AGENT_TRACE_FILE))
    if not isinstance(trace, Mapping):
        return (
            IntegrityFinding(
                code="no_trace",
                message="The agent reported no trace, so only its actions were observed.",
            ),
        )
    steps = [item for item in trace.get("steps") or () if isinstance(item, Mapping)]
    names = set(actions)
    claimed = Counter(
        str(call.get("function_name"))
        for step in steps
        for call in step.get("tool_calls") or ()
        if isinstance(call, Mapping) and call.get("function_name") in names
    )
    observed = Counter(
        str(step["action"]) for step in _lines(files.get(STEPS_FILE)) if step.get("action")
    )
    findings: list[IntegrityFinding] = []
    for name in sorted(set(claimed) | set(observed)):
        if claimed[name] > observed[name]:
            findings.append(
                IntegrityFinding(
                    code="actions_not_observed",
                    message=f"The trace claims {claimed[name]} call(s) of {name!r}; "
                    f"Plural observed {observed[name]}.",
                )
            )
        elif observed[name] > claimed[name]:
            findings.append(
                IntegrityFinding(
                    code="actions_not_traced",
                    message=f"Plural observed {observed[name]} call(s) of {name!r}; "
                    f"the trace shows {claimed[name]}.",
                )
            )
    answer = _response(files.get("result.json"))
    final = next(
        (
            str(step.get("message") or "")
            for step in reversed(steps)
            if step.get("source") == "agent" and str(step.get("message") or "").strip()
        ),
        "",
    )
    if answer and final and _normal(answer) not in _normal(final):
        findings.append(
            IntegrityFinding(
                code="answer_differs",
                message="The agent's final message in its trace is not the answer it submitted.",
            )
        )
    outside = sum(
        1
        for step in steps
        if (moment := _moment(step.get("timestamp"))) is not None
        and not started_at - CLOCK_SKEW <= moment <= finished_at + CLOCK_SKEW
    )
    if outside:
        findings.append(
            IntegrityFinding(
                code="trace_outside_episode",
                message=f"{outside} trace step(s) are timed outside the episode.",
            )
        )
    return tuple(findings)


def _json(data: bytes | None) -> Any:
    if data is None:
        return None
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _lines(data: bytes | None) -> list[Mapping[str, Any]]:
    if data is None:
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


def _response(data: bytes | None) -> str:
    result = _json(data)
    response = result.get("response") if isinstance(result, Mapping) else None
    return response if isinstance(response, str) else ""


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


__all__ = ["audit_external"]
