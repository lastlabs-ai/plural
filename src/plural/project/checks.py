"""The checks behind ``plural task validate`` and ``plural benchmark validate``.

Each Task runs its reference policy, which must pass, and two probes that must
fail, a do-nothing Agent and one that repeats the instructions. Everything the
Agent can read is scanned for leaks, and each Environment's default Runtime is
checked for how far its results can be trusted.

Each Task version's check is saved as ``.plural/checks/<task>@<version>.json``
and is current while the Task's content hash matches. The probes run as local
Jobs kept in ``.plural/checks/jobs``, apart from the project's own Jobs.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from plural.blobs import read_blob
from plural.common import FrozenModel
from plural.harness.probes import PROBE_KINDS, SCAN_KEY, ProbeKind, probe_package
from plural.integrity.checks import ProbeResult, TaskCheck, judge_probe
from plural.integrity.leaks import AgentFile, LeakFinding, scan_task
from plural.jobs import TrialResult
from plural.project.layout import (
    BENCHMARK,
    ENVIRONMENT,
    TASK,
    VERIFIER,
    ProjectError,
    ResourceRef,
)
from plural.project.manifests import read_yaml_mapping
from plural.project.resources import Workspace, _package_files

CHECKS_DIRECTORY = Path(".plural") / "checks"
PROBE_MODEL = "openai/gpt-5.6-luna"
"""The catalog model the probe Agents name. Probes never call it."""


@dataclass
class CheckPlan:
    """What a validation's probes will run.

    Attributes:
        tasks: The Tasks to check, by name.
        threshold: The score that counts as success.
        canaries: Each Task's Benchmark canaries.
        references: Each Task's reference policy as ``path.py:function``.
        skipped: Tasks that cannot be checked, with why.
    """

    tasks: list[str]
    threshold: float = 1.0
    canaries: dict[str, tuple[str, ...]] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)


def check_path(root: Path, task: str, version: str) -> Path:
    """Where one Task version's check is kept.

    Returns:
        The path, whether or not it exists.

    Examples:
        >>> check_path(Path("/p"), "quote-001", "0.1.0").as_posix()
        '/p/.plural/checks/quote-001@0.1.0.json'
    """
    return root / CHECKS_DIRECTORY / f"{task}@{version}.json"


def load_check(workspace: Workspace, task: str) -> TaskCheck | None:
    """The saved check of a Task's current version, if it is still current.

    Returns:
        The check, or ``None`` when there is none or the Task changed since.
    """
    resource = workspace.load(ResourceRef(TASK.name, task))
    path = check_path(workspace.project.root, task, resource.version)
    if not path.is_file():
        return None
    try:
        check = TaskCheck.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return check if check.content_hash == resource.content_hash else None


def save_check(workspace: Workspace, check: TaskCheck) -> Path:
    """Write one Task version's check.

    Returns:
        The path written.
    """
    path = check_path(workspace.project.root, check.task, check.version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(check.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def plan_checks(
    workspace: Workspace,
    tasks: Sequence[str] = (),
    *,
    benchmark: str | None = None,
) -> CheckPlan:
    """Choose the Tasks to check and gather what the check needs.

    Args:
        workspace: The project.
        tasks: Task names; all of the Benchmark's, or the project's, when empty.
        benchmark: A Benchmark whose Tasks, threshold, and canary to use.

    Returns:
        The plan.

    Raises:
        ProjectError: When a named Task is not in the project or the Benchmark.
    """
    project = workspace.project
    threshold = 1.0
    if benchmark is not None:
        value = workspace.load(ResourceRef(BENCHMARK.name, benchmark)).value
        members = [task.name for task in value.tasks]
        threshold = float(value.scoring.success_threshold)
        missing = [name for name in tasks if name not in members]
        if missing:
            raise ProjectError(f"{', '.join(missing)} not in Benchmark {benchmark!r}.")
        names = list(tasks) or members
    else:
        names = list(tasks) or project.names(TASK)
    canaries: dict[str, list[str]] = {name: [] for name in names}
    for other in project.names(BENCHMARK):
        payload = read_yaml_mapping(project.manifest_path(ResourceRef(BENCHMARK.name, other)))
        canary = payload.get("canary")
        if not isinstance(canary, str) or not canary:
            continue
        for name in payload.get("tasks") or ():
            if str(name) in canaries and canary not in canaries[str(name)]:
                canaries[str(name)].append(canary)
    plan = CheckPlan(
        tasks=[],
        threshold=threshold,
        canaries={name: tuple(values) for name, values in canaries.items()},
    )
    for name in names:
        task = workspace.load(ResourceRef(TASK.name, name)).value
        if task._environment_definition().party is not None:
            plan.skipped[name] = "played by a party of Agents, which probes can't fill yet"
            continue
        plan.tasks.append(name)
        reference = task_reference(workspace, name)
        if reference is not None:
            plan.references[name] = reference
    return plan


def task_reference(workspace: Workspace, task: str) -> str | None:
    """A Task's reference policy, its own or its Environment's.

    Returns:
        ``/absolute/path.py:function``, or ``None`` when neither declares one.

    Raises:
        ProjectError: When the declared file does not exist.
    """
    project = workspace.project
    task_ref = ResourceRef(TASK.name, task)
    payload = read_yaml_mapping(project.manifest_path(task_ref))
    owner = project.resource_dir(task_ref)
    reference = payload.get("reference")
    if not reference:
        environment = ResourceRef(ENVIRONMENT.name, str(payload.get("environment")))
        owner = project.resource_dir(environment)
        reference = read_yaml_mapping(project.manifest_path(environment)).get("reference")
    if not reference:
        return None
    file, _, function = str(reference).rpartition(":")
    path = (owner / file).resolve()
    if not path.is_relative_to(owner.resolve()) or not path.is_file():
        raise ProjectError(f"reference: {file} does not exist in {owner}")
    return f"{path}:{function}"


def agent_files(workspace: Workspace, task: str) -> list[AgentFile]:
    """Every file the Agent can read for a Task: its own and its Environment's.

    Returns:
        The files, as the Agent sees them.
    """
    value = workspace.load(ResourceRef(TASK.name, task)).value
    environment = value._environment_definition()
    directory = workspace.project.resource_dir(ResourceRef(ENVIRONMENT.name, environment.name))
    files = []
    task_root = workspace.project.resource_dir(ResourceRef(TASK.name, task))
    for resources, root in ((value.resources, task_root), (environment.resources, directory)):
        for resource in resources:
            for path, data in _resource_files(resource, root):
                files.append(AgentFile(path, data))
    seen = {item.data for item in files}
    files.extend(item for item in environment_source(workspace, task) if item.data not in seen)
    return files


def environment_source(workspace: Workspace, task: str) -> list[AgentFile]:
    """The Environment's own files, which the engine ships to the sandbox.

    The Agent can read them, except a Verifier's code and the reference policy,
    which the engine leaves out.

    Returns:
        The files, under ``environment/``.
    """
    from plural.harness.retrieval import package_files

    value = workspace.load(ResourceRef(TASK.name, task)).value
    environment = value._environment_definition()
    directory = workspace.project.resource_dir(ResourceRef(ENVIRONMENT.name, environment.name))
    if not directory.is_dir():
        return []
    return [
        AgentFile(f"environment/{relative}", path.read_bytes())
        for relative, path in package_files(directory)
    ]


def verifier_sources(workspace: Workspace, task: str) -> dict[str, bytes]:
    """The source files of a Task's Verifiers.

    Returns:
        Each file's bytes, keyed ``verifier/path``.
    """
    project = workspace.project
    payload = read_yaml_mapping(project.manifest_path(ResourceRef(TASK.name, task)))
    sources = {}
    for name in payload.get("verifiers") or ():
        root = project.resource_dir(ResourceRef(VERIFIER.name, str(name)))
        if not root.is_dir():
            continue
        for path in _package_files(root):
            if path.suffix == ".py":
                sources[f"{name}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    return sources


def run_checks(
    workspace: Workspace,
    plan: CheckPlan,
    *,
    probes: Sequence[ProbeKind] = PROBE_KINDS,
    random_steps: int = 20,
    concurrency: int = 4,
    progress: Callable[[str], None] | None = None,
) -> list[TaskCheck]:
    """Run the probes and the leak scan for every planned Task, and save each check.

    Returns:
        One check per Task, in the plan's order.
    """
    from plural import Agent, Benchmark, Job
    from plural.execution.store import JobStore
    from plural.project.resources import load_harness_directory

    tasks = {name: workspace.load(ResourceRef(TASK.name, name)).value for name in plan.tasks}
    if not tasks:
        return []
    store = JobStore(workspace.project.root / CHECKS_DIRECTORY / "jobs")
    trials: dict[ProbeKind, dict[str, TrialResult]] = {}
    scans: dict[str, Mapping[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="plural-probes-") as scratch:
        for kind in probes:
            selected = [
                name for name in plan.tasks if kind != "reference" or name in plan.references
            ]
            if not selected:
                continue
            if progress is not None:
                progress(f"Running the {kind} probe on {len(selected)} Task(s)")
            package = probe_package(
                kind,
                references={name: Path(plan.references[name]) for name in selected}
                if kind == "reference"
                else None,
                random_steps=random_steps,
                directory=Path(scratch) / kind,
            )
            agent = Agent(
                name=f"plural-probe-{kind}",
                model=PROBE_MODEL,
                harness=load_harness_directory(package),
                auth="none",
            )
            values = [tasks[name] for name in selected]
            source = (
                values[0]
                if len(values) == 1
                else Benchmark(name="plural-task-check", version="0.0.0", tasks=tuple(values))
            )
            job = Job(
                source,
                agents=[agent],
                concurrency=concurrency,
                catalog=workspace.catalog,
                store=store,
            )
            result = job.run()
            found: dict[str, TrialResult] = {}
            for trial in result.trials:
                name = trial.receipt.task_pin.name
                found[name] = trial
                if kind == "noop":
                    scans[name] = _probe_scan(store, trial)
            trials[kind] = found
    checks = []
    now = datetime.now(timezone.utc)
    for name in plan.tasks:
        resource = workspace.load(ResourceRef(TASK.name, name))
        value = resource.value
        results = []
        for kind in probes:
            found_trial = trials.get(kind, {}).get(name)
            if kind == "reference" and name not in plan.references:
                results.append(
                    ProbeResult(
                        probe=kind,
                        status="skipped",
                        threshold=plan.threshold,
                        detail="no reference policy: add reference: to the Task or its Environment",
                    )
                )
            elif found_trial is None:
                results.append(
                    ProbeResult(
                        probe=kind,
                        status="error",
                        threshold=plan.threshold,
                        detail=f"{kind} did not run",
                    )
                )
            else:
                results.append(judge_probe(kind, found_trial, plan.threshold))
        leaks: list[LeakFinding] = []
        vocabulary = "\n".join(
            item.data.decode("utf-8", "replace") for item in environment_source(workspace, name)
        )
        for canary in plan.canaries.get(name) or (None,):
            leaks.extend(
                scan_task(
                    instructions=value.instructions,
                    expected=value.expected,
                    info=value.info,
                    metadata=value.metadata,
                    files=agent_files(workspace, name),
                    verifier_sources=verifier_sources(workspace, name),
                    canary=canary,
                    workspace_scan=scans.get(name),
                    vocabulary=vocabulary,
                )
            )
        check = TaskCheck(
            task=name,
            version=resource.version,
            content_hash=resource.content_hash,
            checked_at=now,
            probes=tuple(results),
            leaks=tuple(dict.fromkeys(leaks)),
        )
        save_check(workspace, check)
        checks.append(check)
    return checks


def saved_checks(workspace: Workspace, tasks: Iterable[str]) -> dict[str, TaskCheck | None]:
    """Each Task's current saved check, or ``None`` when it has none.

    Returns:
        Checks by Task name.
    """
    return {name: load_check(workspace, name) for name in tasks}


def _probe_scan(store: Any, trial: TrialResult) -> Mapping[str, Any]:
    root = store.trial_path(trial.receipt.trial_id, trial.receipt.job_id)
    for path in sorted(root.glob("executions/*/artifacts/result.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        scan = payload.get(SCAN_KEY) if isinstance(payload, dict) else None
        if isinstance(scan, dict):
            return scan
    return {}


def _resource_files(resource: Any, root: Path) -> list[tuple[str, bytes]]:
    name = str(resource.path or resource.name)
    if resource.content is not None:
        return [(name, str(resource.content).encode("utf-8"))]
    if resource.digest and resource.delivery == "blob":
        try:
            return [(name, read_blob(resource.digest))]
        except (OSError, ValueError):
            return []
    if resource.path and resource.delivery == "source":
        target = (root / resource.path).resolve()
        if not target.is_relative_to(root.resolve()):
            return []
        if target.is_file():
            return [(name, target.read_bytes())]
        if target.is_dir():
            return [
                (path.relative_to(root.resolve()).as_posix(), path.read_bytes())
                for path in sorted(_package_files(target))
            ]
    return []


CheckMark = Literal["ok", "problem", "warning"]


class CheckLine(FrozenModel):
    """One line of a validation report.

    Attributes:
        mark: ``ok``, ``problem`` to fix before a baseline, or ``warning``.
        text: The line.
        detail: An indented second line, such as the Verifier's feedback.
        tasks: The Tasks it is about.
        command: The command that shows more or fixes it.
    """

    mark: CheckMark
    text: str
    detail: str = ""
    tasks: tuple[str, ...] = ()
    command: str | None = None


class CheckSection(FrozenModel):
    """A titled group of lines: ``Graders``, ``Leaks``, or ``Trust``."""

    title: str
    lines: tuple[CheckLine, ...]


class CheckReport(FrozenModel):
    """What validating Tasks found, beyond their files.

    Attributes:
        tasks: Tasks checked.
        sections: Graders, Leaks, and Trust.
        problems: Lines marked ``problem``.
        next_command: The command that fixes the first problem, if any.
    """

    tasks: int
    sections: tuple[CheckSection, ...]
    problems: int
    next_command: str | None = None


def check_report(
    workspace: Workspace,
    tasks: Sequence[str] = (),
    *,
    benchmark: str | None = None,
    rerun: bool = False,
    random_steps: int = 0,
    progress: Callable[[str], None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[CheckReport, list[TaskCheck]]:
    """Check Tasks' graders, leaks, and trust, reusing each unchanged Task's check.

    Args:
        workspace: The project.
        tasks: Task names; all of the Benchmark's, or the project's, when empty.
        benchmark: A Benchmark whose Tasks, threshold, and canary to use.
        rerun: Run every Task's probes again, even when unchanged.
        random_steps: Also run the ``random`` probe for this many actions.
        progress: Called with a line as each probe starts.
        environ: Where to look up the conformance cache.

    Returns:
        The report, and the checks that ran now.
    """
    plan = plan_checks(workspace, tasks, benchmark=benchmark)
    stale = (
        plan.tasks
        if rerun or random_steps
        else [name for name in plan.tasks if load_check(workspace, name) is None]
    )
    probes: tuple[Any, ...] = ("reference", "noop", "echo") + (("random",) if random_steps else ())
    ran: list[TaskCheck] = []
    if stale:
        subset = plan_checks(workspace, stale, benchmark=benchmark)
        ran = run_checks(
            workspace, subset, probes=probes, random_steps=random_steps or 20, progress=progress
        )
    checks = {name: load_check(workspace, name) for name in plan.tasks}
    present = {name: check for name, check in checks.items() if check is not None}
    sections = (
        CheckSection(title="Graders", lines=tuple(_grader_lines(present, plan.skipped))),
        CheckSection(title="Leaks", lines=tuple(_leak_lines(present))),
        CheckSection(title="Trust", lines=tuple(_isolation_lines(workspace, plan.tasks, environ))),
    )
    problems = [line for section in sections for line in section.lines if line.mark == "problem"]
    return (
        CheckReport(
            tasks=len(plan.tasks),
            sections=sections,
            problems=len(problems),
            next_command=problems[0].command if problems else None,
        ),
        ran,
    )


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun if count == 1 else noun + 's'}"


_PROBE_LABELS: dict[ProbeKind, str] = {
    "noop": "do-nothing agent fails",
    "echo": "copy-the-instructions agent fails",
    "random": "random-actions agent fails",
}


def _grader_lines(checks: Mapping[str, TaskCheck], skipped: Mapping[str, str]) -> list[CheckLine]:
    lines: list[CheckLine] = []
    references = {
        name: item
        for name, check in checks.items()
        if (item := check.probe("reference")) is not None and item.status != "skipped"
    }
    if references:
        passing = sum(item.status == "passed" for item in references.values())
        lines.append(
            CheckLine(
                mark="ok",
                text=f"{'reference solution passes every gate':<44} {passing}/{len(references)}",
            )
        )
        lines.extend(_failures("reference", references))
    missing = tuple(name for name in checks if name not in references)
    if missing:
        lines.append(
            CheckLine(
                mark="warning",
                text=f"{_names(missing)}: no reference policy, so nothing shows the Task "
                "can be solved",
                detail="add reference: file.py:function to the Task or its Environment",
                tasks=missing,
            )
        )
    for kind, label in _PROBE_LABELS.items():
        results = {
            name: item for name, check in checks.items() if (item := check.probe(kind)) is not None
        }
        if not results:
            continue
        failing = sum(item.status == "passed" for item in results.values())
        lines.append(CheckLine(mark="ok", text=f"{label:<44} {failing}/{len(results)}"))
        lines.extend(_failures(kind, results))
    for name, reason in skipped.items():
        lines.append(
            CheckLine(mark="warning", text=f"{name}: not checked, {reason}", tasks=(name,))
        )
    return lines


def _failures(kind: str, results: Mapping[str, ProbeResult]) -> list[CheckLine]:
    groups: dict[tuple[str, ...], list[str]] = {}
    for name, item in results.items():
        if item.status == "error":
            groups.setdefault(("error",), []).append(name)
        elif item.status == "failed":
            key = item.failed_checks if kind == "reference" else ()
            groups.setdefault(key, []).append(name)
    lines = []
    for key, names in groups.items():
        first = results[names[0]]
        if key == ("error",):
            text = f"{_names(names)}: {first.detail}"
        elif kind == "reference":
            text = f"{_names(names)}: reference fails {', '.join(key) or 'the threshold'}"
        else:
            text = f"{_names(names)}: {first.detail}"
        lines.append(
            CheckLine(
                mark="warning" if kind == "random" else "problem",
                text=text,
                detail=first.feedback,
                tasks=tuple(names),
                command=f"plural task validate {names[0]}",
            )
        )
    return lines


def _leak_lines(checks: Mapping[str, TaskCheck]) -> list[CheckLine]:
    lines: list[CheckLine] = []
    groups: dict[tuple[str, str], list[str]] = {}
    messages: dict[tuple[str, str], tuple[str, str]] = {}
    unread: dict[str, list[str]] = {}
    for name, check in checks.items():
        for leak in check.leaks:
            if leak.severity == "info":
                unread.setdefault(leak.path, []).append(name)
                continue
            key: tuple[str, str] = (leak.kind, leak.path)
            groups.setdefault(key, []).append(name)
            messages[key] = (leak.message, leak.severity)
    for key, names in groups.items():
        message, _severity = messages[key]
        lines.append(
            CheckLine(
                mark="problem",
                text=f"{_names(tuple(names))}: {message}",
                detail=_LEAK_FIXES[key[0]],
                tasks=tuple(names),
                command=f"plural task validate {names[0]}",
            )
        )
    if not groups:
        lines.append(
            CheckLine(
                mark="ok",
                text="no answer keys, git history, solution files or Verifier code in "
                "agent-visible files",
            )
        )
    if unread:
        paths = sorted(unread)
        lines.append(
            CheckLine(
                mark="warning",
                text=f"{_counted(len(paths), 'file')} not scanned: {', '.join(paths[:3])}"
                + (f" and {len(paths) - 3} more" if len(paths) > 3 else ""),
                detail="check these by hand; their format has no text the scan can read",
            )
        )
    return lines


_LEAK_FIXES = {
    "answer_key": "remove it from what the Agent sees; the answer key belongs in expected",
    "git_history": "ship the repository with one commit: no older commits, tags, or branches",
    "solution_file": "rename or remove the file, or move it out of the Agent's files",
    "verifier_copy": "keep Verifier code in its own folder, never in the Agent's files",
    "canary": "keep the Benchmark's canary out of every agent-visible file",
    "not_scanned": "",
}


def _isolation_lines(
    workspace: Workspace, tasks: Sequence[str], environ: Mapping[str, str] | None
) -> list[CheckLine]:
    from plural.sandbox import default_registry
    from plural.sandbox.conformance import conformance_status

    providers: dict[str, list[str]] = {}
    for name in tasks:
        environment = workspace.load(ResourceRef(TASK.name, name)).value._environment_definition()
        provider = environment.runtime.provider
        if environment.name not in providers.setdefault(provider, []):
            providers[provider].append(environment.name)
    lines = []
    for provider, environments in sorted(providers.items()):
        where = ", ".join(environments)
        if provider == "local":
            lines.append(
                CheckLine(
                    mark="warning",
                    text=f"{where} runs on the local Runtime, so Trials are unverified",
                    detail="use runtime: {provider: daytona} for verified results",
                )
            )
            continue
        try:
            status, failures = asyncio.run(
                conformance_status(default_registry.get(provider), environ)
            )
        except Exception:  # noqa: BLE001 - an unreachable provider has no report
            status, failures = "missing", ()
        if status == "passed":
            lines.append(
                CheckLine(
                    mark="ok", text=f"{where} runs on {provider}: verified, conformance passed"
                )
            )
        elif status == "failed":
            lines.append(
                CheckLine(
                    mark="warning",
                    text=f"{where} runs on {provider}: standard, conformance failed "
                    f"{', '.join(failures)}",
                    command=f"plural runtime doctor --provider {provider} --conformance",
                )
            )
        else:
            lines.append(
                CheckLine(
                    mark="warning",
                    text=f"{where} runs on {provider}: standard until its conformance suite runs",
                    command=f"plural runtime doctor --provider {provider} --conformance",
                )
            )
    return lines


def _names(names: Sequence[str]) -> str:
    shown = ", ".join(names[:3])
    return shown + (f" and {len(names) - 3} more" if len(names) > 3 else "")


__all__ = [
    "CHECKS_DIRECTORY",
    "PROBE_MODEL",
    "CheckLine",
    "CheckMark",
    "CheckPlan",
    "CheckReport",
    "CheckSection",
    "check_report",
    "agent_files",
    "check_path",
    "environment_source",
    "load_check",
    "plan_checks",
    "run_checks",
    "save_check",
    "saved_checks",
    "task_reference",
    "verifier_sources",
]
