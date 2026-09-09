"""Run a complete credential-free Job with the unsafe local provider."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import Job, JobStore

with tempfile.TemporaryDirectory(prefix="plural-local-job-") as temporary:
    spec = build_job()
    result = asyncio.run(Job(spec, store=JobStore(Path(temporary))).run())
    assert len(result.trials) == 2
    assert all(trial.status == "succeeded" for trial in result.trials)
    assert all(trial.reward is None for trial in result.trials)
    print(f"{result.job_id}: {len(result.trials)} successful offline trials")
