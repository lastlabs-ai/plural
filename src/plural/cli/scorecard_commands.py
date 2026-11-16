"""``plural scorecard``: label Trials, calibrate the graders, decide, and rescore.

The standard ``init|validate|push|pull|show|list|delete`` verbs come from
:mod:`plural.cli.resource_commands`; :func:`add_scorecard_commands` adds these.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import typer

from plural.cli.common import (
    JSON_OPTION,
    counted,
    emit,
    handled,
    heading,
    muted,
    note,
    project_studio,
    rows,
    session,
    success,
    workspace,
)
from plural.config import resolve_gateway_url
from plural.model_steps import DEFAULT_MODEL, estimate_usd, model_step
from plural.project import ProjectError, ResourceRef
from plural.project.layout import ENVIRONMENT, SCORECARD
from plural.project.scorecards import (
    calibrate_scorecard,
    import_labels,
    job_trials,
    labels,
    latest_calibration,
    load_scorecard,
    metric_specs,
    pick_for_labeling,
    record_decision,
    render_good,
    rescore_job,
    save_labels,
)
from plural.scorecard_drafting import (
    QUESTIONS,
    analyze,
    compose,
    draft_files,
    environment_facts,
    estimate_prompt_tokens,
    read_sources,
)
from plural.scorecards import Calibration, Decision, Label, Scorecard

_STATUS = {
    "trusted": "✓ trusted",
    "needs_work": "✗ needs work",
    "undefined": "? define it better",
    "not_calibrated": "· not calibrated",
}


def add_scorecard_commands(app: typer.Typer) -> None:
    """Add ``label``, ``calibrate``, ``decide`` and ``rescore`` to ``plural scorecard``."""
    app.command("draft")(draft)
    app.command("label")(label)
    app.command("calibrate")(calibrate)
    app.command("decide")(decide)
    app.command("rescore")(rescore)


@handled
def draft(
    name: str = typer.Argument(help="The Scorecard to draft, by name."),
    docs: list[Path] = typer.Option(
        [], "--docs", help="Documents, or a folder of them: text, Markdown, or PDF. Repeatable."
    ),
    traces: Path | None = typer.Option(
        None, "--traces", help="Recorded conversations of the work, as JSONL. Up to 50 are read."
    ),
    workflow: str | None = typer.Option(
        None, "--workflow", help="The work, in a sentence. Default: the project's description."
    ),
    environment: str | None = typer.Option(
        None, "--environment", help="The Environment whose State the checks read."
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="The model that drafts."),
    budget_usd: float = typer.Option(
        0.50, "--budget-usd", min=0, help="The most the draft may spend on model calls."
    ),
    no_input: bool = typer.Option(
        False,
        "--no-input",
        help="Accept the suggested answers and list the questions in questions.md.",
    ),
    force: bool = typer.Option(False, "--force", help="Replace files a draft wrote before."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Draft a Scorecard from your documents and traces, after five questions.

    The model reads the documents and traces, finds what matters and where
    sources disagree, and suggests an answer to each question. It then writes
    scorecard.yaml, GOOD.md, questions.md, and a Verifier for each kind of
    check the new metrics need: code checks with PLURAL-TODO, a model judge,
    or a person's review. It calls models with a key minted for this draft
    alone and revoked when it ends.
    """
    space = workspace()
    root = space.project.root
    folder = root / "scorecards" / name
    if folder.exists() and not force:
        raise ProjectError(
            f"scorecards/{name} already exists.\n"
            f"Next: pass --force to replace it, or draft another name."
        )
    sources = read_sources(docs, traces)

    def say(line: str) -> None:
        typer.echo(line, err=as_json)

    say(
        f"Reading {counted(len(sources.documents), 'document')} and "
        f"{counted(len(sources.traces), 'trace')}…"
    )
    for line in sources.skipped:
        say(muted(f"  left out {line}"))
    estimate = estimate_usd(
        model,
        prompt_tokens=estimate_prompt_tokens(sources) + 6_000,
        completion_tokens=12_000,
        catalog=space.catalog,
    )
    say(
        f"Estimated cost with {model}: "
        + (f"${estimate:.3f}" if estimate is not None else "not priced in the catalog")
        + f" (budget ${budget_usd:.2f})."
    )
    if estimate is not None and estimate > budget_usd:
        raise ProjectError(
            f"The draft could cost ${estimate:.3f}, over the ${budget_usd:.2f} budget.\n"
            "Next: pass a larger --budget-usd, or fewer documents and traces."
        )
    facts = _environment_facts(space, environment)
    work = workflow or space.project.manifest.description or name.replace("-", " ")
    current = session()
    studio, _binding = project_studio(space, current)
    gateway = resolve_gateway_url(None, os.environ)
    accepted = no_input or as_json
    with model_step(
        "scorecard-draft",
        model=model,
        budget_usd=budget_usd,
        studio=studio,
        gateway_url=gateway,
        catalog=space.catalog,
    ) as step:
        analysis = analyze(step, work, sources)
        answers = dict(analysis.suggestions)
        if not accepted:
            typer.echo("")
            typer.echo("A few questions so the Scorecard reflects how your team judges this work.")
            typer.echo("(Enter to accept the suggestion in brackets.)")
            for index, (key, question) in enumerate(QUESTIONS, start=1):
                answers[key] = typer.prompt(
                    f"{index}. {question}", default=answers.get(key, "") or ""
                )
        drafted = compose(step, work, analysis, answers, facts=facts, existing=metric_specs(space))
        spent = step.spent_usd
    try:
        files = draft_files(name, drafted, analysis, answers, judge_model=model, accepted=accepted)
    except ValueError as exc:
        raise ProjectError(
            f"The model's draft did not make a valid Scorecard (${spent:.3f} spent): {exc}\n"
            "Next: run plural scorecard draft again, or write scorecard.yaml by hand."
        ) from exc
    for relative_path, content in files.items():
        path = root / relative_path
        if path.exists() and not force and not relative_path.startswith(f"scorecards/{name}/"):
            raise ProjectError(
                f"{relative_path} already exists.\nNext: pass --force to replace it."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    space = workspace()
    card = load_scorecard(space, name)
    verifiers = sorted({path.split("/")[1] for path in files if path.startswith("verifiers/")})
    counts = {
        "gates": len(card.gates),
        "objectives": len(card.objectives),
        "guardrails": len(card.metrics) - len(card.gates) - len(card.objectives),
    }
    payload = {
        "scorecard": card.reference,
        "files": sorted(files),
        "metrics": counts,
        "verifiers": verifiers,
        "open_questions": len(analysis.contradictions),
        "accepted_suggestions": accepted,
        "model": model,
        "estimated_usd": estimate,
        "spent_usd": round(spent, 4),
    }

    def text() -> None:
        typer.echo("")
        typer.echo(f"Wrote scorecards/{name}/")
        typer.echo(
            f"  scorecard.yaml   {counted(len(card.metrics), 'metric')}: "
            f"{counted(counts['gates'], 'gate')}, {counted(counts['objectives'], 'objective')}, "
            f"{counted(counts['guardrails'], 'guardrail')}"
        )
        typer.echo("  GOOD.md          what good means, in your words")
        typer.echo(
            f"  questions.md     {counted(len(analysis.contradictions), 'thing')} the "
            "documents disagree on" + (", and the suggested answers to confirm" if accepted else "")
        )
        if verifiers:
            typer.echo(f"Drafted {counted(len(verifiers), 'Verifier')}: {', '.join(verifiers)}")
        typer.echo(f"Spent ${spent:.4f} with {model}.")
        typer.echo("")
        typer.echo("Next: label 20 real examples so we can check the graders against your team:")
        typer.echo(f"  plural scorecard label {name} --job JOB")

    emit(payload, as_json=as_json, text=text)


def _environment_facts(space: Any, environment: str | None) -> str:
    names = space.project.names(ENVIRONMENT)
    if environment is None and len(names) != 1:
        return ""
    chosen = environment or names[0]
    try:
        return environment_facts(space.get("environment", chosen))
    except (ProjectError, ValueError) as exc:
        raise ProjectError(
            f"Environment {chosen} does not load: {exc}\nNext: plural env validate {chosen}"
        ) from exc


@handled
def label(
    name: str = typer.Argument(help="The Scorecard, by name."),
    job: str = typer.Option(..., "--job", help="The local Job whose Trials to label."),
    import_file: Path | None = typer.Option(
        None,
        "--import",
        help="Labels to attach, as JSONL keyed by task and agent, instead of asking.",
    ),
    labeler: str | None = typer.Option(
        None, "--labeler", help="Who is labeling. Asked for when left out."
    ),
    count: int = typer.Option(20, "--count", min=1, help="How many Trials to label."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Label Trials against the Scorecard, so calibrate can check the graders.

    Asks about each binary and rating metric (y/n/?, or a number), then the
    overall verdict (good/bad/unsure). Picks half the Trials the graders passed
    and half they failed, one per Task first. Labels never change a score.
    """
    space = workspace()
    scorecard = load_scorecard(space, name)
    if import_file is not None:
        imported_labels, skipped = import_labels(space, name, import_file, job)
        labelers = sorted({item.labeler for item in imported_labels})
        trial_count = len({item.trial_id for item in imported_labels})
        payload = {
            "scorecard": scorecard.reference,
            "job_id": job,
            "saved": len(imported_labels),
            "trials": trial_count,
            "labelers": labelers,
            "skipped": skipped,
        }

        def imported() -> None:
            success(
                f"Saved {counted(len(imported_labels), 'label')} on "
                f"{counted(trial_count, 'Trial')} from {counted(len(labelers), 'labeler')}."
            )
            for line in skipped:
                note(f"Skipped {line}.")
            typer.echo(f"Next: plural scorecard calibrate {name}")

        emit(payload, as_json=as_json, text=imported)
        return
    if as_json:
        raise ProjectError(
            "Labeling asks questions, so it has no --json form.\n"
            f"Next: plural scorecard label {name} --job {job} --import FILE --json"
        )
    who = labeler or typer.prompt("Your name, as a labeler")
    trials = job_trials(space, job)
    done = {item.trial_id for item in labels(space, name) if item.labeler == who}
    chosen = pick_for_labeling(trials, count=count, labeled=done)
    if not chosen:
        typer.echo(f"Every Trial of Job {job} is labeled by {who}.")
        typer.echo(f"Next: plural scorecard calibrate {name}")
        return
    specs = metric_specs(space)
    asked = [
        item
        for item in scorecard.metrics
        if (spec := specs.get(item.name)) is not None and spec.kind in {"binary", "rating"}
    ]
    saved = 0
    for index, trial in enumerate(chosen, start=1):
        typer.echo("")
        heading(f"Labeling {index} of {len(chosen)} · Trial {trial['trial_id']} ({trial['task']})")
        typer.echo(muted(f"  Agent {trial['agent']}, status {trial['status']}"))
        values: dict[str, Any] = {}
        reasons: dict[str, str] = {}
        for item in asked:
            spec = specs[item.name]
            hint = (
                "[y/n/?]"
                if spec.kind == "binary"
                else f"[{spec.range[0]:g}-{spec.range[1]:g} or ?]"
                if spec.range
                else "[number or ?]"
            )
            answer = typer.prompt(f"  {item.name:<20} {hint}", default="?").strip()
            values[item.name] = answer if spec.kind == "binary" or answer == "?" else float(answer)
            if answer.lower() in {"n", "no"}:
                why = typer.prompt("    why", default="", show_default=False)
                if why:
                    reasons[item.name] = why
        verdict = typer.prompt("  Overall: good / bad / unsure?", default="unsure").strip()
        verdict = {"g": "good", "b": "bad", "u": "unsure"}.get(verdict, verdict)
        reason = typer.prompt("  Why (optional)", default="", show_default=False)
        save_labels(
            space,
            name,
            [
                Label(
                    scorecard=name,
                    trial_id=trial["trial_id"],
                    labeler=who,
                    values=values,
                    verdict=verdict,
                    reason=reason,
                    reasons=reasons,
                    task=trial["task"],
                )
            ],
        )
        saved += 1
    success(f"Saved {counted(saved, 'label')} from {who}.")
    typer.echo(f"Next: plural scorecard calibrate {name}")


@handled
def calibrate(
    name: str = typer.Argument(help="The Scorecard, by name."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Check the graders against your team's labels, metric by metric.

    Team agreement is Cohen's kappa (Fleiss' for three or more labelers) on
    binary and rating metrics and Spearman's rho on numbers; the grader is
    compared with the labelers' consensus. Saved for the Scorecard version.
    """
    space = workspace()
    result = calibrate_scorecard(space, name)

    def text() -> None:
        heading(
            f"Graders vs your team ({counted(result.labels, 'labeled example')}, "
            f"{counted(len(result.labelers), 'labeler')})"
        )
        typer.echo("")
        rows(
            (
                (
                    item.metric,
                    _agreement(item.team_measure, item.team_agreement),
                    _agreement(item.grader_measure, item.grader_agreement),
                    _STATUS[item.status],
                )
                for item in result.metrics
                if item.labeled
            ),
            ("Metric", "Team agrees with itself", "Grader agrees with team", "Status"),
        )
        unlabeled = [item.metric for item in result.metrics if not item.labeled]
        if unlabeled:
            typer.echo(muted(f"No labels yet on {', '.join(unlabeled)}."))
        for item in result.metrics:
            if item.status in {"needs_work", "undefined"} or (
                item.labeled and item.status == "not_calibrated"
            ):
                typer.echo(muted(f"{item.metric}: {item.note}"))
        if result.needs_decision:
            typer.echo("")
            typer.echo(
                f"{counted(len(result.needs_decision), 'example')} "
                f"need{'s' if len(result.needs_decision) == 1 else ''} a decision:"
            )
            for case in result.needs_decision:
                why = "labelers disagree" if case.kind == "labelers_split" else "grader disagrees"
                typer.echo(f"  {case.trial_id}  {case.task or ''}  {case.metric}: {why}")
            typer.echo(f"Open them: plural scorecard decide {name}")
        typer.echo(f"Next: {_next(name, result)}")

    emit(result, as_json=as_json, text=text)


def _agreement(measure: str | None, value: float | None) -> str:
    if value is None:
        return "-"
    symbol = {"cohen_kappa": "κ", "fleiss_kappa": "κ", "spearman": "ρ"}.get(measure or "", "")
    return f"{symbol} {value:.2f}"


def _next(name: str, result: Calibration) -> str:
    broken = [item.metric for item in result.metrics if item.status == "needs_work"]
    if broken:
        return f"fix the {', '.join(broken)} check, then calibrate again."
    vague = [item.metric for item in result.metrics if item.status == "undefined"]
    if vague:
        return f"define {', '.join(vague)} better in scorecard.yaml, then label again."
    if result.needs_decision:
        return f"plural scorecard decide {name}"
    short = [item.metric for item in result.metrics if item.status == "not_calibrated"]
    if short:
        return f"plural scorecard label {name} --job JOB, to label more examples."
    return f"plural scorecard push {name}"


@handled
def decide(
    name: str = typer.Argument(help="The Scorecard, by name."),
    question: str | None = typer.Option(
        None, "--question", help="Record one decision without the queue: the question."
    ),
    answer: str | None = typer.Option(None, "--answer", help="The ruling, with --question."),
    metric: str | None = typer.Option(None, "--metric", help="The metric the decision is about."),
    trial: str | None = typer.Option(None, "--trial", help="The example that raised it."),
    decided_by: str = typer.Option("", "--by", help="Who decided."),
    description: str | None = typer.Option(
        None, "--description", help="With --metric: the metric's new description."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Settle the examples calibrate flagged, and record each ruling as a decision.

    Each decision is appended to ``scorecard.yaml`` and bumps its patch version;
    ``GOOD.md`` is rewritten to match. With ``--question`` and ``--answer`` it
    records one decision without asking.
    """
    space = workspace()
    scorecard = load_scorecard(space, name)
    decisions: list[Decision] = []
    if question is not None or answer is not None:
        if not question or not answer:
            raise ProjectError(
                "--question and --answer go together.\n"
                f'Next: plural scorecard decide {name} --question "..." --answer "..."'
            )
        decisions.append(
            Decision(
                question=question,
                answer=answer,
                decided_by=decided_by,
                metric=metric,
                trial_id=trial,
            )
        )
    else:
        if as_json:
            calibration = latest_calibration(space, name)
            emit(
                {
                    "scorecard": scorecard.reference,
                    "needs_decision": [
                        item.model_dump(mode="json")
                        for item in (calibration.needs_decision if calibration else ())
                    ],
                },
                as_json=True,
            )
            return
        decisions = _walk_queue(space, name, decided_by)
        if not decisions:
            return
    for item in decisions:
        scorecard = record_decision(
            space, name, item, description=description if item is decisions[-1] else None
        )
    _write_good(space, scorecard)

    def text() -> None:
        success(
            f"Recorded {counted(len(decisions), 'decision')}; {name} is now {scorecard.version}."
        )
        typer.echo(f"Next: plural scorecard calibrate {name}, then plural scorecard push {name}")

    emit(
        {
            "scorecard": scorecard.reference,
            "decisions": [item.model_dump(mode="json") for item in decisions],
        },
        as_json=as_json,
        text=text,
    )


def _walk_queue(space: Any, name: str, decided_by: str) -> list[Decision]:
    calibration = latest_calibration(space, name)
    if calibration is None:
        raise ProjectError(
            f"Scorecard {name} has not been calibrated at this version.\n"
            f"Next: plural scorecard calibrate {name}"
        )
    if not calibration.needs_decision:
        typer.echo("Nothing needs a decision.")
        typer.echo(f"Next: plural scorecard push {name}")
        return []
    who = decided_by or typer.prompt("Who decides")
    decisions = []
    for case in calibration.needs_decision:
        typer.echo("")
        heading(f"Trial {case.trial_id} ({case.task or 'unknown Task'}) · {case.metric}")
        for labeler, value in case.labels.items():
            reason = case.reasons.get(labeler, "")
            typer.echo(f"  {labeler:<14} {value:g}" + (f"  {muted(reason)}" if reason else ""))
        if case.grader is not None:
            typer.echo(f"  {'grader':<14} {case.grader:g}")
        ruling = typer.prompt("  Ruling (Enter to skip)", default="", show_default=False)
        if not ruling:
            continue
        decisions.append(
            Decision(
                question=f"How should {case.metric} be judged on {case.task or case.trial_id}?",
                answer=ruling,
                decided_by=who,
                date=date.today().isoformat(),
                metric=case.metric,
                trial_id=case.trial_id,
            )
        )
    return decisions


def _write_good(space: Any, scorecard: Scorecard) -> None:
    path = space.project.resource_dir(ResourceRef(SCORECARD.name, scorecard.name)) / "GOOD.md"
    path.write_text(render_good(scorecard), encoding="utf-8")


@handled
def rescore(
    name: str = typer.Argument(help="The Scorecard, by name."),
    job: str = typer.Option(..., "--job", help="The local Job whose stored metrics to rescore."),
    target: list[str] = typer.Option(
        [],
        "--target",
        help="Try a different target without saving it, as METRIC='>= 0.8'. Repeatable.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Apply the Scorecard's gates and targets to a Job's stored metrics, with no rerun.

    Use it after the Scorecard's version changes, or with ``--target`` to see
    what a different target would do. When a Verifier changed, use
    ``plural verifier apply`` instead.
    """
    targets: dict[str, str] = {}
    for item in target:
        metric, sep, value = item.partition("=")
        if not sep or not metric.strip() or not value.strip():
            raise ProjectError(
                f"--target {item!r} must be METRIC=TARGET.\n"
                'Next: pass --target "margin_usd=>= 200".'
            )
        targets[metric.strip()] = value.strip()
    result = rescore_job(workspace(), name, job, targets=targets)

    def text() -> None:
        heading(f"{result['scorecard']} on Job {job}" + (" (with new targets)" if targets else ""))
        rows(
            (
                (
                    agent,
                    _rate(rate),
                    _rate(result["recorded"].get(agent)),
                )
                for agent, rate in result["pass_rate"].items()
            ),
            ("Agent", "Pass rate now", "Recorded when run"),
        )
        typer.echo(f"Next: plural scorecard push {name}, so hosted results use it.")

    emit(result, as_json=as_json, text=text)


def _rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


__all__ = ["add_scorecard_commands", "calibrate", "decide", "draft", "label", "rescore"]
