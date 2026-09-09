from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plural.cli.main import app
from plural.cli.scaffold import read_yaml, scaffold_environment, scaffold_harness, write_yaml
from plural.harness import HarnessRunner, HarnessRunRequest
from plural.harness.retrieval import materialize_package, package_from_archive
from plural.sandbox import (
    DockerProvider,
    ExecRequest,
    FileUpload,
    NetworkMode,
    SandboxRequirements,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("PLURAL_RUN_DOCKER_TESTS") != "1",
        reason="set PLURAL_RUN_DOCKER_TESTS=1 to opt in",
    ),
]


async def test_docker_sandbox_lifecycle() -> None:
    provider = DockerProvider()
    requirements = SandboxRequirements(
        image="python:3.12-slim",
        network=NetworkMode.NONE,
        read_only_root=True,
    )
    handle = await provider.create(requirements)
    try:
        await provider.upload_files(handle, (FileUpload(path="input.txt", data=b"hello"),))
        result = await provider.exec(
            handle,
            ExecRequest(
                command=("python", "-c", "print(open('input.txt').read())"),
                timeout_seconds=10,
            ),
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == b"hello"
    finally:
        await provider.destroy(handle)


async def test_scaffold_build_publish_add_and_docker_execution(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    harness = tmp_path / "harness"
    scaffold_environment(environment, "docker-flow")
    scaffold_harness(harness, "docker-flow")
    package_yaml = read_yaml(harness / "harness.yaml")
    package_yaml["manifest"].update(
        {
            "command": ["python", "smoke.py"],
            "capabilities": [],
            "secret_names": [],
            "environment_names": [],
            "auth_modes": ["none"],
        }
    )
    write_yaml(harness / "harness.yaml", package_yaml)
    (harness / "smoke.py").write_text(
        "import json,sys\n"
        "json.loads(sys.stdin.readline())\n"
        "open('result.json','w').write('{}\\n')\n"
        "open('trajectory.jsonl','w').write('{}\\n')\n"
        "print(json.dumps({'protocol':'plural-harness-v1','type':'result',"
        "'status':'succeeded','outputs':['result.json'],"
        "'artifacts':['trajectory.jsonl']}),flush=True)\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    built = runner.invoke(app, ["harness", "build", str(harness)])
    published = runner.invoke(app, ["harness", "publish", str(harness)])
    assert built.exit_code == published.exit_code == 0
    archive = json.loads(published.stdout)
    added = runner.invoke(
        app,
        [
            "harness",
            "add",
            archive["published"],
            "--digest",
            archive["digest"],
            "--environment",
            str(environment),
        ],
    )
    assert added.exit_code == 0, added.stderr
    package = package_from_archive(archive["published"], archive["digest"])
    source = materialize_package(package)
    assert source is not None

    provider = DockerProvider()
    handle = await provider.create(
        SandboxRequirements(image="python:3.12-slim", network=NetworkMode.NONE)
    )
    try:
        await provider.upload_bundle(handle, source, root="/workspace/harness")
        execution = await HarnessRunner(provider).run(
            handle,
            package.manifest,
            HarnessRunRequest(
                request_id="docker-flow",
                task={"task_id": "smoke", "input": "run"},
                agent={"name": "smoke", "model": "test/model"},
                environment={},
                workspace="/workspace/harness",
            ),
        )
        assert execution.status == "succeeded"
    finally:
        await provider.destroy(handle)
