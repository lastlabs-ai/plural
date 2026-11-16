"""``plural task generate`` and ``plural task review``: draft Tasks, then review them."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import typer

from plural.cli.common import (
    JSON_OPTION,
    counted,
    emit,
    handled,
    muted,
    project_studio,
    session,
    success,
    workspace,
)
from plural.config import resolve_gateway_url
from plural.model_steps import DEFAULT_MODEL, estimate_usd, model_step
from plural.project import ProjectError
from plural.project.layout import BENCHMARK, ENVIRONMENT, SCORECARD, TASK
from plural.project.scorecards import load_scorecard
from plural.project.task_generation import (
    BATCH,
    DRAFTS,
    approve,
    draft_names,
    existing_examples,
    generate,
    next_names,
    read_draft,
    reject,
    write_draft,
)
from plural.scorecard_drafting import read_sources

__all__ = ["add_task_generation_commands"]


def add_task_generation_commands(app: typer.Typer) -> None:
    """Register ``generate`` and ``review`` on the ``plural task`` group."""
    app.command("generate")(generate_tasks)
    app.command("review")(review_tasks)


def _only(space: Any, kind: Any, given: str | None, flag: str) -> str:
    if given is not None:
        return given
    names = space.project.names(kind)
    if len(names) == 1:
        return str(names[0])
    raise ProjectError(
        f"Pick one with {flag}: this project has {counted(len(names), kind.label)}.\n"
        f"Next: plural task generate {flag} NAME"
    )


def _categories(space: Any, benchmark: str | None) -> dict[str, list[str]]:
    names = [benchmark] if benchmark else space.project.names(BENCHMARK)
    found: dict[str, list[str]] = {}
    for name in names:
        try:
            loaded = space.get("benchmark", name)
        except ProjectError:
            continue
        for category in loaded.categories:
            found.setdefault(category.id, []).extend(category.tasks)
    return found


@handled
def generate_tasks(
    environment: str | None = typer.Option(
        None, "--environment", "-e", help="The Environment the Tasks run in."
    ),
    scorecard: str | None = typer.Option(
        None, "--scorecard", help="The Scorecard whose metrics the Tasks should exercise."
    ),
    count: int = typer.Option(20, "--count", min=1, max=100, help="Tasks to draft."),
    benchmark: str | None = typer.Option(
        None, "--benchmark", "-b", help="Take categories from this Benchmark."
    ),
    traces: Path | None = typer.Option(
        None, "--traces", help="Recorded conversations of real work, as JSONL."
    ),
    prefix: str | None = typer.Option(
        None, "--prefix", help="Name prefix. Default: the one the project's Tasks share."
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="The model that drafts."),
    budget_usd: float = typer.Option(
        0.50, "--budget-usd", min=0, help="The most the drafts may spend on model calls."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Draft Tasks from the Environment, a Scorecard, and the Tasks you have.

    Each draft's starting state is checked against the Environment's State;
    exact and near-duplicates are dropped. Drafts go to tasks/_drafts/, where
    no Benchmark runs them and nothing pushes them, until you approve them
    with ``plural task review``.
    """
    space = workspace()
    env_name = _only(space, ENVIRONMENT, environment, "--environment")
    card_name = scorecard
    if card_name is None and len(space.project.names(SCORECARD)) == 1:
        card_name = space.project.names(SCORECARD)[0]
    card = load_scorecard(space, card_name) if card_name else None
    env = space.get("environment", env_name)
    categories = _categories(space, benchmark)
    examples = existing_examples(space.project, categories)
    sources = read_sources((), traces)
    trace_text = "\n\n".join(item.text for item in sources.traces[:20])
    verifiers = _verifiers(space, examples)

    def say(line: str) -> None:
        typer.echo(line, err=as_json)

    calls = -(-count // BATCH)
    estimate = estimate_usd(
        model,
        prompt_tokens=calls * (6_000 + len(trace_text) // 4) + 2_000,
        completion_tokens=calls * (1_000 + 700 * BATCH) + 1_000,
        catalog=space.catalog,
    )
    resources = len(getattr(env.definition(), "resources", ()) or ())
    say(
        f"Drafting {count} Tasks from the App's actions, {counted(resources, 'resource')}, "
        + (f"the Scorecard {card.name} " if card else "")
        + f"and {counted(len(sources.traces), 'trace')}…"
    )
    say(
        f"Estimated cost with {model}: "
        + (f"${estimate:.3f}" if estimate is not None else "not priced in the catalog")
        + f" (budget ${budget_usd:.2f})."
    )
    if estimate is not None and estimate > budget_usd:
        raise ProjectError(
            f"Drafting could cost ${estimate:.3f}, over the ${budget_usd:.2f} budget.\n"
            "Next: pass a larger --budget-usd, or a smaller --count."
        )
    studio, _binding = project_studio(space, session())
    with model_step(
        "task-generate",
        model=model,
        budget_usd=budget_usd,
        studio=studio,
        gateway_url=resolve_gateway_url(None, os.environ),
        catalog=space.catalog,
    ) as step:
        result = generate(
            step,
            environment=env,
            count=count,
            scorecard=card,
            examples=examples,
            categories=sorted(categories),
            traces=trace_text,
        )
        spent = step.spent_usd
    names = next_names(space.project, len(result.drafts), prefix)
    for name, draft in zip(names, result.drafts, strict=True):
        write_draft(space.project, name, draft, environment=env_name, verifiers=verifiers)
    coverage = result.coverage()
    payload = {
        "drafted": names,
        "invalid": [{"instructions": d.instructions[:200], "reason": r} for d, r in result.invalid],
        "duplicates": len(result.duplicates),
        "coverage": coverage,
        "model": model,
        "estimated_usd": estimate,
        "spent_usd": round(spent, 4),
    }

    def text() -> None:
        dropped = []
        if result.duplicates:
            dropped.append(f"{len(result.duplicates)} dropped (near-duplicates)")
        if result.invalid:
            dropped.append(f"{len(result.invalid)} dropped (state doesn't fit the Environment)")
        typer.echo("  " + " · ".join([f"{len(names)} drafted", *dropped]))
        if coverage:
            typer.echo("  Coverage: " + " · ".join(f"{k} {v}" for k, v in coverage.items()))
        for draft, reason in result.invalid[:3]:
            typer.echo(muted(f"  left out: {draft.instructions[:60]!r}: {reason}"))
        typer.echo(f"Spent ${spent:.4f} with {model}.")
        typer.echo(f"Drafts are in tasks/{DRAFTS}/. Review them:")
        typer.echo("  plural task review          # approve, edit, or reject one at a time")

    emit(payload, as_json=as_json, text=text)


def _verifiers(space: Any, examples: list[dict[str, Any]]) -> list[str]:
    for example in examples:
        try:
            task = space.get("task", example["name"])
        except ProjectError:
            continue
        return [item.verifier.name for item in task.verifiers]
    return []


@handled
def review_tasks(
    name: str | None = typer.Argument(None, help="One draft to act on. Default: each in turn."),
    approve_draft: bool = typer.Option(False, "--approve", help="Approve NAME."),
    reject_draft: bool = typer.Option(False, "--reject", help="Reject NAME."),
    benchmark: str | None = typer.Option(
        None, "--benchmark", "-b", help="Add approved Tasks to this Benchmark."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Approve, edit, or reject drafted Tasks, one at a time.

    Approving moves the draft to tasks/NAME/ (and into --benchmark, in its
    drafted category). Editing opens it in $EDITOR. With --json, or NAME with
    --approve or --reject, nothing is asked.
    """
    space = workspace()
    project = space.project
    if approve_draft and reject_draft:
        raise ProjectError("Pass --approve or --reject, not both.\nNext: pick one.")
    if name is not None and (approve_draft or reject_draft):
        if approve_draft:
            target = approve(project, name, benchmark=benchmark)
            _check(space, name)
            payload: dict[str, Any] = {"approved": [name], "path": str(target)}
        else:
            reject(project, name)
            payload = {"rejected": [name]}
        emit(
            payload,
            as_json=as_json,
            text=lambda: success(
                f"{'Approved' if approve_draft else 'Rejected'} {name}."
                + (f" Next: plural task push {name}" if approve_draft else "")
            ),
        )
        return
    pending = [name] if name else draft_names(project)
    if as_json:
        emit({"drafts": [_summary(project, item) for item in pending]}, as_json=True)
        return
    if not pending:
        typer.echo("No drafts to review.\nNext: plural task generate")
        return
    approved: list[str] = []
    rejected: list[str] = []
    for index, item in enumerate(pending, start=1):
        while True:
            _show(project, item, index, len(pending))
            choice = (
                typer.prompt("[a]pprove, [e]dit, [r]eject, [s]kip, [q]uit", default="s")
                .strip()[:1]
                .lower()
            )
            if choice == "e":
                editor = os.environ.get("EDITOR", "vi")
                folder = project.root / TASK.directory / DRAFTS / item
                subprocess.run([editor, str(folder / "task.yaml"), str(folder / "instruction.md")])
                continue
            break
        if choice == "q":
            break
        if choice == "a":
            approve(project, item, benchmark=benchmark)
            _check(space, item)
            approved.append(item)
        elif choice == "r":
            reject(project, item)
            rejected.append(item)
    typer.echo(
        f"{counted(len(approved), 'Task')} approved, {len(rejected)} rejected, "
        f"{len(draft_names(project))} drafts left."
    )
    if approved:
        typer.echo(f"Next: plural task push {' '.join(approved)}")


def _check(space: Any, name: str) -> None:
    try:
        workspace().get("task", name)
    except ProjectError as exc:
        raise ProjectError(
            f"Approved {name}, but it does not load as a Task: {exc}\n"
            f"Next: fix tasks/{name}/task.yaml, then plural task validate {name}"
        ) from exc


def _summary(project: Any, name: str) -> dict[str, Any]:
    manifest = read_draft(project, name)
    return {
        "name": name,
        "instructions": manifest.get("instructions_text", ""),
        "initial_state": manifest.get("initial_state") or {},
        "expected": manifest.get("expected"),
        **(manifest.get("draft") or {}),
    }


def _show(project: Any, name: str, index: int, total: int) -> None:
    item = _summary(project, name)
    typer.echo("")
    typer.echo(f"── {name} ({index} of {total}) · {item.get('category') or 'no category'}")
    typer.echo(str(item["instructions"]).strip())
    if item["initial_state"]:
        typer.echo(muted("state: " + json.dumps(item["initial_state"])[:400]))
    typer.echo(muted("expected: " + json.dumps(item["expected"])))
    if item.get("rationale"):
        typer.echo(muted("why: " + str(item["rationale"])))
