"""Write one Task per case, from a Task to copy and a file of cases.

Each case becomes an ordinary Task directory, so it is pushed, versioned, and
listed in a Benchmark like any Task written by hand.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from plural.project.layout import TASK, Project, ProjectError, ResourceRef, check_name
from plural.project.manifests import read_yaml_mapping, write_yaml

CASE_FIELDS = ("initial_state", "info", "metadata", "goals")
"""What a case may set in its Task's ``task.yaml``, besides ``name`` and ``instructions``."""


def read_cases(path: Path) -> list[dict[str, Any]]:
    """Read cases from a JSON Lines file, or from a JSON or YAML list.

    Returns:
        Each case, in file order.

    Raises:
        ProjectError: When the file cannot be read as a list of cases.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectError(f"Cannot read cases from {path}: {exc.strerror or exc}") from exc
    try:
        if path.suffix == ".jsonl":
            cases: Any = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif path.suffix == ".json":
            cases = json.loads(text)
        elif path.suffix in {".yaml", ".yml"}:
            cases = yaml.safe_load(text)
        else:
            raise ProjectError(f"{path}: cases are a .jsonl, .json, or .yaml file.")
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ProjectError(f"{path} is not valid {path.suffix.lstrip('.')}: {exc}") from exc
    if not isinstance(cases, list) or not all(isinstance(item, dict) for item in cases):
        raise ProjectError(f"{path} must hold a list of cases, each an object.")
    return cases


def write_cases(
    project: Project, base: str, cases: list[dict[str, Any]], *, replace: bool = False
) -> list[str]:
    """Write a Task for each case, as a copy of ``base`` with the case's fields.

    A case names its Task and may set ``instructions`` and any of
    :data:`CASE_FIELDS`; everything else comes from ``base``.

    Returns:
        The Task names written, in case order.

    Raises:
        ProjectError: When ``base`` is missing, a case is malformed, or a Task
            already exists and ``replace`` is off.
    """
    source = project.resource_dir(ResourceRef(TASK.name, base))
    if not source.is_dir():
        raise ProjectError(f"No Task named {base!r} in this project to copy cases from.")
    names = [_case_name(case, index) for index, case in enumerate(cases, start=1)]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ProjectError(f"More than one case is named {', '.join(map(repr, repeated))}.")
    if base in names:
        raise ProjectError(f"A case cannot be named {base!r}, the Task it copies.")
    for name, case in zip(names, cases, strict=True):
        unknown = sorted(set(case) - {"name", "instructions", *CASE_FIELDS})
        if unknown:
            raise ProjectError(
                f"Case {name!r} sets {', '.join(unknown)}. A case sets name, instructions, "
                f"and {', '.join(CASE_FIELDS)}."
            )
        target = project.resource_dir(ResourceRef(TASK.name, name))
        if target.exists() and not replace:
            raise ProjectError(
                f"Task {name!r} already exists. Pass --replace to write the cases over it."
            )
    manifest = read_yaml_mapping(source / TASK.manifest)
    for name, case in zip(names, cases, strict=True):
        target = project.resource_dir(ResourceRef(TASK.name, name))
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        _write_case(target, manifest, name, case)
    return names


def _case_name(case: Mapping[str, Any], index: int) -> str:
    name = case.get("name")
    if not isinstance(name, str):
        raise ProjectError(f"Case {index} has no name. Give each case the name of its Task.")
    return check_name(name, "Case")


def _write_case(
    target: Path, manifest: Mapping[str, Any], name: str, case: Mapping[str, Any]
) -> None:
    written = {**manifest, "name": name, **{key: case[key] for key in CASE_FIELDS if key in case}}
    written.pop("title", None)
    if "instructions" in case:
        instructions = target / str(manifest.get("instructions") or "instruction.md")
        instructions.write_text(str(case["instructions"]).rstrip() + "\n", encoding="utf-8")
    write_yaml(target / TASK.manifest, written)


__all__ = ["CASE_FIELDS", "read_cases", "write_cases"]
