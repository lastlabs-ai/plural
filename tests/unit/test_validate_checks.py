"""`plural benchmark validate` and `plural task validate` on the quoting example, clean and
with its traps planted."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "quoting"
CLI = Path(sys.executable).with_name("plural")
SUBSET = (
    "quote-009",
    "quote-013",
    "quote-016",
    "quote-053",
    "quote-004",
    "quote-006",
    "quote-003",
    "quote-005",
    "quote-024",
    "quote-001",
)


def _project(tmp_path: Path, traps: tuple[str, ...]) -> Path:
    project = tmp_path / "quoting"
    if traps:
        subprocess.run(
            [sys.executable, str(EXAMPLE / "traps.py"), str(project), "--enable", ",".join(traps)],
            check=True,
            capture_output=True,
        )
    else:
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    path = project / "benchmarks/quoting/benchmark.yaml"
    benchmark = yaml.safe_load(path.read_text())
    benchmark["tasks"] = [name for name in benchmark["tasks"] if name in SUBSET]
    for category in benchmark["categories"]:
        category["tasks"] = [name for name in category["tasks"] if name in SUBSET]
    path.write_text(yaml.safe_dump(benchmark, sort_keys=False), encoding="utf-8")
    return project


def _check(project: Path, *command: str) -> tuple[int, dict[str, Any]]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("PLURAL_")}
    env["PLURAL_CONFIG_HOME"] = str(project.parent / "config")
    run = subprocess.run(
        [str(CLI), *(command or ("benchmark", "validate", "quoting")), "--json"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run.stdout, run.stderr
    payload = json.loads(run.stdout)
    return run.returncode, payload["checks"]


def _problems(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        line
        for section in result["sections"]
        for line in section["lines"]
        if line["mark"] == "problem"
    ]


def test_a_clean_eval_set_has_nothing_to_fix(tmp_path: Path) -> None:
    code, result = _check(_project(tmp_path, ()))
    assert (code, result["problems"], _problems(result)) == (0, 0, [])
    assert result["tasks"] == len(SUBSET)
    assert result["next_command"] is None
    titles = [section["title"] for section in result["sections"]]
    assert titles == ["Graders", "Leaks", "Trust"]
    trust = result["sections"][2]["lines"]
    assert any("local Runtime, so Trials are unverified" in line["text"] for line in trust)


def test_validate_finds_the_planted_grader_and_leak_problems(tmp_path: Path) -> None:
    code, result = _check(_project(tmp_path, ("unit-bug", "broken-check", "leaked-key")))
    assert code == 1
    problems = _problems(result)
    found = {(task, line["text"]) for line in problems for task in line["tasks"]}

    assert {task for task, text in found if "price_correct" in text} == {"quote-016", "quote-053"}
    assert any(task == "quote-024" and "noop passes" in text for task, text in found)
    assert any(task == "quote-009" and "answer key" in text for task, text in found)
    assert result["problems"] == len(problems)
    assert len({line["text"] for line in problems if "quote-009" in line["tasks"]}) == 1
    assert result["next_command"].startswith("plural task validate")


def test_a_second_check_reuses_the_saved_results(tmp_path: Path) -> None:
    project = _project(tmp_path, ("broken-check",))
    first = _check(project)
    saved = sorted((project / ".plural/checks").glob("*.json"))
    assert len(saved) == len(SUBSET)
    stamps = [path.stat().st_mtime_ns for path in saved]
    assert _check(project) == first
    assert [path.stat().st_mtime_ns for path in saved] == stamps


def test_task_validate_checks_one_task_and_files_only_skips_the_probes(tmp_path: Path) -> None:
    project = _project(tmp_path, ("broken-check",))
    code, result = _check(project, "task", "validate", "quote-024")
    assert code == 1
    assert result["tasks"] == 1
    assert any("noop passes" in line["text"] for line in _problems(result))
    env = {key: value for key, value in os.environ.items() if not key.startswith("PLURAL_")}
    env["PLURAL_CONFIG_HOME"] = str(project.parent / "config")
    files_only = subprocess.run(
        [str(CLI), "task", "validate", "quote-001", "--no-probes", "--json"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert files_only.returncode == 0, files_only.stderr
    assert "checks" not in json.loads(files_only.stdout)
    assert not (project / ".plural/checks/quote-001@1.0.0.json").exists()


@pytest.mark.live
@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("PLURAL_RUN_DOCKER_TESTS") != "1",
    reason="set PLURAL_RUN_DOCKER_TESTS=1 to opt in",
)
def test_validate_finds_git_history_in_the_image(tmp_path: Path) -> None:
    _, result = _check(_project(tmp_path, ("git-history",)))
    lines = [line for line in _problems(result) if "quote-013" in line["tasks"]]
    assert any("history the Agent can read" in line["text"] for line in lines)
    assert not any("answer key" in line["text"] for line in lines)
