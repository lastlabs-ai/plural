"""Plan an independent-attempt sweep without credentials or execution."""

from __future__ import annotations

from _foundation import build_job

job = build_job(attempts=3, concurrency=4)
plan = job.plan
assert plan.trial_count == 6  # one Agent × two tasks × three attempts
assert len({trial.trial_id for trial in plan.trials}) == 6
assert {trial.attempt for trial in plan.trials} == {1, 2, 3}
print(f"{plan.job_id}: {plan.trial_count} trials, concurrency=4")
