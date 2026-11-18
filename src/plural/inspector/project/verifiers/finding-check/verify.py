"""Check the Inspector's Finding against the Task's answer key, when it has one."""

from typing import Any

from plural import Episode, VerifierOutput

CHECKS = ("cause_correct", "step_correct", "cause_named")


def check(episode: Episode) -> VerifierOutput:
    """Score 1 when a Finding was recorded and every check the answer key allows passes.

    The answer key (inspector-bench only) holds the cause dimension, the critical
    steps it accepts, and words, any one of which names the cause. With several
    Findings, the one naming the expected cause is checked, else the first.
    """
    state = episode.state
    expected = episode.expected or {}
    findings: list[dict[str, Any]] = state.get("findings") or []
    finding = next(
        (item for item in findings if item["cause"] == expected.get("cause")),
        findings[0] if findings else None,
    )
    if state.get("mode") == "ask":
        answered = bool(state.get("answer"))
        return VerifierOutput(
            score=float(answered),
            metrics={"recorded": float(answered), **dict.fromkeys(CHECKS)},
            evidence=(f"answered: {state.get('answer')}" if answered else "answered nothing",),
        )
    metrics: dict[str, float | None] = {"recorded": float(finding is not None)}
    metrics.update(dict.fromkeys(CHECKS))
    problems: list[str] = []
    if finding is None:
        problems.append("recorded no Finding")
    if "cause" in expected:
        metrics["cause_correct"] = float(
            finding is not None and finding["cause"] == expected["cause"]
        )
    if "critical_steps" in expected:
        metrics["step_correct"] = float(
            finding is not None and finding["critical_step"] in expected["critical_steps"]
        )
    if expected.get("terms"):
        text = " ".join([finding["summary"], *finding["evidence"]]).lower() if finding else ""
        metrics["cause_named"] = float(any(term.lower() in text for term in expected["terms"]))
    for name in CHECKS:
        if metrics[name] == 0.0:
            problems.append(f"{name} failed; the answer key holds {expected}")
    passed = all(metrics[name] in (1.0, None) for name in ("recorded", *CHECKS))
    evidence = (
        f"recorded {finding['cause']} ({finding['status']}) at step "
        f"{finding['critical_step']}: {finding['summary']}"
        if finding
        else "recorded nothing"
    )
    return VerifierOutput(
        score=float(passed),
        metrics=metrics,
        evidence=(evidence,),
        feedback="; ".join(problems) or "Every check passed.",
    )
