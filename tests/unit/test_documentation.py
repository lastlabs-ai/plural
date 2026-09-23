"""Executable checks for canonical documentation and examples."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from plural import Job
from plural.project import Project, Workspace
from plural.project.runs import RunRequest, plan_run

ROOT = Path(__file__).resolve().parents[2]
CLI = Path(sys.executable).with_name("plural")
TUTORIALS = {
    "first-project": ("support-triage", "scripted"),
    "wordle": ("wordle", "word-list"),
}


def _run(*command: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture
def isolated(tmp_path: Path) -> dict[str, str]:
    """An environment with no stored login and no model credentials."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
    }
    env["PLURAL_CONFIG_HOME"] = str(tmp_path / "config")
    return env


def test_canonical_docs_metadata_links_nav_terms_and_snippets() -> None:
    """Keep the authored docs contract aligned with navigation and public APIs."""
    output = _run(sys.executable, "scripts/check_docs.py")
    assert "internal links are valid" in output


@pytest.mark.parametrize("directory", sorted(TUTORIALS))
def test_tutorial_projects_validate_and_dry_run(directory: str, isolated: dict[str, str]) -> None:
    root = ROOT / "examples" / directory
    benchmark, agent = TUTORIALS[directory]
    for path in sorted(root.rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    _run(str(CLI), "benchmark", "validate", benchmark, cwd=root, env=isolated)
    plan = json.loads(
        _run(
            str(CLI),
            "run",
            "-b",
            benchmark,
            "-a",
            agent,
            "--dry-run",
            "--json",
            cwd=root,
            env=isolated,
        )
    )
    assert plan["source"] == f"benchmark/{benchmark}"
    assert plan["location"] == "local"
    assert plan["trials"]
    assert not (root / ".plural").exists()


def test_wordle_runs_offline_from_the_cli(tmp_path: Path, isolated: dict[str, str]) -> None:
    project = tmp_path / "wordle"
    shutil.copytree(ROOT / "examples" / "wordle", project)
    job = json.loads(
        _run(
            str(CLI), "run", "-b", "wordle", "-a", "word-list", "--json", cwd=project, env=isolated
        )
    )
    assert job["status"] == "succeeded"
    assert [trial["score"] for trial in job["trials"]] == [1.0, 1.0, 1.0]
    shown = json.loads(
        _run(str(CLI), "job", "show", job["job_id"], "--json", cwd=project, env=isolated)
    )
    assert shown["job_id"] == job["job_id"]


@pytest.mark.parametrize("directory", sorted(TUTORIALS))
def test_python_sdk_and_cli_plan_the_same_job(directory: str) -> None:
    benchmark, agent = TUTORIALS[directory]
    workspace = Workspace(Project.find(ROOT / "examples" / directory))

    from_python = Job(workspace.get("benchmark", benchmark), agents=[workspace.get("agent", agent)])
    from_cli = plan_run(workspace, RunRequest(benchmark=benchmark, agent=agent))

    unnumbered = from_cli.spec.model_copy(update={"run_id": None})
    assert unnumbered.content_hash == from_python.spec.content_hash
    assert len(from_cli.job.plan.trials) == len(from_python.plan.trials)


def test_audited_documentation_limits_remain_explicit() -> None:
    runtime = (ROOT / "docs/project/environments.md").read_text(encoding="utf-8")
    reviews = (ROOT / "docs/running/reviews.md").read_text(encoding="utf-8")
    integrations = (ROOT / "docs/reference/integrations.md").read_text(encoding="utf-8")
    fields = (ROOT / "docs/reference/fields.md").read_text(encoding="utf-8")
    api = (ROOT / "docs/reference/api.md").read_text(encoding="utf-8")
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert "Environment secret references as metadata" in runtime
    assert "does not expose the full contracted evidence view" in reviews
    assert "native APIs are not directly executed by Job" in integrations
    assert "post-resolution Pydantic constructor models" in fields
    assert "public `Job` constructor is omitted" in fields
    assert "\n## plural.execution.JobRunner\n" not in api
    assert "\n## plural.jobs.JobSpec\n" not in api
    assert "\n## plural.jobs.TrialSpec\n" not in api
    assert "- project/*.md" not in mkdocs
    assert "- running/*.md" not in mkdocs


def test_support_tutorial_integration() -> None:
    """Run the documented starter against a controlled model transport."""
    output = _run(sys.executable, "scripts/check_docs_starter.py")
    assert "PASS:" in output
