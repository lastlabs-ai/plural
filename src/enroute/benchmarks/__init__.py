"""Benchmarks: run environments across models and produce reports.

Examples:
    >>> from enroute.benchmarks import Benchmark, Report
    >>> Benchmark.__name__
    'Benchmark'
"""

from __future__ import annotations

from enroute.benchmarks.runner import (
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
