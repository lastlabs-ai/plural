"""Benchmark release rules, result aggregation, and publication manifests.

A Benchmark version is a release. It pins Tasks and declares how they are
scored: :mod:`plural.benchmarks.rules`. Results from one release and one
evaluation track are combined by :mod:`plural.benchmarks.results`. A published
release with selected results is described by :mod:`plural.benchmarks.publication`.
"""

from __future__ import annotations

from plural.benchmarks.publication import (
    MANIFEST_SCHEMA,
    PRIVATE_EVALUATION_MATERIAL,
    PUBLIC_ROUTING_FIELDS,
    Disclosure,
    ManifestCategory,
    ManifestConfiguration,
    ManifestExample,
    ManifestResult,
    ManifestTask,
    PublicationManifest,
    release_reference,
)
from plural.benchmarks.results import (
    AttemptEvidence,
    CategoryResult,
    ConfigurationResult,
    MeasuredMean,
    TaskResult,
    TaskSpec,
    Uncertainty,
    aggregate_configuration,
    classify_attempt,
)
from plural.benchmarks.rules import (
    BenchmarkCategory,
    BenchmarkScoring,
    EvaluationTrack,
    TrackConformance,
    check_track_conformance,
)

__all__ = [
    "MANIFEST_SCHEMA",
    "PRIVATE_EVALUATION_MATERIAL",
    "PUBLIC_ROUTING_FIELDS",
    "AttemptEvidence",
    "BenchmarkCategory",
    "BenchmarkScoring",
    "CategoryResult",
    "ConfigurationResult",
    "Disclosure",
    "EvaluationTrack",
    "ManifestCategory",
    "ManifestConfiguration",
    "ManifestExample",
    "ManifestResult",
    "ManifestTask",
    "MeasuredMean",
    "PublicationManifest",
    "TaskResult",
    "TaskSpec",
    "TrackConformance",
    "Uncertainty",
    "aggregate_configuration",
    "check_track_conformance",
    "classify_attempt",
    "release_reference",
]
