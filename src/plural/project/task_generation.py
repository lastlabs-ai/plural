"""Draft Tasks with a model, and review the drafts before they join a project.

A draft is a Task folder under ``tasks/_drafts/``, with ``draft:`` in its
``task.yaml`` holding the category, the reason it was written, and the metrics
it exercises. Drafts are not resources: no Benchmark runs them and nothing
pushes them. Approving one moves it to ``tasks/<name>/`` and drops ``draft:``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from plural.model_steps import ModelStep
from plural.project.layout import TASK, Project, ProjectError
from plural.scorecard_drafting import environment_facts, prompt
from plural.tasks import validate_task_state

__all__ = [
    "DRAFTS",
    "GenerationResult",
    "TaskDraft",
    "approve",
    "draft_names",
    "generate",
    "next_names",
    "normalized",
    "read_draft",
    "reject",
    "write_draft",
]

DRAFTS = "_drafts"
"""The folder under ``tasks/`` that holds drafts."""

BATCH = 10
"""Drafts asked for in one model call, so each answer stays short enough to be whole."""


class TaskDraft(BaseModel):
    """One drafted Task, before review.

    Examples:
        >>> TaskDraft(instructions="Quote 5 tons of A36.", category="simple").category
        'simple'
    """

    model_config = ConfigDict(frozen=True)

    instructions: str
    initial_state: dict[str, Any] = Field(default_factory=dict)
    expected: Any = None
    category: str = ""
    rationale: str = ""
    metrics_exercised: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        """The draft's identity for exact-duplicate checks: its words and its state."""
        payload = json.dumps(
            {"text": normalized(self.instructions), "state": self.initial_state},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class GenerationResult:
    """What one ``plural task generate`` produced."""

    drafts: list[TaskDraft] = field(default_factory=list)
    invalid: list[tuple[TaskDraft, str]] = field(default_factory=list)
    duplicates: list[TaskDraft] = field(default_factory=list)

    def coverage(self) -> dict[str, int]:
        """Drafts exercising each metric, most first.

        Returns:
            Metric name to count.
        """
        counts: dict[str, int] = {}
        for draft in self.drafts:
            for name in draft.metrics_exercised:
                counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def normalized(text: str) -> str:
    """Instruction text with case, punctuation and spacing ignored.

    Examples:
        >>> normalized("Quote  5 tons, please!") == normalized("quote 5 tons please")
        True

    Returns:
        The normalized text.
    """
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _schema() -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "instructions": {"type": "string"},
            "initial_state_json": {"type": "string"},
            "expected_json": {"type": "string"},
            "category": {"type": "string"},
            "rationale": {"type": "string"},
            "metrics_exercised": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "instructions",
            "initial_state_json",
            "expected_json",
            "category",
            "rationale",
            "metrics_exercised",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"tasks": {"type": "array", "items": item}},
        "required": ["tasks"],
        "additionalProperties": False,
    }


def _loads(text: str, default: Any) -> Any:
    text = (text or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _state_fields(environment: Any) -> str:
    blocks = []
    for app in getattr(environment, "apps", ()):
        schema = app._state_schema()
        properties = {
            key: value
            for key, value in schema.get("properties", {}).items()
            if key not in {"seed", "metadata"}
        }
        blocks.append(
            f"App {type(app).__name__} State schema:\n"
            + json.dumps({**schema, "properties": properties}, indent=1)[:6_000]
        )
    return "\n\n".join(blocks)


def _scorecard_text(scorecard: Any) -> str:
    if scorecard is None:
        return "(no Scorecard: spread the Tasks across the categories)"
    lines = [f"Scorecard {scorecard.reference}: {scorecard.good.strip()[:1_500]}"]
    for metric in scorecard.metrics:
        target = f" ({metric.target})" if metric.target else ""
        lines.append(f"- {metric.name}: {metric.role}{target}")
    for decision in scorecard.decisions:
        lines.append(f"Decision: {decision.question} {decision.answer}")
    return "\n".join(lines)


def _examples_text(examples: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for example in examples:
        parts.append(
            f"## Task {example['name']} (category: {example.get('category') or 'none'})\n"
            f"instructions:\n{example['instructions'].strip()}\n"
            f"initial_state: {json.dumps(example.get('initial_state') or {})}\n"
            f"expected: {json.dumps(example.get('expected'))}"
        )
    return "\n\n".join(parts) or "(no existing Tasks)"


def generate(
    step: ModelStep,
    *,
    environment: Any,
    count: int,
    scorecard: Any = None,
    examples: Sequence[Mapping[str, Any]] = (),
    categories: Sequence[str] = (),
    traces: str = "",
) -> GenerationResult:
    """Draft ``count`` Tasks, validate each, and drop duplicates.

    Each draft's initial state is checked against the Environment's State
    schemas; a draft that fails is kept aside with the reason. Exact
    duplicates, of the existing Tasks or each other, are dropped by their
    words and state; near-duplicates are found by one more model call.

    Returns:
        The drafts, the invalid ones, and the duplicates dropped.
    """
    definition = environment.definition()
    context = "\n\n".join(
        [
            "# Environment\n" + environment_facts(environment),
            _state_fields(environment),
            "# Scorecard\n" + _scorecard_text(scorecard),
            "# Categories\n" + (", ".join(categories) or "(none yet)"),
            "# Existing Tasks\n" + _examples_text(examples),
            *(["# Traces of real work\n" + traces] if traces else []),
        ]
    )
    result = GenerationResult()
    seen = {
        TaskDraft(
            instructions=item["instructions"], initial_state=item.get("initial_state") or {}
        ).digest
        for item in examples
    }
    remaining = count
    while remaining > 0:
        batch = min(BATCH, remaining)
        remaining -= batch
        reply = step.json(
            system=prompt("task_generate"),
            user=f"{context}\n\nWrite {batch} Tasks.",
            schema_name="task_drafts",
            schema=_schema(),
            max_tokens=1_000 + 700 * batch,
        )
        for raw in reply.get("tasks", [])[:batch]:
            state = _loads(raw.get("initial_state_json", ""), {})
            draft = TaskDraft(
                instructions=str(raw.get("instructions") or "").strip(),
                initial_state=state if isinstance(state, dict) else {},
                expected=_loads(raw.get("expected_json", ""), None),
                category=str(raw.get("category") or "").strip(),
                rationale=str(raw.get("rationale") or "").strip(),
                metrics_exercised=tuple(str(name) for name in raw.get("metrics_exercised", [])),
            )
            if not draft.instructions:
                result.invalid.append((draft, "no instructions"))
                continue
            try:
                validate_task_state(
                    task_id="draft", environment=definition, state=draft.initial_state or None
                )
            except ValueError as exc:
                result.invalid.append((draft, " ".join(str(exc).splitlines()[1:]) or str(exc)))
                continue
            if draft.digest in seen:
                result.duplicates.append(draft)
                continue
            seen.add(draft.digest)
            result.drafts.append(draft)
    if len(result.drafts) > 1:
        _drop_near_duplicates(step, result)
    return result


def _drop_near_duplicates(step: ModelStep, result: GenerationResult) -> None:
    listing = "\n\n".join(
        f"{index}. [{draft.category}] {draft.instructions[:600]}\n"
        f"state: {json.dumps(draft.initial_state)[:400]}"
        for index, draft in enumerate(result.drafts)
    )
    reply = step.json(
        system=prompt("task_dedupe"),
        user=listing,
        schema_name="near_duplicates",
        schema={
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                }
            },
            "required": ["groups"],
            "additionalProperties": False,
        },
        max_tokens=1_000,
    )
    dropped: set[int] = set()
    for group in reply.get("groups", []):
        members = sorted(
            {index for index in group if isinstance(index, int)} & set(range(len(result.drafts)))
        )
        dropped.update(members[1:])
    result.duplicates.extend(result.drafts[index] for index in sorted(dropped))
    result.drafts = [draft for index, draft in enumerate(result.drafts) if index not in dropped]


def drafts_dir(project: Project) -> Path:
    """The folder that holds a project's Task drafts.

    Returns:
        ``tasks/_drafts`` under the project root.
    """
    return project.root / TASK.directory / DRAFTS


def next_names(project: Project, count: int, prefix: str | None = None) -> list[str]:
    """Free Task names that continue the project's numbering.

    With no prefix, the prefix the existing Tasks share is used, so ``quote-060``
    is followed by ``quote-061``.

    Returns:
        ``count`` names no Task or draft has.
    """
    taken = set(project.names(TASK)) | set(draft_names(project))
    if prefix is None:
        stems = [match.group(1) for name in taken if (match := re.match(r"(.+?)-?\d+$", name))]
        prefix = max(set(stems), key=stems.count) if stems else "task"
    numbers = [
        int(match.group(1))
        for name in taken
        if (match := re.fullmatch(re.escape(prefix) + r"-?(\d+)", name))
    ]
    width = max(3, *(len(str(number)) for number in numbers)) if numbers else 3
    names: list[str] = []
    number = max(numbers, default=0)
    while len(names) < count:
        number += 1
        name = f"{prefix}-{number:0{width}d}"
        if name not in taken:
            names.append(name)
    return names


def write_draft(
    project: Project,
    name: str,
    draft: TaskDraft,
    *,
    environment: str,
    verifiers: Sequence[str],
) -> Path:
    """Write one draft as a Task folder under ``tasks/_drafts/``.

    Returns:
        The draft's folder.
    """
    folder = drafts_dir(project) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "instruction.md").write_text(draft.instructions.strip() + "\n", encoding="utf-8")
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "instructions": "instruction.md",
        "environment": environment,
        "verifiers": list(verifiers),
    }
    if draft.expected is not None:
        manifest["expected"] = draft.expected
    if draft.initial_state:
        manifest["initial_state"] = draft.initial_state
    manifest["draft"] = {
        "category": draft.category,
        "rationale": draft.rationale,
        "metrics_exercised": list(draft.metrics_exercised),
    }
    (folder / "task.yaml").write_text(
        "# Drafted by `plural task generate`. Review it with `plural task review`.\n"
        + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return folder


def draft_names(project: Project) -> list[str]:
    """The drafts waiting for review, sorted.

    Returns:
        Their names.
    """
    folder = drafts_dir(project)
    if not folder.is_dir():
        return []
    return sorted(path.name for path in folder.iterdir() if (path / "task.yaml").is_file())


def read_draft(project: Project, name: str) -> dict[str, Any]:
    """One draft's manifest with its instructions read in.

    Returns:
        The manifest, with ``instructions_text`` added.

    Raises:
        ProjectError: When there is no such draft.
    """
    folder = drafts_dir(project) / name
    if not (folder / "task.yaml").is_file():
        raise ProjectError(
            f"There is no draft {name!r} in tasks/{DRAFTS}/.\n"
            "Next: plural task review lists the drafts."
        )
    manifest = yaml.safe_load((folder / "task.yaml").read_text(encoding="utf-8")) or {}
    instructions = folder / str(manifest.get("instructions") or "instruction.md")
    manifest["instructions_text"] = (
        instructions.read_text(encoding="utf-8") if instructions.is_file() else ""
    )
    return manifest


def approve(project: Project, name: str, *, benchmark: str | None = None) -> Path:
    """Make a draft a Task: move it to ``tasks/<name>/`` and drop ``draft:``.

    With ``benchmark``, the Task joins that Benchmark, in its drafted category
    when the Benchmark has one by that id.

    Returns:
        The Task's folder.

    Raises:
        ProjectError: When a Task by that name exists already.
    """
    source = drafts_dir(project) / name
    manifest = read_draft(project, name)
    target = project.root / TASK.directory / name
    if target.exists():
        raise ProjectError(
            f"Task {name} exists already.\nNext: rename the draft's folder and its name."
        )
    draft = manifest.get("draft") or {}
    path = source / "task.yaml"
    text = path.read_text(encoding="utf-8")
    kept = yaml.safe_load(text) or {}
    kept.pop("draft", None)
    path.write_text(
        "# Task drafted by `plural task generate` and approved in review.\n"
        + yaml.safe_dump(kept, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    shutil.move(str(source), target)
    if benchmark is not None:
        _join_benchmark(project, benchmark, name, str(draft.get("category") or ""))
    return target


def _join_benchmark(project: Project, benchmark: str, task: str, category: str) -> None:
    path = project.root / "benchmarks" / benchmark / "benchmark.yaml"
    if not path.is_file():
        raise ProjectError(f"There is no Benchmark {benchmark!r}.\nNext: plural benchmark list")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tasks = list(data.get("tasks") or [])
    if task not in tasks:
        tasks.append(task)
    data["tasks"] = tasks
    for item in data.get("categories") or []:
        if item.get("id") == category and task not in (item.get("tasks") or []):
            item["tasks"] = [*(item.get("tasks") or []), task]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def reject(project: Project, name: str) -> None:
    """Delete a draft.

    Raises:
        ProjectError: When there is no such draft.
    """
    read_draft(project, name)
    shutil.rmtree(drafts_dir(project) / name)


def existing_examples(
    project: Project, categories: Mapping[str, Iterable[str]], limit: int = 8
) -> list[dict[str, Any]]:
    """A few existing Tasks to show the model, one category at a time.

    Returns:
        Up to ``limit`` Tasks with their instructions, state, answer key and category.
    """
    by_task = {task: category for category, tasks in categories.items() for task in tasks}
    names = project.names(TASK)
    ordered: list[str] = []
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(by_task.get(name, ""), []).append(name)
    while len(ordered) < min(limit, len(names)):
        for group in groups.values():
            if group and len(ordered) < limit:
                ordered.append(group.pop(0))
    examples = []
    for name in ordered:
        folder = project.root / TASK.directory / name
        manifest = yaml.safe_load((folder / "task.yaml").read_text(encoding="utf-8")) or {}
        instructions = manifest.get("instructions") or ""
        path = folder / str(instructions)
        if path.suffix == ".md" and path.is_file():
            instructions = path.read_text(encoding="utf-8")
        examples.append(
            {
                "name": name,
                "instructions": str(instructions),
                "initial_state": manifest.get("initial_state") or {},
                "expected": manifest.get("expected"),
                "category": by_task.get(name, ""),
            }
        )
    return examples
