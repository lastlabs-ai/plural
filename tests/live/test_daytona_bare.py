"""An Environment with no Apps on Daytona: the App host runs, signs, and keeps the workspace."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest
import yaml

from plural import Agent, Job
from plural.execution.engine import JobRunner
from plural.execution.store import JobStore
from plural.harness.probes import probe_package
from plural.project import Project, Workspace
from plural.project.checks import plan_checks
from plural.project.layout import ResourceRef
from plural.project.resources import load_harness_directory

pytestmark = [
    pytest.mark.live,
    pytest.mark.daytona,
    pytest.mark.skipif(
        os.environ.get("PLURAL_RUN_DAYTONA_TESTS") != "1",
        reason="set PLURAL_RUN_DAYTONA_TESTS=1 to opt in",
    ),
]

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "bare-files"


def test_a_bare_environment_on_daytona_has_a_signed_isolated_host(tmp_path: Path) -> None:
    root = tmp_path / "bare-files"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".plural"))
    manifest = root / "environments" / "files" / "environment.yaml"
    environment = yaml.safe_load(manifest.read_text())
    environment["runtime"] = {"provider": "daytona"}
    manifest.write_text(yaml.safe_dump(environment))

    space = Workspace(Project.find(root))
    plan = plan_checks(space, ["march-total"], benchmark=None)
    task = space.load(ResourceRef("task", "march-total")).value
    reference = probe_package(
        "reference",
        references={"march-total": Path(plan.references["march-total"])},
        random_steps=0,
        directory=tmp_path / "reference",
    )
    agent = Agent(
        name="probe-reference",
        model="openai/gpt-5.6-luna",
        harness=load_harness_directory(reference),
        auth="none",
    )
    # A minted key makes the run recorded, which is what narrows the network to an
    # allowlist. The reference makes no model call, so the key is never used.
    runner = JobRunner(
        Job(task, agents=[agent], catalog=space.catalog).spec,
        store=JobStore(tmp_path / "jobs"),
        catalog=space.catalog,
        environ={**os.environ, "PLURAL_API_KEY": "pk_unused_user_key"},
        gateway_keys=lambda *_: "pk_unused_" + "x" * 32,
    )
    (trial,) = asyncio.run(runner.run()).trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.score == 1.0
    assert trial.app_isolation == "os_user"
    assert trial.trust is not None
    assert trial.trust.facts.host_report_signed is True
    assert trial.trust.facts.network == "allowlist"
    assert list((tmp_path / "jobs").glob("**/artifacts/workspace.bundle"))
