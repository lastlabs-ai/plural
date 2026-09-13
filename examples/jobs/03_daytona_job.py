"""Validate Daytona configuration; execute only with explicit live opt-in."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import JobStore

with tempfile.TemporaryDirectory(prefix="plural-daytona-job-") as temporary:
    job = build_job(provider="daytona", store=JobStore(Path(temporary)))
    if os.environ.get("PLURAL_RUN_DAYTONA") != "1":
        assert job.plan.trials[0].runtime_provider == "daytona"
        print("Daytona live run gated; set PLURAL_RUN_DAYTONA=1 and DAYTONA_API_KEY")
    else:
        result = job.run()
        assert all(trial.status == "succeeded" for trial in result.trials)
        print(f"{result.job_id}: Daytona run succeeded")
