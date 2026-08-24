from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from enroute import Dataset, TaskData, TaskDataset, Trace, TraceDataset


def test_task_dataset_roundtrip_preserves_complete_tasks(tmp_path: Path) -> None:
    dataset = TaskDataset(
        name="support-cases",
        version="2.0.0",
        tasks=[
            TaskData(
                task_id="refund",
                input={"message": "refund please"},
                expected={"intent": "refund"},
                metadata={"difficulty": "easy"},
            ),
            TaskData(task_id="shipping", input="where is it?", expected="shipping"),
        ],
        metadata={"owner": "evals"},
    )
    path = tmp_path / "tasks.jsonl"

    dataset.save(path)
    loaded = TaskDataset.load(path)

    assert loaded == dataset
    assert loaded.content_hash == dataset.compute_hash()
    manifest = json.loads((tmp_path / "tasks.jsonl.manifest.json").read_text())
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["hash_algorithm"] == "sha256"
    assert manifest["hash_version"] == "1"


def test_task_dataset_hash_covers_expected_and_metadata() -> None:
    base = TaskData(task_id="one", input={"value": 1}, expected="yes", metadata={"seed": 1})
    changed_expected = base.model_copy(update={"expected": "no"})
    changed_metadata = base.model_copy(update={"metadata": {"seed": 2}})

    assert (
        TaskDataset(name="a", tasks=[base]).content_hash
        != TaskDataset(name="a", tasks=[changed_expected]).content_hash
    )
    assert (
        TaskDataset(name="a", tasks=[base]).content_hash
        != TaskDataset(name="a", tasks=[changed_metadata]).content_hash
    )


def test_task_dataset_hash_preserves_input_order() -> None:
    first = TaskData(task_id="first", input=1)
    second = TaskData(task_id="second", input=2)

    assert (
        TaskDataset(name="a", tasks=[first, second]).content_hash
        != TaskDataset(name="a", tasks=[second, first]).content_hash
    )


def test_supplied_dataset_hashes_are_verified_at_construction() -> None:
    with pytest.raises(ValidationError, match="dataset content hash mismatch"):
        Dataset(name="traces", traces=[Trace(trace_id="one")], content_hash="untrusted")
    with pytest.raises(ValidationError, match="task dataset content hash mismatch"):
        TaskDataset(
            name="tasks",
            tasks=[TaskData(task_id="one", input="x")],
            content_hash="untrusted",
        )


def test_dataset_exposes_current_hash_without_mutating_snapshot_identity() -> None:
    dataset = Dataset(name="traces", traces=[Trace(trace_id="one", task_id="before")])
    snapshot_hash = dataset.content_hash

    dataset.traces[0].task_id = "after"

    assert dataset.content_hash == snapshot_hash
    assert dataset.current_content_hash != snapshot_hash


def test_task_dataset_exposes_current_hash_without_mutating_snapshot_identity() -> None:
    dataset = TaskDataset(
        name="tasks",
        tasks=[TaskData(task_id="one", input={"value": 1})],
    )
    snapshot_hash = dataset.content_hash

    dataset.tasks[0].input["value"] = 2

    assert dataset.content_hash == snapshot_hash
    assert dataset.current_content_hash != snapshot_hash


def test_task_dataset_save_refreshes_identity_after_mutation(tmp_path: Path) -> None:
    dataset = TaskDataset(
        name="tasks",
        tasks=[TaskData(task_id="one", input={"value": 1})],
    )
    original_hash = dataset.content_hash
    dataset.tasks[0].input["value"] = 2
    path = tmp_path / "mutated-tasks.jsonl"

    dataset.save(path)
    loaded = TaskDataset.load(path)

    assert dataset.content_hash != original_hash
    assert dataset.content_hash == dataset.current_content_hash
    assert loaded == dataset


def test_task_dataset_rejects_duplicate_task_ids() -> None:
    with pytest.raises(ValidationError, match="task_id values must be unique"):
        TaskDataset(
            name="duplicates",
            tasks=[
                TaskData(task_id="same", input="first"),
                TaskData(task_id="same", input="second"),
            ],
        )


def test_task_dataset_load_detects_content_tampering(tmp_path: Path) -> None:
    path = tmp_path / "tasks.jsonl"
    TaskDataset(
        name="integrity",
        tasks=[TaskData(task_id="one", input="original", expected="private-label")],
    ).save(path)
    path.write_text(
        TaskData(task_id="one", input="tampered", expected="private-label").model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="content hash mismatch"):
        TaskDataset.load(path)


def test_trace_dataset_alias_is_backward_compatible() -> None:
    assert TraceDataset is Dataset
