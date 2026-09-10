"""Validate Daytona configuration; execute only with explicit live opt-in."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import Job, JobStore

spec = build_job(provider="daytona")
if os.environ.get("PLURAL_RUN_DAYTONA") != "1":
    assert spec.environment.runtime.image == "python:3.12-slim"
    print("Daytona live run gated; set PLURAL_RUN_DAYTONA=1 and DAYTONA_API_KEY")
else:
    with tempfile.TemporaryDirectory(prefix="plural-daytona-job-") as temporary:
        result = asyncio.run(Job(spec, store=JobStore(Path(temporary))).run())
        assert all(trial.status == "succeeded" for trial in result.trials)
        print(f"{result.job_id}: Daytona run succeeded")
