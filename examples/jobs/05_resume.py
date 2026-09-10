"""Run and resume a durable Job without rerunning successful Trials."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import Job, JobStore


async def main() -> None:
    """Exercise durable local Job resume."""
    with tempfile.TemporaryDirectory(prefix="plural-resume-") as temporary:
        docker = os.environ.get("PLURAL_RUN_DOCKER") == "1"
        spec = build_job(provider="docker" if docker else "local")
        store = JobStore(Path(temporary))
        first = await Job(spec, store=store).run()
        resumed = await Job(spec, store=store).run(resume=True)
        assert resumed == first
        provider = "Docker" if docker else "local"
        print(f"{first.job_id}: resumed {len(first.trials)} {provider} trials")


asyncio.run(main())
