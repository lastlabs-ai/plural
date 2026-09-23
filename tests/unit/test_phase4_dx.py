from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural import Agent, Environment, Job
from plural.catalog import CatalogContext, ModelCatalog, ModelEndpoint, ModelSpec
from plural.cli.main import app
from plural.project import KINDS, ResourceRef, Workspace
from plural.project.runs import RunRequest, plan_run
from plural.project.templates import project_scaffold, resource_scaffold

ROOT = Path(__file__).resolve().parents[2]
STALE_PUBLIC_API = re.compile(
    r"\b(?:Agent|Environment|Task|Benchmark|Job|Verifier)(?:Definition|Binding)\b"
    r"|\bWeightedVerifier\b|\bnative_(?:actions|chat)_v1\b"
)
SERIALIZATION_INTERNAL = re.compile(
    r"\b[A-Za-z_]\w*(?:Definition|Binding)\b"
    r"|\bWeightedVerifier\b|\bnative_(?:actions|chat)_v1\b"
    r"|\bschema_version\b|\bprotocol_adapter\b|\bprotocol\b"
    r"|\bdefinition\b|\bbinding\b|\bpackage\b|_v1\b",
    re.IGNORECASE,
)


FIXTURE_REFS = [
    ResourceRef("environment", "queue"),
    ResourceRef("verifier", "resolved"),
    ResourceRef("task", "refund"),
    ResourceRef("harness", "scripted"),
    ResourceRef("agent", "baseline"),
    ResourceRef("benchmark", "basics"),
]


def test_every_resource_loads_with_stable_hashes(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    first, second = Workspace(project), Workspace(project)
    for ref in FIXTURE_REFS:
        loaded = first.load(ref)
        assert loaded.content_hash.startswith("sha256:")
        assert second.load(ref).content_hash == loaded.content_hash, ref
        manifest = (project.resource_dir(ref) / ref.info.manifest).read_text(encoding="utf-8")
        assert "schema_version" not in manifest
        assert SERIALIZATION_INTERNAL.search(manifest) is None, ref


def test_scaffolded_manifests_use_public_words_only(tmp_path: Path) -> None:
    project_scaffold("support-desk").write(tmp_path / "support-desk")
    for kind in KINDS:
        scaffold = resource_scaffold(kind, "example")
        for relative, text in scaffold.files.items():
            if relative.endswith(".yaml"):
                assert "schema_version" not in text
                assert SERIALIZATION_INTERNAL.search(text) is None, (kind.name, relative)


def test_public_docs_and_examples_do_not_regress_to_internal_authoring_api() -> None:
    for source in (ROOT / "examples").rglob("*.py"):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "plural":
                continue
            imported = {alias.name for alias in node.names}
            assert STALE_PUBLIC_API.search(" ".join(sorted(imported))) is None, source

    for source in (ROOT / "docs").rglob("*.md"):
        if source == ROOT / "docs" / "migration" / "v1.md":
            continue
        assert STALE_PUBLIC_API.search(source.read_text(encoding="utf-8")) is None, source


def test_environment_actions_run_through_the_class_reference(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    directory = project.root / "environments/queue"
    (directory / ".pluralignore").write_text("notes.txt\n")
    space = Workspace(project)
    environment = space.load(ResourceRef("environment", "queue")).value
    assert isinstance(environment, Environment)
    definition = environment.definition()
    assert definition.actions[0].command == (
        "python",
        "-m",
        "plural.environments.runner",
        "environment.py:Queue",
        "submit",
    )
    assert definition.reset_command == (
        "python",
        "-m",
        "plural.environments.runner",
        "environment.py:Queue",
        "reset",
    )
    before = environment.content_hash
    (directory / "notes.txt").write_text("scratch\n")
    assert Workspace(project).load(ResourceRef("environment", "queue")).content_hash == before
    (directory / "environment.py").write_text(
        (directory / "environment.py").read_text() + "\n# edited\n"
    )
    assert Workspace(project).load(ResourceRef("environment", "queue")).content_hash != before


def test_runs_plan_the_same_graph_as_python(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    space = Workspace(project)
    benchmark = space.load(ResourceRef("benchmark", "basics")).value
    agent = space.load(ResourceRef("agent", "baseline")).value
    planned = plan_run(space, RunRequest(benchmark="basics", agent="baseline"))
    direct = Job(benchmark, agents=[agent])
    assert planned.spec.model_copy(update={"run_id": None}).content_hash == direct.content_hash
    assert [item.task_id for item in planned.job.plan.trials] == [
        item.task_id for item in direct.plan.trials
    ]


def test_custom_catalog_context_is_explicit_and_validates_provider() -> None:
    custom = ModelSpec(
        id="project/model",
        endpoints=[ModelEndpoint(provider="project-host", upstream_id="model")],
    )
    context = CatalogContext(ModelCatalog(entries=[custom]))
    assert context.agent(model="project/model", provider="project-host").model == "project/model"

    try:
        Agent(model="project/model")
    except ValueError as exc:
        assert "effective ModelCatalog" in str(exc)
    else:
        raise AssertionError("custom model leaked into the bundled catalog")


def test_cli_validate_reports_the_same_hash_as_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(project.root)
    space = Workspace(project)
    runner = CliRunner()
    nouns = {"environment": "env"}
    for ref in FIXTURE_REFS:
        result = runner.invoke(app, [nouns.get(ref.kind, ref.kind), "validate", ref.name, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["content_hash"] == space.load(ref).content_hash


def test_models_list_offline_uses_the_bundled_catalog(
    monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    result = CliRunner().invoke(app, ["models", "list", "--provider", "openai", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["source"] == "catalog"
    ids = [item["id"] for item in payload["models"]]
    assert "openai/gpt-5.6-luna" in ids
    assert all(item.startswith("openai/") for item in ids)
