"""Run and resume a durable Job without rerunning successful Trials."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import JobStore


async def main() -> None:
    """Exercise durable local Job resume."""
    with tempfile.TemporaryDirectory(prefix="plural-resume-") as temporary:
        docker = os.environ.get("PLURAL_RUN_DOCKER") == "1"
        store = JobStore(Path(temporary))
        job = build_job(provider="docker" if docker else "local", store=store)
        first = await job.run_async()
        resumed = await job.run_async(resume=True)
        assert resumed == first
        provider = "Docker" if docker else "local"
        print(f"{first.job_id}: resumed {len(first.trials)} {provider} trials")


asyncio.run(main())
