from __future__ import annotations

import os

import pytest

from plural.sandbox import DaytonaProvider, ExecRequest, NetworkMode, SandboxRequirements

pytestmark = [
    pytest.mark.live,
    pytest.mark.daytona,
    pytest.mark.skipif(
        os.environ.get("PLURAL_RUN_DAYTONA_TESTS") != "1",
        reason="set PLURAL_RUN_DAYTONA_TESTS=1 to opt in",
    ),
]


async def test_daytona_sandbox_lifecycle() -> None:
    provider = DaytonaProvider()
    handle = await provider.create(
        SandboxRequirements(
            image="python:3.12-slim",
            network=NetworkMode.NONE,
            timeout_seconds=120,
        )
    )
    try:
        result = await provider.exec(
            handle,
            ExecRequest(command=("python", "-c", "print('ok')"), timeout_seconds=10),
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == b"ok"
    finally:
        await provider.destroy(handle)
