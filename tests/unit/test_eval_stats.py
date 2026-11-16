"""Intervals come from a seeded clustered bootstrap; comparisons are paired with a verdict."""

from __future__ import annotations

import pytest

from plural.benchmarks import AttemptEvidence, BenchmarkScoring, aggregate_configuration
from plural.stats import (
    MIN_SHARED_TASKS,
    clustered_bootstrap,
    compare_configurations,
    paired_bootstrap,
    pass_at_k,
    pass_hat_k,
    seed_for,
)

NAMES = tuple(f"t{index:02d}" for index in range(20))


def _attempts(scores: dict[str, list[float]], **fields: object) -> list[AttemptEvidence]:
    return [
        AttemptEvidence(task=name, status="succeeded", score=value, **fields)  # type: ignore[arg-type]
        for name, values in scores.items()
        for value in values
    ]


def test_the_bootstrap_is_reproducible_and_brackets_the_estimate() -> None:
    tasks = [(1.0, [1.0, 0.0, 1.0]), (1.0, [0.0, 0.0, 1.0]), (2.0, [1.0, 1.0, 1.0])]
    first = clustered_bootstrap(tasks, seed=seed_for("job-1"))
    again = clustered_bootstrap(tasks, seed=seed_for("job-1"))
    other = clustered_bootstrap(tasks, seed=seed_for("job-2"))
    assert first is not None and first == again
    assert other is not None and other.seed != first.seed
    assert first.low <= first.estimate <= first.high
    assert first.estimate == pytest.approx((2 / 3 + 1 / 3 + 2 * 1.0) / 4)
    assert first.resamples == 2_000
    assert clustered_bootstrap([], seed=1) is None


def test_repeated_attempts_narrow_the_interval_no_further_than_tasks_allow() -> None:
    one = clustered_bootstrap([(1.0, [float(i % 2)]) for i in range(20)], seed=3)
    many = clustered_bootstrap([(1.0, [float(i % 2)] * 5) for i in range(20)], seed=3)
    assert one is not None and many is not None
    assert many.high - many.low == pytest.approx(one.high - one.low, abs=0.08)


def test_a_paired_comparison_needs_ten_shared_tasks() -> None:
    a = {name: [1.0] for name in NAMES[: MIN_SHARED_TASKS - 1]}
    b = {name: [0.0] for name in NAMES[: MIN_SHARED_TASKS - 1]}
    few = paired_bootstrap(a, b)
    assert few.verdict == "not_enough_data"
    assert few.delta == 1.0 and few.low is None
    assert "9 shared Tasks, 10 needed" in few.summary


def test_a_clear_difference_is_better_and_noise_is_within_noise() -> None:
    strong = {name: [1.0, 1.0] for name in NAMES}
    weak = {name: [0.0, 1.0] if index % 4 == 0 else [0.0, 0.0] for index, name in enumerate(NAMES)}
    better = paired_bootstrap(strong, weak, seed=11)
    worse = paired_bootstrap(weak, strong, seed=11)
    assert better.verdict == "better" and better.low is not None and better.low > 0
    assert worse.verdict == "worse"
    assert better.probability_better == 1.0
    noisy = {name: [float(index % 2)] for index, name in enumerate(NAMES)}
    shifted = {name: [float((index + 1) % 2)] for index, name in enumerate(NAMES)}
    assert paired_bootstrap(noisy, shifted, seed=11).verdict == "within_noise"
    assert paired_bootstrap(weak, strong, higher_is_better=False, seed=11).verdict == "better"


def test_only_tasks_both_sides_attempted_are_compared() -> None:
    a = {name: [1.0] for name in NAMES}
    b = {name: [0.0] for name in NAMES[:12]} | {"other": [1.0]}
    comparison = paired_bootstrap(a, b, seed=1)
    assert comparison.shared_tasks == 12
    assert comparison.delta == 1.0


def test_configurations_compare_on_their_attempt_scores() -> None:
    good = aggregate_configuration(
        NAMES, _attempts({name: [1.0, 1.0] for name in NAMES}), scoring=BenchmarkScoring()
    )
    bad = aggregate_configuration(
        NAMES, _attempts({name: [0.0, 1.0] for name in NAMES}), scoring=BenchmarkScoring()
    )
    comparison = compare_configurations(good, bad)
    assert comparison.verdict == "better"
    assert comparison.delta == pytest.approx(0.5)
    with pytest.raises(ValueError, match="only the Verifier score"):
        compare_configurations(good, bad, metric="cost")


def test_results_carry_pass_hat_k_and_pass_at_k() -> None:
    scores = {
        name: [1.0, 1.0, 0.0] if index < 10 else [1.0] * 3 for index, name in enumerate(NAMES)
    }
    result = aggregate_configuration(NAMES, _attempts(scores), scoring=BenchmarkScoring())
    assert result.attempts_per_task == 3
    assert result.pass_at_k == 1.0
    assert result.pass_hat_k == 0.5
    assert result.uncertainty.method is not None
    assert "clustered bootstrap" in result.uncertainty.method
    assert pass_hat_k([]) is None and pass_at_k([[False]]) == 0.0


def test_the_integrity_rule_excludes_or_zeroes_critical_attempts_and_keeps_the_raw_score() -> None:
    clean = _attempts({name: [1.0] for name in NAMES[:18]})
    flagged = _attempts({name: [1.0] for name in NAMES[18:]}, integrity_critical=True)
    attempts = [*clean, *flagged]

    reported = aggregate_configuration(NAMES, attempts, scoring=BenchmarkScoring())
    assert (reported.score, reported.integrity_flagged, reported.raw_score) == (1.0, 2, None)

    excluded = aggregate_configuration(
        NAMES, attempts, scoring=BenchmarkScoring(integrity="exclude_critical")
    )
    assert excluded.integrity_flagged == 2
    assert excluded.raw_score == 1.0
    assert excluded.tasks_covered == 18
    assert sum(task.integrity_excluded for task in excluded.tasks) == 2

    zeroed = aggregate_configuration(
        NAMES, attempts, scoring=BenchmarkScoring(integrity="zero_critical")
    )
    assert zeroed.score == pytest.approx(0.9)
    assert zeroed.raw_score == 1.0
    assert zeroed.raw_uncertainty is not None
