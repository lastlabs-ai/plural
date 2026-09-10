"""Export datasets to Hugging Face-style record lists.

Examples:
    >>> from plural.environments.dataset import TraceDataset
    >>> from plural.environments.export.hf import to_huggingface_records
    >>> from plural.tracing.schema import Trace
    >>> recs = to_huggingface_records(TraceDataset.from_traces("d", [Trace(trace_id="1")]))
    >>> recs[0]["trace_id"]
    '1'
"""

from __future__ import annotations

from typing import Any

from plural.environments.dataset import TraceDataset


def to_huggingface_records(dataset: TraceDataset) -> list[dict[str, Any]]:
    """Convert a dataset to a list of HF-friendly dictionaries.

    Args:
        dataset: Source dataset.

    Returns:
        List of flat-ish records suitable for ``datasets.Dataset.from_list``.
    """
    records: list[dict[str, Any]] = []
    for trace in dataset.traces:
        records.append(
            {
                "trace_id": trace.trace_id,
                "environment": trace.environment,
                "environment_version": trace.environment_version,
                "environment_fingerprint": trace.environment_fingerprint,
                "task_id": trace.task_id,
                "model": trace.model,
                "reward": trace.outcome.reward if trace.outcome else None,
                "scores": trace.outcome.scores if trace.outcome else {},
                "labels": trace.outcome.labels if trace.outcome else {},
                "tags": trace.tags,
                "steps": [s.model_dump(mode="json") for s in trace.steps],
                "transitions": [
                    t.model_dump(mode="json") for t in trace.transitions(source="both")
                ],
                "returns": trace.returns(source="both"),
                "initial_state": trace.initial_state,
                "final_state": trace.final_state,
                "metrics": trace.metrics,
                "terminated": trace.terminated,
                "truncated": trace.truncated,
                "metadata": trace.metadata,
                "created_at": trace.created_at.isoformat(),
            }
        )
    return records
