"""Drafting Tasks with a model, and reviewing the drafts, without a live model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from plural.model_steps import model_step
from plural.project import Project, Workspace
from plural.project.layout import TASK
from plural.project.task_generation import (
    approve,
    draft_names,
    existing_examples,
    generate,
    next_names,
    read_draft,
    reject,
    write_draft,
)

QUOTING = Path(__file__).resolve().parents[2] / "examples" / "quoting"


class _Model:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def chat(self, **request: Any) -> Any:
        self.requests.append(request)
        content = json.dumps(self.replies.pop(0))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=2_000, completion_tokens=800, cost=None),
        )


def _task(text: str, state: dict[str, Any], category: str = "rush") -> dict[str, Any]:
    return {
        "instructions": text,
        "initial_state_json": json.dumps(state),
        "expected_json": json.dumps({"decision": "quote", "grade": "A36", "tons": 12}),
        "category": category,
        "rationale": "A booked mill.",
        "metrics_exercised": ["delivery_feasible", "price_correct"],
    }


def test_generation_validates_dedupes_and_review_approves(tmp_path: Path) -> None:
    project_root = tmp_path / "quoting"
    shutil.copytree(QUOTING, project_root, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    space = Workspace(Project.at(project_root))
    project = space.project
    benchmark = space.get("benchmark", "quoting")
    categories = {item.id: list(item.tasks) for item in benchmark.categories}
    examples = existing_examples(project, categories, limit=4)
    assert len({item["category"] for item in examples}) == 4
    existing = examples[0]
    booked = {"booked": ["2026-12-02", "2026-12-03"]}
    model = _Model(
        {
            "tasks": [
                _task("Need 12 tons of A36 by Dec 4, sorry for the rush.", booked),
                _task("NEED 12 tons of A36 by Dec 4 -- sorry for the rush!", booked),
                _task("Quote 8 tons of A572-50 for Friday.", {}, "simple"),
                _task("Quote 3 tons of A36.", {"warehouse_size": 9}),
                _task(existing["instructions"], existing["initial_state"]),
            ]
        },
        {"groups": [[0, 1]]},
    )
    card = space.get("scorecard", "steel-quoting")
    with model_step("task-generate", budget_usd=1.0, client=model) as step:
        result = generate(
            step,
            environment=space.get("environment", "quoting"),
            count=5,
            scorecard=card,
            examples=examples,
            categories=sorted(categories),
        )
    prompt = model.requests[0]["messages"][1]["content"]
    assert "price_correct: gate" in prompt and "booked" in prompt and "rush" in prompt
    assert [draft.instructions[:14] for draft in result.drafts] == ["Need 12 tons o"]
    # A State field the Environment doesn't have is caught before anyone reviews it.
    assert len(result.invalid) == 1 and "warehouse_size" in result.invalid[0][1]
    # Same words and state as another draft, an existing Task, or a near-duplicate.
    assert len(result.duplicates) == 3
    assert result.coverage() == {"delivery_feasible": 1, "price_correct": 1}

    (name,) = next_names(project, 1)
    assert name == "quote-061"
    write_draft(project, name, result.drafts[0], environment="quoting", verifiers=["quote-check"])
    assert draft_names(project) == ["quote-061"]
    assert name not in project.names(TASK)
    assert read_draft(project, name)["draft"]["category"] == "rush"
    # A draft is not a Task: no Benchmark runs it and the project doesn't list it.
    assert "quote-061" not in Workspace(Project.at(project_root)).get("benchmark", "quoting").tasks

    approve(project, name, benchmark="quoting")
    task = Workspace(Project.at(project_root)).get("task", name)
    assert task.expected == {"decision": "quote", "grade": "A36", "tons": 12}
    manifest = yaml.safe_load((project_root / "tasks" / name / "task.yaml").read_text())
    assert "draft" not in manifest
    reloaded = Workspace(Project.at(project_root)).get("benchmark", "quoting")
    assert name in {item.task_id for item in reloaded.tasks}
    assert name in next(item for item in reloaded.categories if item.id == "rush").tasks

    write_draft(project, "quote-062", result.drafts[0], environment="quoting", verifiers=[])
    reject(project, "quote-062")
    assert draft_names(project) == []
