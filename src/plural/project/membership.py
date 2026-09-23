"""Edit which Tasks a Benchmark includes without disturbing the rest of its file."""

from __future__ import annotations

import re

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


def add_task(project: Project, benchmark: str, task: str) -> bool:
    """Add a local Task to a Benchmark.

    Returns:
        Whether the file changed.

    Raises:
        ProjectError: When the Task does not exist in this project.
    """
    if not project.has(ResourceRef(TASK.name, task)):
        raise ProjectError(
            f"No Task named {task!r} in this project. Create it with `plural task init {task}`."
        )
    tasks = benchmark_tasks(project, benchmark)
    if task in tasks:
        return False
    _write_tasks(project, benchmark, [*tasks, task])
    return True


def remove_task(project: Project, benchmark: str, task: str) -> bool:
    """Remove a Task from a Benchmark.

    Returns:
        Whether the file changed.

    Raises:
        ProjectError: When the Benchmark does not list the Task.
    """
    tasks = benchmark_tasks(project, benchmark)
    if task not in tasks:
        raise ProjectError(f"Benchmark {benchmark!r} does not include Task {task!r}.")
    _write_tasks(project, benchmark, [item for item in tasks if item != task])
    return True


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


__all__ = ["add_task", "benchmark_tasks", "remove_task"]
