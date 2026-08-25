"""Benchmarks: run environments across models and produce reports.

Examples:
    >>> from plural.benchmarks import Benchmark, Report
    >>> Benchmark.__name__
    'Benchmark'
"""

from __future__ import annotations

from plural.benchmarks.runner import (
    Benchmark,
    CaseKey,
    CaseResult,
    ModelStats,
    Report,
    RunManifest,
    TaskDatasetMetadata,
    TaskSetMetadata,
    WinRatePair,
)

__all__ = [
    "Benchmark",
    "CaseKey",
    "CaseResult",
    "ModelStats",
    "Report",
    "RunManifest",
    "TaskDatasetMetadata",
    "TaskSetMetadata",
    "WinRatePair",
]
