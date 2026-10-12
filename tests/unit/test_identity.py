"""Revision identity: the shared vectors every SDK must reproduce, and the rules behind them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from project_fixtures import write_project

from plural.harness.retrieval import tree_digest
from plural.identity import canonical_json, revision_hash
from plural.project import Project, ResourceRef, Workspace

VECTORS = json.loads(
    (Path(__file__).parents[2] / "spec/identity/vectors.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", VECTORS["canonical_json"], ids=lambda case: case["name"])
def test_canonical_json_vectors(case: dict[str, str]) -> None:
    assert canonical_json(json.loads(case["input"])) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["revision_hash"], ids=lambda case: case["name"])
def test_revision_hash_vectors(case: dict[str, object]) -> None:
    content = case["content"]
    assert isinstance(content, dict)
    assert revision_hash(str(case["kind"]), content) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["tree_digest"], ids=lambda case: case["name"])
def test_tree_digest_vectors(case: dict[str, object], tmp_path: Path) -> None:
    files = case["files"]
    assert isinstance(files, dict)
    for relative, body in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    assert tree_digest(tmp_path) == case["expected"]


def test_canonical_json_rejects_values_json_cannot_hold() -> None:
    for value in (float("nan"), float("inf"), {1: "x"}, object()):
        with pytest.raises(ValueError):
            canonical_json(value)


def _hashes(project: Project) -> dict[str, str]:
    workspace = Workspace(project)
    return {
        f"{kind}/{name}": workspace.load(ResourceRef(kind, name)).content_hash
        for kind, name in (
            ("environment", "queue"),
            ("verifier", "resolved"),
            ("task", "refund"),
            ("agent", "baseline"),
            ("benchmark", "basics"),
        )
    }


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


def test_versions_and_titles_label_a_revision_without_changing_its_hash(tmp_path: Path) -> None:
    project = write_project(tmp_path / "desk")
    before = _hashes(project)
    for manifest in (
        "environments/queue/environment.yaml",
        "verifiers/resolved/verifier.yaml",
        "tasks/refund/task.yaml",
        "benchmarks/basics/benchmark.yaml",
    ):
        _replace(project.root / manifest, "version: 0.1.0", "version: 2.0.0")
    _replace(
        project.root / "tasks/refund/task.yaml", "name: refund", "name: refund\ntitle: Refunds"
    )
    assert _hashes(project) == before


def test_a_content_change_moves_every_dependent_and_nothing_else(tmp_path: Path) -> None:
    project = write_project(tmp_path / "desk")
    before = _hashes(project)
    _replace(project.root / "environments/queue/README.md", "resolves each one", "closes each one")
    after = _hashes(project)
    changed = {ref for ref in before if before[ref] != after[ref]}
    assert changed == {"environment/queue", "task/refund", "benchmark/basics"}
