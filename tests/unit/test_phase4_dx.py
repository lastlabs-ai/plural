from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import yaml
from typer.testing import CliRunner

from plural import Agent, Benchmark, Environment, Harness, Job, Task
from plural.catalog import ModelCatalog, ModelEndpoint, ModelSpec
from plural.cli.main import app
from plural.project import CatalogContext, Resolver, dump, load
from plural.verifiers import DeterministicVerifier

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


def graph() -> tuple[Environment, DeterministicVerifier, Task, Benchmark, Agent, Job]:
    environment = Environment(name="world", version="1.0.0")
    verifier = DeterministicVerifier(name="done", check="python verify.py")
    task = Task(
        name="case",
        instructions="Complete the case.",
        environment=environment,
        verifiers=[verifier],
    )
    benchmark = Benchmark(name="suite", version="1.0.0", tasks=[task])
    agent = Agent(model="openai/gpt-5.6-luna")
    return environment, verifier, task, benchmark, agent, Job(benchmark, agents=[agent])


def test_every_public_concept_round_trips_with_equal_hashes(tmp_path: Path) -> None:
    values = graph()
    for value in values:
        path = tmp_path / f"{type(value).__name__.lower()}.yaml"
        dump(value, path)
        restored = load(path)
        assert type(restored) is type(value)
        assert restored.content_hash == value.content_hash
        if isinstance(value, (Environment, Task, Benchmark, Job)):
            emitted = path.read_text(encoding="utf-8")
            assert "schema_version" not in emitted
            assert "revision:" not in emitted
            assert SERIALIZATION_INTERNAL.search(emitted) is None
    original_job = values[-1]
    restored_job = load(tmp_path / "job.yaml")
    assert isinstance(restored_job, Job)
    assert restored_job.plan == original_job.plan


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


def test_python_reference_and_environment_packaging(tmp_path: Path) -> None:
    (tmp_path / ".pluralignore").write_text("task.yaml\n")
    (tmp_path / "world.py").write_text(
        "from plural import Environment, action\n\n"
        "class World(Environment):\n"
        "    name = 'packaged'\n\n"
        "    @action\n"
        "    def answer(self, value: str) -> str:\n"
        "        return value\n\n"
        "world = World().package(('python', 'adapter.py'))\n"
    )
    (tmp_path / "adapter.py").write_text("print('{}')\n")
    resolver = Resolver(root=tmp_path)
    environment = resolver.load("world.py:world")
    assert isinstance(environment, Environment)
    definition = environment.definition()
    assert definition.actions[0].command == ("python", "adapter.py", "answer")
    assert definition.reset_command == ("python", "adapter.py", "reset")

    task = Task(
        name="case",
        instructions="Answer.",
        environment=environment,
        verifiers=[DeterministicVerifier(name="done", check="python verify.py")],
    )
    resolver.dump(task, "task.yaml")
    restored = resolver.load("task.yaml")
    assert isinstance(restored, Task)
    assert restored.content_hash == task.content_hash


def test_advanced_job_yaml_hides_nested_harness_protocol_names(tmp_path: Path) -> None:
    *_values, original = graph()
    (tmp_path / "harness.py").write_text("print('ok')\n")
    harness = Harness(
        name="custom",
        version="1.0.0",
        command=("python", "harness.py"),
        source=str(tmp_path),
    )
    job = Job(
        original.source,
        agents=[Agent(model="openai/gpt-5.6-luna", harness=harness)],
    )
    path = dump(job, tmp_path / "advanced-job.yaml")
    emitted = path.read_text(encoding="utf-8")
    assert "schema_version" not in emitted
    assert "revision:" not in emitted
    assert SERIALIZATION_INTERNAL.search(emitted) is None
    restored = load(path)
    assert isinstance(restored, Job)
    assert restored.content_hash == job.content_hash
    assert restored.plan == job.plan


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


def test_cli_uses_same_graph_for_validate_inspect_export_and_dry_run(tmp_path: Path) -> None:
    *_values, job = graph()
    source = dump(job, tmp_path / "job.yaml")
    runner = CliRunner()
    validated = runner.invoke(app, ["validate", str(source)])
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.stdout)["content_hash"] == job.content_hash

    inspected = runner.invoke(app, ["inspect", str(source), "--format", "json"])
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspected.stdout)["kind"] == "job"

    exported = tmp_path / "exported.yaml"
    result = runner.invoke(app, ["export", str(source), "--output", str(exported)])
    assert result.exit_code == 0, result.output
    assert load(exported).content_hash == job.content_hash

    planned = runner.invoke(app, ["run", str(source), "--dry-run"])
    assert planned.exit_code == 0, planned.output
    assert json.loads(planned.stdout)["job_id"] == job.plan.job_id

    shown = runner.invoke(app, ["benchmarks", "show", str(tmp_path / "benchmark.yaml")])
    assert shown.exit_code == 2
    dump(job.source, tmp_path / "benchmark.yaml")
    shown = runner.invoke(app, ["benchmarks", "show", str(tmp_path / "benchmark.yaml")])
    assert shown.exit_code == 0, shown.output


def test_cli_effective_catalog_models_and_errors(tmp_path: Path) -> None:
    catalog = tmp_path / "plural.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "catalog": {
                    "models": [
                        {
                            "id": "project/model",
                            "endpoints": [
                                {
                                    "provider": "project-host",
                                    "upstream_id": "model",
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )
    models = CliRunner().invoke(app, ["models", "show", "project/model", "--catalog", str(catalog)])
    assert models.exit_code == 0, models.output
    assert json.loads(models.stdout)["id"] == "project/model"
