"""Run the complete example in Docker when explicitly enabled."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import JobStore

with tempfile.TemporaryDirectory(prefix="plural-docker-job-") as temporary:
    job = build_job(provider="docker", store=JobStore(Path(temporary)))
    if os.environ.get("PLURAL_RUN_DOCKER") != "1":
        print(f"Docker live run gated; dry plan has {job.plan.trial_count} trials")
    else:
        result = job.run()
        assert all(trial.status == "succeeded" for trial in result.trials)
        print(f"{result.job_id}: Docker run succeeded")
