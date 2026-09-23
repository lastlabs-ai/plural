from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from plural.harness.protocol import HarnessRunRequest
from plural.harness.retrieval import build_archive, materialize_package, package_from_archive
from plural.harness.runner import HarnessRunner
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


async def test_archived_harness_package_runs_in_docker(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "harness.yaml").write_text(
        yaml.safe_dump(
            {
                "definition": {
                    "name": "docker-flow",
                    "implementation": "runnable",
                    "command": ["python", "smoke.py"],
                    "auth_modes": ["none"],
                    "outputs": [{"path": "result.json"}],
                    "artifacts": [{"path": "trajectory.jsonl", "required": False}],
                    "trajectory_path": "trajectory.jsonl",
                }
            }
        ),
        encoding="utf-8",
    )
    (harness / "smoke.py").write_text(
        "import json,sys\n"
        "json.loads(sys.stdin.readline())\n"
        "open('result.json','w').write('{}\\n')\n"
        "open('trajectory.jsonl','w').write('{}\\n')\n"
        "print(json.dumps({'type':'result',"
        "'status':'succeeded','outputs':['result.json'],"
        "'artifacts':['trajectory.jsonl']}),flush=True)\n",
        encoding="utf-8",
    )
    archive_path = tmp_path / "harness.tar.gz"
    digest = build_archive(harness, archive_path)
    archive = {"published": str(archive_path), "digest": digest}
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
            package.definition,
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
