"""The machine-readable description of one published Benchmark release.

A manifest is what a reader, or a future router, may rely on: the release and
its Tasks, the evaluation tracks, and the selected results with their
provenance. It is immutable once published and addressed by its digest, so a
consumer can name exactly which evidence it used.

The manifest is public routing metadata. It never carries private evaluation
material: a Task's initial State and reset options, Verifier definitions and
expected answers, resource contents, secrets, or trace contents unless the
publisher disclosed them. It is never placed in an evaluated Agent's context.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from plural.benchmarks.results import MeasuredMean, Uncertainty
from plural.benchmarks.rules import BenchmarkScoring, EvaluationTrack
from plural.common import FrozenModel, content_hash

MANIFEST_SCHEMA: Literal["plural.benchmark-publication/1"] = "plural.benchmark-publication/1"

PUBLIC_ROUTING_FIELDS: tuple[str, ...] = (
    "publication, publisher, release, track, configuration, and result identifiers",
    "Task names, descriptions, categories, applicability, and requirements",
    "score semantics: range, success threshold, weights, and Verifier names and kinds",
    "per-Task and per-category scores, coverage, sample counts, and uncertainty",
    "measured cost and latency with their units and denominators",
    "provenance, evaluation dates, lineage, license, and correction status",
)

PRIVATE_EVALUATION_MATERIAL: tuple[str, ...] = (
    "Task initial State and reset options, which can hold the answer",
    "Verifier definitions, rubrics, and expected outputs",
    "Verifier findings, unless the publisher disclosed them",
    "Task instructions, unless the publisher disclosed them",
    "trace contents, unless the publisher disclosed them",
    "resource contents, secrets, and API keys",
)

Provenance = Literal["plural_executed", "independently_reproduced", "self_reported", "legacy"]
ResultStatus = Literal["accepted", "withdrawn", "superseded"]


def release_reference(slug: str, version: str, digest: str) -> str:
    """Return the immutable reference for one published release.

    Returns:
        A reference of the form ``plural:benchmark/<slug>@<version>#<digest>``.
    """
    return f"plural:benchmark/{slug}@{version}#{digest}"


class Disclosure(FrozenModel):
    """What the publisher chose to make public beyond routing metadata.

    Attributes:
        task_instructions: Publish each Task's instructions.
        verifier_findings: Publish Verifier evidence on representative attempts.
        traces: Publish trace links for representative attempts.
    """

    task_instructions: bool = False
    verifier_findings: bool = False
    traces: bool = False


class ManifestPublication(FrozenModel):
    """Stable identity of the publication across releases."""

    id: str
    slug: str
    title: str
    path: str


class ManifestPublisher(FrozenModel):
    """Who published the release and is attributed for its evidence."""

    account_id: str
    name: str


class ManifestRelease(FrozenModel):
    """The exact Benchmark revision this manifest describes.

    Attributes:
        id: Benchmark revision identifier.
        benchmark_id: Stable Benchmark identifier.
        version: Release version.
        content_hash: Digest of the pinned Tasks and scoring rules.
        published_at: When the release was published, ISO 8601.
        forked_from: Reference of the release this Benchmark was derived from.
        supersedes: Previous release of this publication, when any.
    """

    id: str
    benchmark_id: str
    version: str
    content_hash: str
    published_at: str
    forked_from: str | None = None
    supersedes: str | None = None


class ManifestAbout(FrozenModel):
    """What the Benchmark is for, in the author's words."""

    description: str = ""
    purpose: str = ""
    success: str = ""
    limitations: tuple[str, ...] = ()
    license: str = ""


class ManifestCategory(FrozenModel):
    """A Task category and whether its scores compare across Benchmarks.

    Attributes:
        id: Category id, stable across releases.
        name: Category label.
        description: What its Tasks share.
        taxonomy: Shared classification identifier, when declared.
        tasks: Task ids in the category.
    """

    id: str
    name: str
    description: str = ""
    taxonomy: str | None = None
    tasks: tuple[str, ...] = ()

    @property
    def comparable_across_benchmarks(self) -> bool:
        """Only a shared classification is a claim beyond this Benchmark."""
        return self.taxonomy is not None


class ManifestRequirements(FrozenModel):
    """What running one Task needs."""

    environment: str
    runtime_provider: str | None = None
    network: str | None = None
    tools: tuple[str, ...] = ()
    max_turns: int | None = None
    max_seconds: float | None = None
    max_cost_usd: float | None = None


class ManifestVerifier(FrozenModel):
    """A Verifier's public identity, never its definition."""

    name: str
    kind: str
    weight: float = 1.0


class ManifestTask(FrozenModel):
    """One Task's public description and score semantics.

    Attributes:
        id: Stable Task identifier: the pinned Task content digest.
        name: Task name within the release.
        version: Task version.
        description: What the Task asks, without its answer.
        categories: Category ids.
        weight: Declared weight.
        applicability: Author-declared conditions under which results apply,
            such as ``{"language": "en"}``.
        requirements: What running it needs.
        verifiers: Which Verifiers score it.
        instructions: The Task instructions, only when disclosed.
    """

    id: str
    name: str
    version: str
    description: str = ""
    categories: tuple[str, ...] = ()
    weight: float = 1.0
    applicability: dict[str, Any] = Field(default_factory=dict)
    requirements: ManifestRequirements
    verifiers: tuple[ManifestVerifier, ...] = ()
    instructions: str | None = None


class ManifestConfiguration(FrozenModel):
    """One exact evaluated configuration.

    Model, harness, instructions, and settings stay separate so a reader can
    tell a model result from a system result. A configuration that can call
    more than one model is a ``system``; its score is never attributed to one
    model.

    Attributes:
        id: Configuration digest: the Agent definition's content hash.
        label: Readable name.
        group: Related configurations share a group; their scores stay separate.
        kind: ``"model"`` for one fixed model, ``"system"`` otherwise.
        model: Configured primary model.
        provider: Configured provider, when pinned.
        fallback_models: Configured fallbacks.
        models_used: Models and providers actually used, with call counts.
        harness: Harness name, or ``None`` for the built-in loop.
        harness_version: Harness version, when a harness is used.
        instructions_digest: Digest of the Agent instructions, when present.
        settings: Inference settings.
    """

    id: str
    label: str
    group: str
    kind: Literal["model", "system"]
    model: str
    provider: str | None = None
    fallback_models: tuple[str, ...] = ()
    models_used: tuple[dict[str, Any], ...] = ()
    harness: str | None = None
    harness_version: str | None = None
    instructions_digest: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ManifestTaskResult(FrozenModel):
    """One Task's result within one published result."""

    task_id: str
    score: float | None = None
    valid: int = 0
    attempts: int = 0
    successes: int = 0
    success_rate: float | None = None
    agent_failures: int = 0
    infrastructure_errors: int = 0


class ManifestCategoryResult(FrozenModel):
    """One category's result within one published result."""

    id: str
    score: float | None = None
    coverage: float = 0
    tasks_covered: int = 0
    tasks_total: int = 0


class ManifestExample(FrozenModel):
    """One representative attempt, chosen to show a success or a failure.

    Examples illustrate a result; they never select which attempts count.

    Attributes:
        task_id: Task id.
        attempt: Attempt index.
        outcome: How the attempt ended.
        score: Verifier-derived score, when one was produced.
        stop_reason: How the episode ended.
        findings: Verifier evidence, only when the publisher disclosed it.
    """

    task_id: str
    attempt: int
    outcome: str
    score: float | None = None
    stop_reason: str | None = None
    findings: tuple[str, ...] = ()


class ManifestReproducibility(FrozenModel):
    """What someone needs to rerun a result on the same terms."""

    evaluation_ids: tuple[str, ...] = ()
    release_content_hash: str
    track_rules_hash: str
    configuration_hash: str
    task_hashes: tuple[str, ...] = ()


class ManifestResult(FrozenModel):
    """One selected result, bound to an exact release, track, and configuration.

    Attributes:
        id: Result identifier.
        track: Track reference, ``id@version``.
        configuration: Configuration id.
        provenance: Who ran the evaluation and how it was checked.
        status: ``accepted``, ``withdrawn``, or ``superseded`` by a correction.
        supersedes: Result this one corrects.
        status_reason: Why it was withdrawn or corrected.
        submitted_by: Account that contributed the result.
        evaluated_from: Start of the contributing evaluations, ISO 8601.
        evaluated_to: End of the contributing evaluations, ISO 8601.
        eligible: Whether it met the release's ranking requirements.
        ineligible_reasons: Why not, when it did not.
    """

    id: str
    track: str
    configuration: str
    provenance: Provenance
    status: ResultStatus = "accepted"
    supersedes: str | None = None
    status_reason: str | None = None
    submitted_by: ManifestPublisher
    evaluated_from: str | None = None
    evaluated_to: str | None = None
    score: float | None = None
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)
    coverage: float = 0
    complete_coverage: float = 0
    success_rate: float | None = None
    completion_rate: float | None = None
    cost: MeasuredMean
    latency: MeasuredMean
    outcomes: dict[str, int] = Field(default_factory=dict)
    eligible: bool = False
    ineligible_reasons: tuple[str, ...] = ()
    tasks: tuple[ManifestTaskResult, ...] = ()
    categories: tuple[ManifestCategoryResult, ...] = ()
    examples: tuple[ManifestExample, ...] = ()
    reproducibility: ManifestReproducibility


class ManifestBoundary(FrozenModel):
    """The explicit line between routing metadata and private evaluation material."""

    public_routing_fields: tuple[str, ...] = PUBLIC_ROUTING_FIELDS
    private_evaluation_material: tuple[str, ...] = PRIVATE_EVALUATION_MATERIAL


class PublicationManifest(FrozenModel):
    """Everything published for one Benchmark release.

    The model checks its own consistency: every result names a track and a
    configuration in the manifest, every Task and category a result reports
    exists, and every identifier is unique.
    """

    schema_version: Literal["plural.benchmark-publication/1"] = MANIFEST_SCHEMA
    publication: ManifestPublication
    publisher: ManifestPublisher
    release: ManifestRelease
    status: Literal["published", "withdrawn"] = "published"
    about: ManifestAbout = Field(default_factory=ManifestAbout)
    scoring: BenchmarkScoring
    default_view: Literal["models", "agents"] = "agents"
    categories: tuple[ManifestCategory, ...] = ()
    tasks: tuple[ManifestTask, ...] = Field(min_length=1)
    tracks: tuple[EvaluationTrack, ...] = ()
    configurations: tuple[ManifestConfiguration, ...] = ()
    results: tuple[ManifestResult, ...] = ()
    disclosure: Disclosure = Field(default_factory=Disclosure)
    boundary: ManifestBoundary = Field(default_factory=ManifestBoundary)

    @model_validator(mode="after")
    def _consistent(self) -> PublicationManifest:
        def unique(values: list[str], what: str) -> set[str]:
            if len(values) != len(set(values)):
                raise ValueError(f"Manifest {what} identifiers must be unique.")
            return set(values)

        task_ids = unique([task.id for task in self.tasks], "Task")
        category_ids = unique([category.id for category in self.categories], "category")
        tracks = unique([track.reference for track in self.tracks], "track")
        configurations = unique(
            [configuration.id for configuration in self.configurations], "configuration"
        )
        results = unique([result.id for result in self.results], "result")
        for category in self.categories:
            unknown = set(category.tasks) - task_ids
            if unknown:
                raise ValueError(f"Category {category.id!r} names unknown Tasks.")
        for task in self.tasks:
            if set(task.categories) - category_ids:
                raise ValueError(f"Task {task.name!r} names an unknown category.")
        for result in self.results:
            if result.track not in tracks:
                raise ValueError(f"Result {result.id!r} names unknown track {result.track!r}.")
            if result.configuration not in configurations:
                raise ValueError(f"Result {result.id!r} names an unknown configuration.")
            if result.supersedes is not None and result.supersedes not in results:
                raise ValueError(f"Result {result.id!r} corrects a result not in the manifest.")
            if {item.task_id for item in result.tasks} - task_ids:
                raise ValueError(f"Result {result.id!r} reports an unknown Task.")
            if {item.id for item in result.categories} - category_ids:
                raise ValueError(f"Result {result.id!r} reports an unknown category.")
            if {item.task_id for item in result.examples} - task_ids:
                raise ValueError(f"Result {result.id!r} shows an example of an unknown Task.")
            if not self.disclosure.verifier_findings and any(
                item.findings for item in result.examples
            ):
                raise ValueError(
                    f"Result {result.id!r} includes Verifier findings the publisher "
                    "did not disclose."
                )
            if result.reproducibility.release_content_hash != self.release.content_hash:
                raise ValueError(f"Result {result.id!r} was computed for a different release.")
        return self

    @property
    def digest(self) -> str:
        """Content digest of the manifest; changes whenever any field does."""
        return content_hash(self.model_dump(mode="json"))

    @property
    def reference(self) -> str:
        """Immutable reference a consumer records when it relies on this evidence."""
        return release_reference(self.publication.slug, self.release.version, self.digest)


__all__ = [
    "MANIFEST_SCHEMA",
    "PRIVATE_EVALUATION_MATERIAL",
    "PUBLIC_ROUTING_FIELDS",
    "Disclosure",
    "ManifestAbout",
    "ManifestBoundary",
    "ManifestCategory",
    "ManifestCategoryResult",
    "ManifestConfiguration",
    "ManifestExample",
    "ManifestPublication",
    "ManifestPublisher",
    "ManifestRelease",
    "ManifestRequirements",
    "ManifestReproducibility",
    "ManifestResult",
    "ManifestTask",
    "ManifestTaskResult",
    "ManifestVerifier",
    "PublicationManifest",
    "Provenance",
    "release_reference",
]
