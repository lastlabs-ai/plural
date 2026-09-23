from __future__ import annotations

import pytest
from pydantic import ValidationError

from plural import (
    Benchmark,
    BenchmarkCategory,
    BenchmarkScoring,
    Environment,
    EvaluationTrack,
    ExecutionLimits,
    Runtime,
    Task,
)
from plural.benchmarks import (
    AttemptEvidence,
    PublicationManifest,
    TrackConformance,
    aggregate_configuration,
    check_track_conformance,
    classify_attempt,
)
from plural.benchmarks.publication import (
    ManifestConfiguration,
    ManifestPublication,
    ManifestPublisher,
    ManifestRelease,
    ManifestReproducibility,
    ManifestRequirements,
    ManifestResult,
    ManifestTask,
)
from plural.benchmarks.results import MeasuredMean
from plural.common import content_hash
from plural.verifiers import DeterministicVerifier, RubricCriterion


def task(name: str, *, max_turns: int = 8) -> Task:
    return Task(
        name=name,
        instructions=f"Solve {name}.",
        environment=Environment(
            name="world",
            version="1.0.0",
            runtime=Runtime.docker(),
            limits=ExecutionLimits(max_turns=max_turns),
        ),
        verifiers=(
            DeterministicVerifier(
                name="solved",
                check="python verifier.py",
                criteria=(RubricCriterion(name="correct", description="Correct."),),
            ),
        ),
    )


def attempt(task_name: str, score: float | None, **fields: object) -> AttemptEvidence:
    status = fields.pop("status", "succeeded" if score is not None else "failed")
    return AttemptEvidence(task=task_name, score=score, status=str(status), **fields)  # type: ignore[arg-type]


SPECS = ("a", "b")


def test_release_fields_leave_existing_benchmark_digests_unchanged() -> None:
    plain = Benchmark(name="suite", version="1.0.0", tasks=(task("a"),))
    legacy = content_hash(
        {
            "name": "suite",
            "version": "1.0.0",
            "task_pins": plain.task_pins,
            "primary_metric": "score",
            "description": "",
            "metadata": {},
        }
    )
    assert plain.content_hash == legacy
    assert plain._definition().content_hash == legacy
    released = Benchmark(
        name="suite",
        version="1.0.0",
        tasks=(task("a"),),
        purpose="Measure puzzle solving.",
    )
    assert released.content_hash != legacy
    assert plain.diff(released).configuration_changes["purpose"] == (
        "",
        "Measure puzzle solving.",
    )


def test_release_rules_must_name_tasks_and_tracks_in_the_release() -> None:
    with pytest.raises(ValidationError, match="not in the Benchmark: missing"):
        Benchmark(
            name="suite",
            version="1.0.0",
            tasks=(task("a"),),
            categories=(BenchmarkCategory(id="easy", name="Easy", tasks=("missing",)),),
        )
    with pytest.raises(ValidationError, match="task_weights names"):
        Benchmark(
            name="suite",
            version="1.0.0",
            tasks=(task("a"),),
            scoring=BenchmarkScoring(task_weights={"missing": 2}),
        )
    with pytest.raises(ValidationError, match="no track has kind 'models'"):
        Benchmark(
            name="suite",
            version="1.0.0",
            tasks=(task("a"),),
            tracks=(EvaluationTrack(id="open", name="Open", kind="agents"),),
            default_view="models",
        )
    with pytest.raises(ValidationError, match="caps turns at 4"):
        Benchmark(
            name="suite",
            version="1.0.0",
            tasks=(task("a", max_turns=8),),
            tracks=(EvaluationTrack(id="open", name="Open", kind="agents", max_turns=4),),
        )
    with pytest.raises(ValidationError, match="one harness at most"):
        EvaluationTrack(
            id="controlled",
            name="Controlled",
            kind="models",
            instructions="none",
            harnesses=("codex", "claude-code"),
        )


def test_track_versions_have_a_rules_digest_and_check_configurations() -> None:
    controlled = EvaluationTrack(
        id="controlled", name="Controlled", kind="models", instructions="none", temperature=0
    )
    renamed = controlled.model_copy(update={"name": "Renamed"})
    assert renamed.rules_hash == controlled.rules_hash
    assert controlled.model_copy(update={"attempts": 3}).rules_hash != controlled.rules_hash
    assert controlled.reference == "controlled@1.0.0"

    assert check_track_conformance(controlled, TrackConformance(model="m", temperature=0)) == []
    issues = check_track_conformance(
        controlled,
        TrackConformance(
            model="m",
            fallback_models=("n",),
            harness="codex",
            instructions="Think hard.",
            temperature=0.7,
        ),
    )
    assert len(issues) == 4
    assert any("falls back to n" in issue for issue in issues)


def test_attempts_are_averaged_within_tasks_before_tasks_are_combined() -> None:
    attempts = [attempt("a", 1.0), attempt("a", 1.0), attempt("a", 1.0), attempt("b", 0.0)]
    result = aggregate_configuration(
        SPECS, attempts, scoring=BenchmarkScoring(), required_attempts=1
    )
    naive_trial_mean = sum(item.score or 0 for item in attempts) / len(attempts)
    assert naive_trial_mean == 0.75
    assert result.score == 0.5
    weighted = aggregate_configuration(
        SPECS,
        attempts,
        scoring=BenchmarkScoring(task_weights={"b": 3}),
        required_attempts=1,
    )
    assert weighted.score == pytest.approx(0.25)


def test_every_attempt_counts_so_the_best_one_is_never_selected() -> None:
    result = aggregate_configuration(
        ("a",),
        [attempt("a", 1.0), attempt("a", 0.0), attempt("a", 0.5)],
        scoring=BenchmarkScoring(),
        required_attempts=3,
    )
    assert result.score == pytest.approx(0.5)
    assert result.tasks[0].score_max == 1.0
    assert result.tasks[0].successes == 1


def test_step_rewards_are_not_an_input_to_scores() -> None:
    assert "reward" not in " ".join(AttemptEvidence.model_fields)
    with pytest.raises(ValidationError):
        AttemptEvidence(task="a", status="succeeded", score=1.0, step_reward_total=9)  # type: ignore[call-arg]


def test_failures_are_classified_and_handled_by_declared_rules() -> None:
    assert classify_attempt(attempt("a", None, stop_reason="max_turns")) == "agent_failure"
    assert classify_attempt(attempt("a", None, error_code="harness_failed")) == "agent_failure"
    assert classify_attempt(attempt("a", None, error_code="provider_unavailable")) == (
        "infrastructure_error"
    )
    assert classify_attempt(attempt("a", None, status="cancelled")) == "cancelled"
    assert classify_attempt(attempt("a", None, status="running")) == "pending"

    attempts = [
        attempt("a", 1.0),
        attempt("a", None, stop_reason="max_cost"),
        attempt("b", None, error_code="runtime_unavailable"),
    ]
    zero = aggregate_configuration(SPECS, attempts, scoring=BenchmarkScoring())
    assert zero.tasks[0].score == 0.5
    assert zero.tasks[1].covered is False
    assert zero.coverage == 0.5
    assert zero.score == 0.5
    assert zero.completion_rate == pytest.approx(1 / 3)
    assert zero.eligible is False
    assert "requires 100%" in zero.ineligible_reasons[0]

    excluded = aggregate_configuration(
        SPECS, attempts, scoring=BenchmarkScoring(agent_failure="exclude")
    )
    assert excluded.tasks[0].score == 1.0


def test_official_ranking_needs_declared_coverage_and_no_pending_attempts() -> None:
    scoring = BenchmarkScoring(coverage_required=0.5)
    partial = aggregate_configuration(SPECS, [attempt("a", 1.0)], scoring=scoring)
    assert partial.eligible is True
    pending = aggregate_configuration(
        SPECS, [attempt("a", 1.0), attempt("b", None, status="running")], scoring=scoring
    )
    assert pending.eligible is False
    assert "still pending" in pending.ineligible_reasons[0]
    blocked = aggregate_configuration(
        SPECS,
        [attempt("a", 1.0), attempt("b", 1.0)],
        scoring=BenchmarkScoring(),
        blocking_issues=("Legacy result without a track.",),
    )
    assert blocked.eligible is False
    too_few = aggregate_configuration(
        SPECS,
        [attempt("a", 1.0), attempt("b", 1.0)],
        scoring=BenchmarkScoring(),
        required_attempts=2,
    )
    assert too_few.eligible is False
    assert too_few.coverage == 1.0
    assert too_few.complete_coverage == 0.0


def test_uncertainty_is_unknown_until_there_are_enough_tasks() -> None:
    few = aggregate_configuration(
        SPECS, [attempt("a", 1.0), attempt("b", 0.0)], scoring=BenchmarkScoring()
    )
    assert few.uncertainty.low is None
    assert "at least 5" in (few.uncertainty.unavailable_reason or "")

    specs = tuple(str(index) for index in range(6))
    scores = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    many = aggregate_configuration(
        specs,
        [attempt(str(index), score) for index, score in enumerate(scores)],
        scoring=BenchmarkScoring(),
    )
    assert many.uncertainty.low is not None and many.uncertainty.high is not None
    assert many.uncertainty.low < (many.score or 0) < many.uncertainty.high
    assert many.uncertainty.high <= 1.0
    assert many.uncertainty.sample_size == 6
    assert "normal-approximation" in (many.uncertainty.method or "")


def test_cost_and_latency_use_attempts_that_ran_and_disclose_gaps() -> None:
    result = aggregate_configuration(
        SPECS,
        [
            attempt("a", 1.0, cost_usd=0.02, latency_seconds=4.0),
            attempt("b", 0.0),
            attempt("b", None, error_code="provider_unavailable", cost_usd=5.0),
        ],
        scoring=BenchmarkScoring(),
    )
    assert result.cost.value == pytest.approx(0.02)
    assert result.cost.unit == "USD per attempt"
    assert (result.cost.measured, result.cost.attempts) == (1, 2)
    assert result.cost.complete is False
    assert result.latency.unit == "seconds per attempt"


def test_categories_are_scored_with_the_release_rules() -> None:
    categories = (
        BenchmarkCategory(id="easy", name="Easy", tasks=("a",)),
        BenchmarkCategory(id="hard", name="Hard", tasks=("b",), taxonomy="plural:reasoning"),
    )
    result = aggregate_configuration(
        ("a", "b"),
        [attempt("a", 1.0), attempt("b", 0.0)],
        scoring=BenchmarkScoring(),
        categories=categories,
    )
    assert [(item.id, item.score) for item in result.categories] == [
        ("easy", 1.0),
        ("hard", 0.0),
    ]
    assert result.categories[1].taxonomy == "plural:reasoning"


def test_task_agent_view_never_carries_benchmark_scoring() -> None:
    benchmark = Benchmark(
        name="suite",
        version="1.0.0",
        tasks=(task("a"),),
        scoring=BenchmarkScoring(task_weights={"a": 3}),
        categories=(BenchmarkCategory(id="easy", name="Easy", tasks=("a",)),),
    )
    payload = str(benchmark._definition().tasks[0].public_payload)
    assert "task_weights" not in payload
    assert "easy" not in payload
    assert "score" not in payload


def _manifest(**overrides: object) -> PublicationManifest:
    result = ManifestResult(
        id="res_1",
        track="controlled@1.0.0",
        configuration="sha256:agent",
        provenance="plural_executed",
        submitted_by=ManifestPublisher(account_id="acc", name="Ada"),
        cost=MeasuredMean(unit="USD per attempt"),
        latency=MeasuredMean(unit="seconds per attempt"),
        reproducibility=ManifestReproducibility(
            release_content_hash="sha256:release",
            track_rules_hash="sha256:rules",
            configuration_hash="sha256:agent",
        ),
    )
    values: dict[str, object] = {
        "publication": ManifestPublication(id="pub", slug="wordle", title="Wordle", path="/p"),
        "publisher": ManifestPublisher(account_id="acc", name="Ada"),
        "release": ManifestRelease(
            id="rev",
            benchmark_id="bmk",
            version="1.0.0",
            content_hash="sha256:release",
            published_at="2026-09-22T00:00:00Z",
        ),
        "scoring": BenchmarkScoring(),
        "tasks": (
            ManifestTask(
                id="sha256:task",
                name="a",
                version="0.1.0",
                requirements=ManifestRequirements(environment="world"),
            ),
        ),
        "tracks": (
            EvaluationTrack(id="controlled", name="Controlled", kind="models", instructions="none"),
        ),
        "configurations": (
            ManifestConfiguration(
                id="sha256:agent", label="Model", group="model", kind="model", model="m"
            ),
        ),
        "results": (result,),
    }
    values.update(overrides)
    return PublicationManifest.model_validate(values)


def test_manifest_is_consistent_addressable_and_states_its_boundary() -> None:
    manifest = _manifest()
    assert manifest.reference == f"plural:benchmark/wordle@1.0.0#{manifest.digest}"
    assert manifest.digest.startswith("sha256:")
    assert manifest.disclosure.task_instructions is False
    assert any("initial State" in item for item in manifest.boundary.private_evaluation_material)
    assert manifest.tasks[0].instructions is None

    with pytest.raises(ValidationError, match="unknown track"):
        _manifest(tracks=())
    with pytest.raises(ValidationError, match="different release"):
        _manifest(
            release=ManifestRelease(
                id="rev",
                benchmark_id="bmk",
                version="1.0.0",
                content_hash="sha256:other",
                published_at="2026-09-22T00:00:00Z",
            )
        )
    renamed = _manifest(publisher=ManifestPublisher(account_id="acc", name="Grace"))
    assert renamed.digest != manifest.digest
