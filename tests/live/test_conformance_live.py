"""The conformance suite against real providers: Docker locally, Daytona with its key."""

from __future__ import annotations

import os

import pytest

from plural.sandbox.conformance import run_conformance

pytestmark = pytest.mark.live


@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("PLURAL_RUN_DOCKER_TESTS") != "1",
    reason="set PLURAL_RUN_DOCKER_TESTS=1 to opt in",
)
async def test_docker_passes_everything_but_the_allowlist() -> None:
    from plural.sandbox import DockerProvider

    report = await run_conformance(DockerProvider(), image="python:3.12-slim")

    assert report.failures == ("NET-2", "NET-3"), [
        (item.id, item.detail) for item in report.checks if not item.passed
    ]


@pytest.mark.daytona
@pytest.mark.skipif(
    os.environ.get("PLURAL_RUN_DAYTONA_TESTS") != "1",
    reason="set PLURAL_RUN_DAYTONA_TESTS=1 to opt in",
)
async def test_daytona_passes_every_check() -> None:
    from plural.sandbox import DaytonaProvider

    report = await run_conformance(DaytonaProvider())

    assert report.passed, [(item.id, item.detail) for item in report.checks if not item.passed]
