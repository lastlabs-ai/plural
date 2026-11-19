"""inspector-bench: plant known faults, keep the Trials they break, and score the Inspector.

A healthy Agent runs the quoting Tasks. Each fault then changes one thing, the
Agent (its instructions, a tool's description, which tools it sees, its model, or
how much it must read) or the project (its Verifier, an answer key, or a Task's
request), and the same Tasks run again. A Trial joins the bench only when the
healthy Agent passed its Task and the faulty run failed it, so its cause is
known. A fault with levels, such as padding, escalates until it breaks a Task or
runs out of levels. A fault that broke nothing is kept out of the bench and
reported in ``bench.json``, as is every cause the faults claim that has no case.
Each case becomes one Inspector Task whose answer key is the planted cause; the
Inspector's accuracy is the pass rate of ``finding-check`` over them.

Agents get neutral names (``agent-3``), so a name never gives the fault away.

Run it as ``python -m plural.inspector.faults build SOURCE OUT``, then
``python -m plural.inspector.faults run OUT``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from plural.inspector.evidence import JobEvidence, TrialEvidence
from plural.inspector.run import (
    TEMPLATE,
    Depth,
    fork_environ,
    fork_key,
    instructions_for,
    write_benchmark,
    write_task,
)
from plural.project.layout import Project
from plural.project.resources import Workspace
from plural.project.runs import RunRequest, local_job_spec, plan_run, run_local
from plural.studio import Studio

BENCH = "inspector-bench"
BENCH_FILE = "bench.json"
RESULTS_FILE = "results.json"
HEALTHY = "agent-0"
IGNORED = shutil.ignore_patterns(".plural", "__pycache__", "plural.lock", "traps.py", ".venv")

ROUNDING = (
    "Pricing: round the price per ton to the nearest whole dollar, then multiply by the tons "
    "for the total."
)
EXACT = (
    "Pricing: quote today's price per ton exactly as looked up, and multiply it by the tons "
    "for the total, rounded to the cent."
)
SUPPLY = "the mill can't supply the order."
DATES = (
    "the mill can't supply the order. A requested date the mill can't meet is no reason to "
    "hand off: quote the earliest date it can."
)
SCHEDULE = (
    "The earliest delivery date the mill can meet for an order of this many short tons. "
    "Check it before every quote and never promise an earlier date: quote the customer's "
    "date when the mill can meet it, and this one otherwise."
)
WEAK_MODELS = ("anthropic/claude-haiku-4-5", "google/gemini-3.7-flash")
"""The weaker gateway models the model fault tries, in turn, until one breaks a Task."""
PADDING_LINES = (1_200, 6_000, 24_000)
"""How many padding lines the context fault tries, in turn: about 40k, 200k, and 800k tokens."""
PADDING_LINE = (
    "Reference: mill {n} keeps archived order ledgers, shift rosters, safety bulletins, "
    "and maintenance logs for the {n}th rolling line; none of them bear on quoting."
)


@dataclass(frozen=True)
class Fault:
    """One planted fault.

    Attributes:
        name: Its name, kept out of everything the Inspector reads.
        cause: The cause dimension a correct Finding names.
        description: What was planted.
        categories: The quoting categories it is run on.
        terms: Words, one of which a correct Finding's summary or evidence uses.
        agent: Changes the healthy Agent's manifest, given the level;
            ``None`` for a project fault.
        project: Changes a copy of the project; ``None`` for an Agent fault.
        step_known: Whether the critical step is the Agent's answer. A grader
            or answer-key fault breaks no step, so any step is accepted.
        levels: The strengths an Agent fault tries, in turn, until one breaks a
            Task the healthy Agent passed.
    """

    name: str
    cause: str
    description: str
    categories: tuple[str, ...]
    terms: tuple[str, ...]
    agent: Callable[[dict[str, Any], Any], None] | None = None
    project: Callable[[Path], None] | None = None
    step_known: bool = True
    levels: tuple[Any, ...] = (None,)


@dataclass
class Case:
    """One bench Trial: a fault's failure, with what the healthy Agent did."""

    fault: str
    project: str
    job_id: str
    trial_id: str
    task: str
    healthy_trial_id: str
    expected: dict[str, Any] = field(default_factory=dict)


def healthy_agent(source: Mapping[str, Any]) -> dict[str, Any]:
    """quote-bot without its weaknesses: exact pricing, a clear schedule tool, and rush dates.

    Returns:
        The healthy Agent's manifest.
    """
    payload = {key: value for key, value in source.items() if key != "tool_overrides"}
    payload["name"] = HEALTHY
    payload["version"] = "1.0.0"
    instructions = str(source["instructions"])
    if ROUNDING not in instructions or SUPPLY not in instructions:
        raise ValueError("quote-bot's instructions changed; update the fault injector.")
    payload["instructions"] = instructions.replace(ROUNDING, EXACT).replace(SUPPLY, DATES)
    payload["tool_overrides"] = {"check_schedule": SCHEDULE}
    return payload


def _hide_schedule(agent: dict[str, Any], _level: Any = None) -> None:
    agent["tool_overrides"] = {"check_schedule": {"hidden": True}}


def _vague_schedule(agent: dict[str, Any], _level: Any = None) -> None:
    agent["tool_overrides"] = {"check_schedule": "Optional: view mill bookings."}


def _rounding(agent: dict[str, Any], _level: Any = None) -> None:
    agent["instructions"] = str(agent["instructions"]).replace(EXACT, ROUNDING)


def _requested_date(agent: dict[str, Any], _level: Any = None) -> None:
    agent["instructions"] = (
        str(agent["instructions"]).rstrip()
        + " Always promise the delivery date the customer asked for; customers walk away "
        "from any other date.\n"
    )


def _never_handoff(agent: dict[str, Any], _level: Any = None) -> None:
    agent["instructions"] = (
        str(agent["instructions"]).rstrip()
        + " The sales team is fully booked this week, so never hand off: always send a "
        "quote, filling in whatever the customer left out.\n"
    )


def _padding(agent: dict[str, Any], lines: int) -> None:
    filler = "\n".join(PADDING_LINE.format(n=n) for n in range(1, lines + 1))
    agent["instructions"] = filler + "\n\n" + str(agent["instructions"])


def _weaker_model(agent: dict[str, Any], model: str) -> None:
    agent["model"] = model


def _list_price_grader(root: Path) -> None:
    _replace(
        root / "verifiers" / "quote-check" / "verify.py",
        'given = state["prices_given"].get(grade)',
        'given = state["price_book"].get(grade)',
    )


def _doubled_answer_key(root: Path) -> None:
    for path in sorted((root / "tasks").glob("*/task.yaml")):
        text = path.read_text("utf-8")
        match = re.search(r"\n  tons: ([0-9.]+)\n", text)
        if match and "decision: quote" in text:
            doubled = f"{float(match.group(1)) * 2:g}"
            path.write_text(text.replace(match.group(0), f"\n  tons: {doubled}\n"), "utf-8")


def _missing_quantity(root: Path) -> None:
    for path in sorted((root / "tasks").glob("*/instruction.md")):
        text = path.read_text("utf-8")
        path.write_text(re.sub(r"\b[0-9][0-9,.]* short tons of ", "some ", text), "utf-8")


QUOTING_FAULTS = (
    Fault(
        "hidden-schedule",
        "tools",
        "check_schedule is hidden from the Agent",
        ("rush",),
        ("check_schedule", "schedule"),
        agent=_hide_schedule,
    ),
    Fault(
        "vague-schedule",
        "tools",
        "check_schedule is described as optional",
        ("rush",),
        ("check_schedule", "schedule", "optional"),
        agent=_vague_schedule,
    ),
    Fault(
        "rounding",
        "instructions",
        "the instructions round the price per ton",
        ("simple", "rush"),
        ("round",),
        agent=_rounding,
    ),
    Fault(
        "requested-date",
        "instructions",
        "the instructions demand the customer's date",
        ("rush",),
        ("asked", "requested", "customer's date", "instruction"),
        agent=_requested_date,
    ),
    Fault(
        "never-handoff",
        "instructions",
        "the instructions forbid handing off",
        ("ambiguous", "out-of-stock"),
        ("hand off", "handoff", "never"),
        agent=_never_handoff,
    ),
    Fault(
        "padding",
        "context",
        "the instructions are buried under irrelevant text",
        ("simple", "rush"),
        ("context", "long", "padding", "irrelevant", "buried"),
        agent=_padding,
        levels=PADDING_LINES,
    ),
    Fault(
        "weaker-model",
        "model",
        "the Agent runs on a weaker model",
        ("simple", "rush", "ambiguous", "out-of-stock"),
        ("model", "weaker", "capab", "stronger"),
        agent=_weaker_model,
        levels=WEAK_MODELS,
    ),
    Fault(
        "list-price-grader",
        "grader",
        "the Verifier checks the quote against the list price",
        ("simple", "rush"),
        ("list price", "price_book", "verifier"),
        project=_list_price_grader,
        step_known=False,
    ),
    Fault(
        "doubled-answer-key",
        "task",
        "the answer key doubles the tons",
        ("simple",),
        ("answer key", "expected", "tons"),
        project=_doubled_answer_key,
        step_known=False,
    ),
    Fault(
        "missing-quantity",
        "task",
        "the request leaves out the quantity the answer key quotes",
        ("simple",),
        ("quantity", "tons", "request"),
        project=_missing_quantity,
    ),
)


def build_bench(
    source: Path,
    out: Path,
    *,
    environ: Mapping[str, str],
    faults: Sequence[Fault] = QUOTING_FAULTS,
    agent: str = "quote-bot",
    per_fault: int = 4,
    max_tasks: int | None = None,
    depth: Depth = "standard",
    budget_usd: float = 0.5,
    concurrency: int = 8,
    log: Callable[[str], None] = print,
) -> list[Case]:
    """Run the healthy and faulty Agents, keep the Trials each fault broke, write the bench.

    ``max_tasks`` caps the Tasks each fault runs on, an even spread of the ones the
    healthy Agent passed, to bound what building the bench costs.

    Returns:
        The bench's cases.
    """
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    clean = out / "subjects" / "clean"
    if not clean.is_dir():
        shutil.copytree(source, clean, ignore=IGNORED)
    manifest = yaml.safe_load((clean / "agents" / agent / "agent.yaml").read_text("utf-8"))
    healthy = healthy_agent(manifest)
    categories = _categories(clean)
    _write_agent(clean, healthy)
    _write_bench(clean, "bench-all", sorted({t for ts in categories.values() for t in ts}))
    log("healthy Agent on every Task")
    baseline = _run(clean, "bench-all", HEALTHY, environ, concurrency)
    passed = {trial.task.task_id: trial for trial in baseline.trials.values() if trial.passed}
    cases: list[Case] = []
    outcomes: dict[str, dict[str, Any]] = {}
    for index, fault in enumerate(faults, start=1):
        tasks = _spread(
            sorted(
                task
                for name in fault.categories
                for task in categories.get(name, ())
                if task in passed
            ),
            max_tasks,
        )
        outcome: dict[str, Any] = {
            "cause": fault.cause,
            "description": fault.description,
            "tasks": len(tasks),
            "tried": [],
            "level": None,
            "broke": 0,
        }
        outcomes[fault.name] = outcome
        if not tasks:
            outcome["note"] = "The healthy Agent passed none of its Tasks."
            continue
        bench = f"bench-{index}"
        if fault.agent is None:
            assert fault.project is not None
            root = out / "subjects" / f"s{index}"
            if not root.is_dir():
                shutil.copytree(clean, root, ignore=IGNORED)
                fault.project(root)
            _write_bench(root, bench, tasks)
            log(f"fault {index} on {len(tasks)} Tasks")
            evidence = _run(root, bench, HEALTHY, environ, concurrency)
            broke = _broke(evidence)
        else:
            for step, level in enumerate(fault.levels, start=1):
                root, name = clean, f"agent-{index}" + (f"-{step}" if len(fault.levels) > 1 else "")
                variant = json.loads(json.dumps(healthy))
                variant["name"] = name
                fault.agent(variant, level)
                _write_agent(root, variant)
                _write_bench(root, bench, tasks)
                log(f"fault {index} level {step} on {len(tasks)} Tasks")
                evidence = _run(root, bench, name, environ, concurrency)
                broke = _broke(evidence)
                outcome["tried"].append({"level": level, "broke": len(broke)})
                if broke:
                    outcome["level"] = level
                    break
        outcome["broke"] = len(broke)
        for trial in broke[:per_fault]:
            cases.append(_case(fault, root, evidence, trial, passed[trial.task.task_id]))
    _write_inspector(out, cases, depth=depth, budget_usd=budget_usd, environ=environ)
    claimed = sorted({fault.cause for fault in faults})
    covered = {case.expected["cause"] for case in cases}
    (out / BENCH_FILE).write_text(
        json.dumps(
            {
                "faults": outcomes,
                "ineffective": sorted(name for name, item in outcomes.items() if not item["broke"]),
                "causes_without_cases": [cause for cause in claimed if cause not in covered],
                "cases": [case.__dict__ for case in cases],
            },
            indent=2,
        )
        + "\n",
        "utf-8",
    )
    return cases


def run_bench(
    out: Path,
    *,
    environ: Mapping[str, str],
    model: str | None = None,
    concurrency: int = 4,
    studio: Studio | None = None,
) -> dict[str, Any]:
    """Run the Inspector on the bench and score it.

    The cases are grouped by the Job they came from, and each group runs with a
    fork key minted for that Job alone; without ``studio`` the forks are off.

    Returns:
        Accuracy overall and per fault, and each check's rate.
    """
    out = out.resolve()
    root = out / "inspector"
    for kind in ("agents", "environments", "verifiers"):
        shutil.rmtree(root / kind, ignore_errors=True)
        shutil.copytree(TEMPLATE / kind, root / kind, ignore=shutil.ignore_patterns("__pycache__"))
    if model is not None:
        path = root / "agents" / "inspector" / "agent.yaml"
        payload = yaml.safe_load(path.read_text("utf-8"))
        payload["model"] = model
        path.write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")
    bench = json.loads((out / BENCH_FILE).read_text("utf-8"))
    by_task = {f"case-{n:02d}": case for n, case in enumerate(bench["cases"], start=1)}
    groups: dict[str, list[str]] = {}
    for name, case in by_task.items():
        groups.setdefault(str(case["job_id"]), []).append(name)
    space = Workspace(Project.at(root))
    rows = []
    jobs = []
    for number, (subject, names) in enumerate(sorted(groups.items()), start=1):
        name = f"{BENCH}-{number}"
        write_benchmark(root, name, names, f"The bench's failed Trials from Job {subject}.")
        with fork_key(studio, subject) as key:
            plan = plan_run(
                space,
                RunRequest(benchmark=name, agent="inspector", concurrency=concurrency),
                environ=fork_environ(environ, key),
            )
            job_id, result = run_local(space, plan, environ=fork_environ(environ, key))
        jobs.append(job_id)
        spec_tasks = {
            item.content_hash: item.task_id for item in local_job_spec(space, job_id).tasks
        }
        for trial in result.trials:
            task = spec_tasks.get(trial.receipt.task_digest, "")
            case = by_task.get(task, {})
            rows.append(
                {
                    "task": task,
                    "fault": case.get("fault"),
                    "cause": (case.get("expected") or {}).get("cause"),
                    "trial_id": trial.receipt.trial_id,
                    "passed": bool(trial.passed),
                    "metrics": dict(trial.metrics),
                    "cost_usd": trial.metrics.get("cost_usd"),
                    "forks": key is not None,
                }
            )
    summary = score_rows(rows)
    summary.update(
        {
            "job_ids": jobs,
            "model": model
            or yaml.safe_load((root / "agents" / "inspector" / "agent.yaml").read_text("utf-8"))[
                "model"
            ],
            "ineffective": bench.get("ineffective", []),
            "causes_without_cases": bench.get("causes_without_cases", []),
            "rows": sorted(rows, key=lambda row: row["task"]),
        }
    )
    (out / RESULTS_FILE).write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    return summary


def score_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Accuracy overall, per fault, per cause, and each check's rate.

    Returns:
        The scores, each with its count.

    Examples:
        >>> rows = [
        ...     {"fault": "a", "cause": "tools", "passed": True, "metrics": {"cause_correct": 1.0}},
        ...     {
        ...         "fault": "b",
        ...         "cause": "grader",
        ...         "passed": False,
        ...         "metrics": {"cause_correct": 0.0},
        ...     },
        ... ]
        >>> score_rows(rows)["accuracy"]
        {'rate': 0.5, 'passed': 1, 'of': 2}
    """

    def rate(items: Sequence[Mapping[str, Any]], key: str | None = None) -> dict[str, Any]:
        if key is None:
            values = [1.0 if item["passed"] else 0.0 for item in items]
        else:
            values = [
                float(item["metrics"][key])
                for item in items
                if item["metrics"].get(key) is not None
            ]
        hits = int(sum(values))
        return {
            "rate": round(hits / len(values), 4) if values else None,
            "passed": hits,
            "of": len(values),
        }

    groups: dict[str, dict[str, list[Mapping[str, Any]]]] = {"fault": {}, "cause": {}}
    for row in rows:
        for key in groups:
            groups[key].setdefault(str(row.get(key)), []).append(row)
    return {
        "accuracy": rate(rows),
        "cause_accuracy": rate(rows, "cause_correct"),
        "step_accuracy": rate(rows, "step_correct"),
        "cause_named": rate(rows, "cause_named"),
        "by_fault": {name: rate(items) for name, items in sorted(groups["fault"].items())},
        "by_cause": {
            name: rate(items, "cause_correct") for name, items in sorted(groups["cause"].items())
        },
    }


def _broke(evidence: JobEvidence) -> list[TrialEvidence]:
    return sorted(
        (trial for trial in evidence.trials.values() if trial.passed is False),
        key=lambda trial: trial.task.task_id,
    )


def _case(
    fault: Fault, root: Path, evidence: JobEvidence, trial: TrialEvidence, healthy: TrialEvidence
) -> Case:
    expected: dict[str, Any] = {"cause": fault.cause, "terms": list(fault.terms)}
    if fault.step_known:
        steps = [int(item["step"]) for item in trial.steps if item.get("source") == "agent"]
        if steps:
            expected["critical_steps"] = sorted({max(steps), max(max(steps) - 1, 1)})
    return Case(
        fault=fault.name,
        project=str(root),
        job_id=evidence.job_id,
        trial_id=trial.trial_id,
        task=trial.task.task_id,
        healthy_trial_id=healthy.trial_id,
        expected=expected,
    )


def _write_inspector(
    out: Path,
    cases: Sequence[Case],
    *,
    depth: Depth,
    budget_usd: float,
    environ: Mapping[str, str],
) -> None:
    root = out / "inspector"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(TEMPLATE, root, ignore=shutil.ignore_patterns("__pycache__"))
    names = []
    for number, case in enumerate(cases, start=1):
        name = f"case-{number:02d}"
        names.append(name)
        trial = JobEvidence(Path(case.project), case.job_id).trial(case.trial_id)
        write_task(
            root,
            name,
            state={
                "mode": "inspect",
                "project": case.project,
                "job_id": case.job_id,
                "trial_id": case.trial_id,
                "depth": depth,
                "budget_usd": budget_usd,
                "gateway_url": environ.get("PLURAL_GATEWAY_URL", ""),
                "api_url": environ.get("PLURAL_API_URL", ""),
            },
            instructions=instructions_for(trial, depth, "inspect"),
            expected=case.expected,
        )
    write_benchmark(root, BENCH, names, "Failed Trials whose cause was planted.")


def _run(
    root: Path, bench: str, agent: str, environ: Mapping[str, str], concurrency: int
) -> JobEvidence:
    space = Workspace(Project.at(root))
    plan = plan_run(
        space, RunRequest(benchmark=bench, agent=agent, concurrency=concurrency), environ=environ
    )
    job_id, _ = run_local(space, plan, environ=environ)
    return JobEvidence(root, job_id)


def _categories(root: Path) -> dict[str, list[str]]:
    payload = yaml.safe_load(
        (root / "benchmarks" / "quoting" / "benchmark.yaml").read_text("utf-8")
    )
    # The bench is diagnosis, which never looks at held-out Tasks.
    heldout = set(payload.get("heldout") or ())
    return {
        item["id"]: [task for task in item["tasks"] if task not in heldout]
        for item in payload.get("categories") or ()
    }


def _spread(tasks: Sequence[str], limit: int | None) -> list[str]:
    """At most ``limit`` of ``tasks``, evenly spaced, so every category stays in.

    Returns:
        The Tasks kept, in order.

    Examples:
        >>> _spread(["a", "b", "c", "d", "e", "f"], 3)
        ['a', 'c', 'e']
    """
    if limit is None or len(tasks) <= limit:
        return list(tasks)
    return [tasks[index * len(tasks) // limit] for index in range(limit)]


def _write_agent(root: Path, payload: Mapping[str, Any]) -> None:
    folder = root / "agents" / str(payload["name"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "agent.yaml").write_text(
        yaml.safe_dump(dict(payload), sort_keys=False, width=88), "utf-8"
    )


def _write_bench(root: Path, name: str, tasks: Sequence[str]) -> None:
    folder = root / "benchmarks" / name
    folder.mkdir(parents=True, exist_ok=True)
    description = "The Tasks inspector-bench runs one Agent on, healthy or with a fault."
    (folder / "README.md").write_text(f"# {name}\n\n{description}\n", "utf-8")
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "purpose": "Finds Trials a planted fault broke, for the Inspector to explain.",
        "tasks": list(tasks),
        "scoring": {"description": "The Tasks' own score; inspector-bench reads pass or fail."},
    }
    (folder / "benchmark.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), "utf-8")


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        raise ValueError(f"{path}: expected to find {old!r}")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Build or run inspector-bench.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m plural.inspector.faults")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Run the faults and write the bench.")
    build.add_argument("source", type=Path)
    build.add_argument("out", type=Path)
    build.add_argument("--per-fault", type=int, default=4)
    build.add_argument("--max-tasks", type=int, help="The most Tasks each fault runs on.")
    build.add_argument("--depth", choices=("quick", "standard", "deep"), default="standard")
    build.add_argument("--budget-usd", type=float, default=0.5)
    build.add_argument("--concurrency", type=int, default=8)
    build.add_argument(
        "--weak-model",
        action="append",
        help="A weaker gateway model for the model fault; repeat to try several in turn.",
    )
    build.add_argument(
        "--padding-lines",
        action="append",
        type=int,
        help="Lines of padding for the context fault; repeat to try several in turn.",
    )
    run = commands.add_parser("run", help="Run the Inspector on a built bench.")
    run.add_argument("out", type=Path)
    run.add_argument("--model")
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument(
        "--project", default=os.environ.get("PLURAL_PROJECT"), help="Hosted project for fork keys."
    )
    args = parser.parse_args(argv)
    environ = fork_environ(os.environ, None)
    if args.command == "build":
        cases = build_bench(
            args.source,
            args.out,
            environ=environ,
            per_fault=args.per_fault,
            max_tasks=args.max_tasks,
            depth=args.depth,
            budget_usd=args.budget_usd,
            concurrency=args.concurrency,
            faults=_with_levels(QUOTING_FAULTS, model=args.weak_model, context=args.padding_lines),
        )
        print(f"{len(cases)} cases written to {args.out / 'inspector'}")
        return 0
    summary = run_bench(
        args.out,
        environ=environ,
        model=args.model,
        concurrency=args.concurrency,
        studio=_studio(args.project),
    )
    print(json.dumps({key: summary[key] for key in summary if key != "rows"}, indent=2))
    return 0


def _with_levels(faults: Sequence[Fault], **levels: Sequence[Any] | None) -> tuple[Fault, ...]:
    return tuple(
        replace(fault, levels=tuple(levels[fault.cause] or ()))
        if levels.get(fault.cause)
        else fault
        for fault in faults
    )


def _studio(project: str | None) -> Studio | None:
    from plural.auth import resolve_session

    current = resolve_session()
    if current.token is None and not current.api_key:
        print("Forks are off: sign in, or set PLURAL_API_KEY, to mint fork keys.", file=sys.stderr)
        return None
    with suppress(Exception):
        return current.studio(project=project)
    print("Forks are off: no hosted project to mint fork keys in.", file=sys.stderr)
    return None


__all__ = [
    "BENCH",
    "QUOTING_FAULTS",
    "Case",
    "Fault",
    "build_bench",
    "healthy_agent",
    "main",
    "run_bench",
    "score_rows",
]

if __name__ == "__main__":
    sys.exit(main())
