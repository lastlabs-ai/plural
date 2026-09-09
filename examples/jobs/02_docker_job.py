"""Run the complete example in Docker when explicitly enabled."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import Job, JobStore

spec = build_job(provider="docker")
if os.environ.get("PLURAL_RUN_DOCKER") != "1":
    print(f"Docker live run gated; dry plan has {spec.plan().trial_count} trials")
else:
    with tempfile.TemporaryDirectory(prefix="plural-docker-job-") as temporary:
        result = asyncio.run(Job(spec, store=JobStore(Path(temporary))).run())
        assert all(trial.status == "succeeded" for trial in result.trials)
        print(f"{result.job_id}: Docker run succeeded")
