"""Run, resume without rerunning success, then verifier-only regrade."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from _foundation import build_job

from plural import Job, JobStore


async def main() -> None:
    """Exercise durable local lifecycle operations."""
    with tempfile.TemporaryDirectory(prefix="plural-resume-") as temporary:
        docker = os.environ.get("PLURAL_RUN_DOCKER") == "1"
        spec = build_job(provider="docker" if docker else "local")
        store = JobStore(Path(temporary))
        first = await Job(spec, store=store).run()
        resumed = await Job(spec, store=store).run(resume=True)
        assert resumed == first
        if docker:
            regraded = await Job(spec, store=store).regrade()
            assert all(item.receipt.source_receipt_hash for item in regraded.trials)
            assert all(item.reward == 1.0 for item in regraded.trials)
            print(f"{first.job_id}: resumed and regraded {len(first.trials)} Docker trials")
        else:
            print(
                f"{first.job_id}: resumed {len(first.trials)} local trials; "
                "regrade gated because local cannot enforce verifier network isolation"
            )


asyncio.run(main())
