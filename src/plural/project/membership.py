"""Edit which Tasks a Benchmark includes without disturbing the rest of its file."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Sequence

from plural.project.layout import BENCHMARK, TASK, Project, ProjectError, ResourceRef
from plural.project.manifests import read_yaml_mapping

_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_][\w-]*\s*:")


def benchmark_tasks(project: Project, benchmark: str) -> list[str]:
    """Task names a Benchmark currently lists.

    Returns:
        The names, in file order.

    Raises:
        ProjectError: When the Benchmark is missing or ``tasks`` is not a list.
    """
    path = project.manifest_path(ResourceRef(BENCHMARK.name, benchmark))
    if not path.is_file():
        raise ProjectError(
            f"No Benchmark named {benchmark!r} in this project. "
            f"Create it with `plural benchmark init {benchmark}`."
        )
    tasks = read_yaml_mapping(path).get("tasks") or []
    if not isinstance(tasks, list) or not all(isinstance(item, str) for item in tasks):
        raise ProjectError(f"{path}: tasks must be a list of Task names.")
    return list(tasks)


def add_tasks(project: Project, benchmark: str, patterns: Sequence[str]) -> list[str]:
    """Add local Tasks to a Benchmark, each named or matched by a pattern such as ``refund-*``.

    Returns:
        The Tasks added, in order. Ones the Benchmark already lists are skipped.

    Raises:
        ProjectError: When a name or pattern matches no Task in this project.
    """
    wanted = _matching(project.names(TASK), patterns, "in this project", suggest_init=True)
    tasks = benchmark_tasks(project, benchmark)
    added = [name for name in wanted if name not in tasks]
    if added:
        _write_tasks(project, benchmark, [*tasks, *added])
    return added


def remove_tasks(project: Project, benchmark: str, patterns: Sequence[str]) -> list[str]:
    """Remove Tasks from a Benchmark, each named or matched by a pattern.

    Returns:
        The Tasks removed, in the Benchmark's order.

    Raises:
        ProjectError: When a name or pattern matches no Task the Benchmark lists.
    """
    tasks = benchmark_tasks(project, benchmark)
    removed = _matching(tasks, patterns, f"in Benchmark {benchmark!r}", suggest_init=False)
    _write_tasks(project, benchmark, [name for name in tasks if name not in removed])
    return [name for name in tasks if name in removed]


def _matching(
    names: Sequence[str], patterns: Sequence[str], where: str, *, suggest_init: bool
) -> list[str]:
    """The names each pattern matches, in pattern order and without repeats.

    Returns:
        The matched names.

    Raises:
        ProjectError: When a pattern matches nothing.
    """
    matched: list[str] = []
    for pattern in patterns:
        found = fnmatch.filter(names, pattern)
        if not found:
            hint = (
                f" Create it with `plural task init {pattern}`."
                if suggest_init and not _is_pattern(pattern)
                else ""
            )
            raise ProjectError(f"No Task {pattern!r} {where}.{hint}")
        matched.extend(name for name in found if name not in matched)
    return matched


def _is_pattern(value: str) -> bool:
    return any(character in value for character in "*?[")


def _write_tasks(project: Project, benchmark: str, tasks: list[str]) -> None:
    """Replace the top-level ``tasks`` value, keeping every other line as written."""
    path = project.manifest_path(ResourceRef(BENCHMARK.name, benchmark))
    lines = path.read_text(encoding="utf-8").splitlines()
    block = ["tasks: []"] if not tasks else ["tasks:", *(f"  - {name}" for name in tasks)]
    start = next((index for index, line in enumerate(lines) if line.startswith("tasks:")), None)
    if start is None:
        lines.extend(block)
    else:
        end = start + 1
        while end < len(lines):
            line = lines[end]
            stripped = line.strip()
            if _TOP_LEVEL_KEY.match(line) or (stripped.startswith("#") and not line[0].isspace()):
                break
            end += 1
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[start:end] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["add_tasks", "benchmark_tasks", "remove_tasks"]
