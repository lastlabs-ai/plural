"""Run a complete credential-free Job with the unsafe local provider."""

from __future__ import annotations

import tempfile
from pathlib import Path

from _foundation import build_job

from plural import JobStore

with tempfile.TemporaryDirectory(prefix="plural-local-job-") as temporary:
    job = build_job(store=JobStore(Path(temporary)))
    result = job.run()
    assert len(result.trials) == 2
    assert all(trial.status == "succeeded" for trial in result.trials)
    assert all(trial.score == 1.0 for trial in result.trials)
    print(f"{result.job_id}: {len(result.trials)} verified offline trials")
