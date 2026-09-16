"""Executable checks for canonical documentation and examples."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from plural import Job
from plural.harness.retrieval import tree_digest
from plural.project import Resolver

ROOT = Path(__file__).resolve().parents[2]
CLI = Path(sys.executable).with_name("plural")


def _run(*command: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_canonical_docs_metadata_links_nav_terms_and_snippets() -> None:
    """Keep the authored docs contract aligned with navigation and public APIs."""
    output = _run(sys.executable, "scripts/check_docs.py")
    assert "internal links are valid" in output


def test_tutorial_python_files_compile_and_dry_run() -> None:
    """Compile both tutorials and resolve their documented Python/YAML Jobs."""
    for directory in ("first-project", "wordle"):
        root = ROOT / "examples" / directory
        for path in sorted(root.rglob("*.py")):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    wordle = ROOT / "examples" / "wordle"
    for reference in ("job.py:job", "job.yaml"):
        _run(str(CLI), "validate", reference, cwd=wordle)
        _run(str(CLI), "run", reference, "--dry-run", cwd=wordle)

    starter = ROOT / "examples" / "first-project"
    _run(str(CLI), "validate", "job.yaml", cwd=starter)
    _run(str(CLI), "run", "job.yaml", "--dry-run", cwd=starter)


def test_wordle_python_yaml_plan_and_materialized_source_are_identical() -> None:
    wordle = ROOT / "examples" / "wordle"
    resolver = Resolver(root=wordle)
    python_job = resolver.load("job.py:job")
    yaml_job = resolver.load("job.yaml")
    assert isinstance(python_job, Job)
    assert isinstance(yaml_job, Job)
    assert python_job.content_hash == yaml_job.content_hash
    assert python_job.plan == yaml_job.plan

    python_source = python_job.source.tasks[0].environment.definition().source
    yaml_source = yaml_job.source.tasks[0].environment.definition().source
    assert python_source is not None
    assert yaml_source is not None
    assert python_source.digest == yaml_source.digest == tree_digest(wordle)


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
