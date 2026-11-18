"""inspector-bench: plant known faults, keep the Trials they break, and score the Inspector.

A healthy Agent runs the quoting Tasks. Each fault then changes one thing, the
Agent (its instructions, a tool's description, or which tools it sees) or the
project (its Verifier, an answer key, or a Task's request), and the same Tasks
run again. A Trial joins the bench only when the healthy Agent passed its Task
and the faulty run failed it, so its cause is known. Each becomes one Inspector
Task whose answer key is the planted cause; the Inspector's accuracy is the
pass rate of ``finding-check`` over them.

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from plural.inspector.evidence import JobEvidence, TrialEvidence
from plural.inspector.run import (
    TEMPLATE,
    Depth,
    instructions_for,
    with_credential,
    write_benchmark,
    write_task,
)
from plural.project.layout import Project
from plural.project.resources import Workspace
from plural.project.runs import RunRequest, local_job_spec, plan_run, run_local

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
        agent: Changes the healthy Agent's manifest; ``None`` for a project fault.
        project: Changes a copy of the project; ``None`` for an Agent fault.
        step_known: Whether the critical step is the Agent's answer. A grader
            fault breaks no step, so any step is accepted.
    """

    name: str
    cause: str
    description: str
    categories: tuple[str, ...]
    terms: tuple[str, ...]
    agent: Callable[[dict[str, Any]], None] | None = None
    project: Callable[[Path], None] | None = None
    step_known: bool = True


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


def _hide_schedule(agent: dict[str, Any]) -> None:
    agent["tool_overrides"] = {"check_schedule": {"hidden": True}}


def _vague_schedule(agent: dict[str, Any]) -> None:
    agent["tool_overrides"] = {"check_schedule": "Optional: view mill bookings."}


def _rounding(agent: dict[str, Any]) -> None:
    agent["instructions"] = str(agent["instructions"]).replace(EXACT, ROUNDING)


def _requested_date(agent: dict[str, Any]) -> None:
    agent["instructions"] = (
        str(agent["instructions"]).rstrip()
        + " Always promise the delivery date the customer asked for; customers walk away "
        "from any other date.\n"
    )


def _never_handoff(agent: dict[str, Any]) -> None:
    agent["instructions"] = (
        str(agent["instructions"]).rstrip()
        + " The sales team is fully booked this week, so never hand off: always send a "
        "quote, filling in whatever the customer left out.\n"
    )


def _padding(agent: dict[str, Any]) -> None:
    filler = "\n".join(PADDING_LINE.format(n=n) for n in range(1, 1201))
    agent["instructions"] = filler + "\n\n" + str(agent["instructions"])


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
        "grader",
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
    depth: Depth = "standard",
    budget_usd: float = 0.5,
    concurrency: int = 8,
    log: Callable[[str], None] = print,
) -> list[Case]:
    """Run the healthy and faulty Agents, keep the Trials each fault broke, write the bench.

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
    for index, fault in enumerate(faults, start=1):
        tasks = sorted(
            task for name in fault.categories for task in categories.get(name, ()) if task in passed
        )
        if not tasks:
            continue
        bench = f"bench-{index}"
        if fault.agent is not None:
            root, name = clean, f"agent-{index}"
            variant = json.loads(json.dumps(healthy))
            variant["name"] = name
            fault.agent(variant)
            _write_agent(root, variant)
        else:
            assert fault.project is not None
            root, name = out / "subjects" / f"s{index}", HEALTHY
            if not root.is_dir():
                shutil.copytree(clean, root, ignore=IGNORED)
                fault.project(root)
        _write_bench(root, bench, tasks)
        log(f"fault {index} on {len(tasks)} Tasks")
        evidence = _run(root, bench, name, environ, concurrency)
        broke = sorted(
            (trial for trial in evidence.trials.values() if trial.passed is False),
            key=lambda trial: trial.task.task_id,
        )
        for trial in broke[:per_fault]:
            cases.append(_case(fault, root, evidence, trial, passed[trial.task.task_id]))
    _write_inspector(out, cases, depth=depth, budget_usd=budget_usd, environ=environ)
    (out / BENCH_FILE).write_text(
        json.dumps(
            {
                "faults": {
                    f.name: {"cause": f.cause, "description": f.description} for f in faults
                },
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
) -> dict[str, Any]:
    """Run the Inspector on the bench and score it.

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
    space = Workspace(Project.at(root))
    plan = plan_run(
        space,
        RunRequest(benchmark=BENCH, agent="inspector", concurrency=concurrency),
        environ=environ,
    )
    job_id, result = run_local(space, plan, environ=environ)
    bench = json.loads((out / BENCH_FILE).read_text("utf-8"))
    by_task = {f"case-{n:02d}": case for n, case in enumerate(bench["cases"], start=1)}
    spec_tasks = {item.content_hash: item.task_id for item in local_job_spec(space, job_id).tasks}
    rows = []
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
            }
        )
    summary = score_rows(rows)
    summary.update(
        {
            "job_id": job_id,
            "model": plan.agent.model,
            "rows": rows,
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
    return {item["id"]: list(item["tasks"]) for item in payload.get("categories") or ()}


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
    build.add_argument("--depth", choices=("quick", "standard", "deep"), default="standard")
    build.add_argument("--budget-usd", type=float, default=0.5)
    build.add_argument("--concurrency", type=int, default=8)
    run = commands.add_parser("run", help="Run the Inspector on a built bench.")
    run.add_argument("out", type=Path)
    run.add_argument("--model")
    run.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    environ = with_credential(os.environ)
    if args.command == "build":
        cases = build_bench(
            args.source,
            args.out,
            environ=environ,
            per_fault=args.per_fault,
            depth=args.depth,
            budget_usd=args.budget_usd,
            concurrency=args.concurrency,
        )
        print(f"{len(cases)} cases written to {args.out / 'inspector'}")
        return 0
    summary = run_bench(args.out, environ=environ, model=args.model, concurrency=args.concurrency)
    print(json.dumps({key: summary[key] for key in summary if key != "rows"}, indent=2))
    return 0


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
