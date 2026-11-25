"""Run a Job's runner in a Runtime sandbox, so a long run doesn't depend on this machine.

``plural run --detach`` packages the project, uploads it with this Plural to a
sandbox the hosted project starts for one of its Daytona Runtimes, starts
``plural run`` there, and returns. Only a Plural key is needed: the sandbox
runs on Plural's account or the Runtime's stored credentials, which never
leave the server, and every command and file goes through the hosted API. The sandbox unpacks the
project into its own folder and never depends on this machine's paths or folder
layout. The Job keeps its id: this machine plans it with a run id the sandbox
reuses, and a Job's identity names its sources by content, not by path. The
Job-scoped key minted for it serves that Job alone. ``plural job show`` copies
the Job's files back while it runs, and once it has finished, revokes the key
and deletes the sandbox.

Every Environment must use the local Runtime, which then runs inside the sandbox.
A sandbox never reaches back into this machine: a platform URL on it, or on its
network, is refused rather than tunneled to.
"""

from __future__ import annotations

import asyncio
import io
import json
import shlex
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import plural
from plural.config import is_local_url
from plural.project.layout import BINDING_FILE, ProjectError
from plural.project.resources import Workspace
from plural.project.runs import RunPlan, planned_job_id
from plural.sandbox import ExecRequest, FileUpload, SandboxHandle, SandboxProvider
from plural.sandbox.models import SandboxRequirements

DETACHED_FILE = "detached.json"
RECORDING_FILE = ".plural/detached-recording.json"
"""In the sandbox's project: the hosted Job its run records to."""
REMOTE = "/workspace/detached"
LABEL = "plural.dev/detached-job"
_SKIPPED = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
PROJECT_FOLDER = "plural-project"
"""The project's folder in the sandbox user's home; the same for every Job and machine."""
_SETUP = (
    "set -e; cd {remote}; mkdir -p config; mkdir -p {project}; "
    "tar xzf project.tgz -C {project}; "
    "uv venv -q {venv}; uv pip install -q --python {venv}/bin/python {wheel}"
)
# The local Runtime runs Apps and Harnesses with the python on PATH, and maps any PATH
# entry under /workspace into its own folder, so this Plural lives outside it.
_VENV = '"$HOME/plural-detached"'
_LAUNCH = (
    'export PATH={venv}/bin:"$PATH"; cd {project} && '
    "setsid nohup plural run {args} > {remote}/run.log 2>&1 < /dev/null & echo $!"
)
_ALIVE = "{{ kill -0 {pid} 2>/dev/null && echo alive || echo done; }}"
_PACK = "cd {project}/.plural/jobs && tar czf {remote}/sync.tgz {job}"


@dataclass(frozen=True)
class Detached:
    """Where a detached Job runs, as recorded beside its local copy."""

    job_id: str
    provider: str
    sandbox_id: str
    pid: int
    project: str
    started_at: str
    key_expires_at: str | None = None
    synced_at: str | None = None
    finished: bool = False
    runtime: str | None = None
    """The project Runtime the hosted project started the sandbox for."""

    def to_json(self) -> dict[str, Any]:
        """The record as written to ``detached.json``.

        Returns:
            Its fields; never a key.
        """
        return dict(self.__dict__)


def refuse_unreachable(url: str) -> None:
    """Refuse a platform URL a sandbox would reach only through this machine.

    Raises:
        ProjectError: When the URL names this machine or a private network.
    """
    if is_local_url(url):
        raise ProjectError(
            f"A detached run's sandbox can't reach {url}: it is this machine or its "
            "network, and Plural never tunnels to it. Detach against a hosted Plural, "
            "with PLURAL_API_URL and PLURAL_GATEWAY_URL set to its https address, or detach "
            "an Agent that calls no model."
        )


def calls_models(plan: RunPlan) -> bool:
    """Whether any Agent of the Job calls a model through the gateway.

    Returns:
        False only when every Agent declares ``auth: none``.
    """
    return any(binding.agent.auth != "none" for binding in plan.spec.agents)


def refuse_runtimes(plan: RunPlan) -> None:
    """Refuse a Job whose Environments don't run in the sandbox itself.

    Raises:
        ProjectError: When an Environment names a Runtime other than local.
    """
    other = sorted(
        {
            f"{task.environment.name} ({task.environment.runtime.provider})"
            for task in plan.spec.tasks
            if task.environment.runtime.provider != "local"
        }
    )
    if other:
        raise ProjectError(
            "A detached run plays every Trial inside its own sandbox, on the local Runtime "
            f"there, and these Environments name another: {', '.join(other)}. Give them "
            "runtime: local, or run without --detach."
        )


def lifetime_seconds(plan: RunPlan) -> float:
    """How long the sandbox may live: every Trial's time limit, run in turn, plus an hour.

    Returns:
        Seconds, at most two days.
    """
    total = 0.0
    for trial in plan.job.plan.trials:
        task = next(item for item in plan.spec.tasks if item.task_id == trial.task_id)
        total += float(task.environment.limits.max_seconds or 3600)
    concurrency = max(1, plan.spec.concurrency)
    return min(total / concurrency + 3600, 2 * 86400)


def project_archive(root: Path, extra: Mapping[str, bytes] | None = None) -> bytes:
    """The project's files as a gzipped tar, without local Jobs, caches, or history.

    ``extra`` adds files by their path in the project, such as its hosted binding.

    Returns:
        The archive.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            parts = relative.parts
            if any(part in _SKIPPED for part in parts) or parts[0] == ".plural":
                continue
            if path.is_file() and not path.is_symlink():
                archive.add(path, arcname=str(relative), recursive=False)
        for name, data in sorted((extra or {}).items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def recording_files(
    binding: bytes, hosted_job_id: str, agents: Mapping[str, Any]
) -> dict[str, bytes]:
    """What a detached run needs to record its Job: the binding, and the hosted Job.

    Returns:
        The files, by their path in the project.
    """
    recording = {"hosted_job_id": hosted_job_id, "agents": {k: list(v) for k, v in agents.items()}}
    return {
        f".plural/{BINDING_FILE}": binding,
        RECORDING_FILE: (json.dumps(recording, sort_keys=True) + "\n").encode(),
    }


def read_recording(root: Path) -> tuple[str, dict[str, tuple[str, str]]]:
    """The hosted Job a detached run records to, and the hosted Agent each binding ran as.

    Returns:
        The hosted Job id and the Agents.

    Raises:
        ProjectError: When the run was not packaged to record.
    """
    path = root / RECORDING_FILE
    if not path.is_file():
        raise ProjectError(f"This project was not packaged to record a detached run: no {path}.")
    value = json.loads(path.read_text("utf-8"))
    agents = {str(k): (str(v[0]), str(v[1])) for k, v in dict(value.get("agents") or {}).items()}
    return str(value["hosted_job_id"]), agents


def sdk_wheel(directory: Path) -> Path | None:
    """Build a wheel of this Plural when it runs from a source checkout.

    Returns:
        The wheel, or ``None`` when Plural is installed from a release.

    Raises:
        ProjectError: When the build fails.
    """
    source = Path(plural.__file__).resolve().parents[2]
    if not (source / "pyproject.toml").is_file() or not (source / "src" / "plural").is_dir():
        return None
    result = subprocess.run(
        ["uv", "build", "--wheel", "-q", "-o", str(directory)],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    wheels = sorted(directory.glob("plural-*.whl"))
    if result.returncode != 0 or not wheels:
        raise ProjectError(
            f"Could not build this Plural for the sandbox: {result.stderr.strip()[-500:]}"
        )
    return wheels[-1]


async def _run(
    provider: SandboxProvider,
    handle: SandboxHandle,
    command: str,
    *,
    env: Mapping[str, str] | None = None,
    timeout: float = 600,
) -> str:
    result = await provider.exec(
        handle,
        ExecRequest(
            command=("sh", "-c", command), cwd="/", env=dict(env or {}), timeout_seconds=timeout
        ),
    )
    if result.timed_out or result.exit_code != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-800:]
        raise ProjectError(f"The detached run's sandbox failed: {detail}")
    return result.stdout.decode(errors="replace").strip()


async def launch(
    workspace: Workspace,
    plan: RunPlan,
    *,
    provider: SandboxProvider,
    args: Sequence[str],
    env: Mapping[str, str],
    key_expires_at: str | None = None,
    wait_seconds: float = 180,
    extra: Mapping[str, bytes] | None = None,
    runtime: str | None = None,
) -> Detached:
    """Start the Job in a new sandbox and record where it runs.

    ``args`` are the ``plural run`` arguments, ``--run-id`` included, and ``env``
    is the runner's environment there: the Job-scoped key and the platform's
    URLs. Neither is written to a file. ``extra`` adds files to the project,
    such as its binding, so the runner there records the Job.

    Returns:
        The record, also written as the local Job's ``detached.json``.

    Raises:
        ProjectError: When the sandbox can't be set up, or the Job doesn't start.
    """
    job_id = planned_job_id(workspace, plan)
    handle = await provider.create(
        SandboxRequirements(labels={LABEL: job_id}, lifetime_seconds=lifetime_seconds(plan))
    )
    try:
        with tempfile.TemporaryDirectory() as scratch:
            wheel = sdk_wheel(Path(scratch))
            files = [
                FileUpload(
                    path="detached/project.tgz", data=project_archive(_root(workspace), extra)
                )
            ]
            if wheel is not None:
                files.append(FileUpload(path=f"detached/{wheel.name}", data=wheel.read_bytes()))
        await provider.upload_files(handle, files, root="/workspace")
        package = shlex.quote(wheel.name) if wheel is not None else f"plural=={plural.__version__}"
        home = await _run(provider, handle, 'printf %s "$HOME"')
        if not home.startswith("/"):
            raise ProjectError("The detached run's sandbox has no home folder for the project.")
        folder = f"{home.rstrip('/')}/{PROJECT_FOLDER}"
        project = shlex.quote(folder)
        await _run(
            provider,
            handle,
            _SETUP.format(remote=REMOTE, project=project, wheel=package, venv=_VENV),
        )
        runner = {**env, "PLURAL_CONFIG_HOME": f"{REMOTE}/config"}
        pid = int(
            await _run(
                provider,
                handle,
                _LAUNCH.format(
                    venv=_VENV,
                    project=project,
                    args=" ".join(shlex.quote(item) for item in args),
                    remote=REMOTE,
                ),
                env=runner,
                timeout=60,
            )
        )
        deadline = time.monotonic() + wait_seconds
        while True:
            found = await _run(
                provider,
                handle,
                f"{{ test -d {project}/.plural/jobs/{job_id} && echo yes; }} || "
                + _ALIVE.format(pid=pid),
            )
            if found == "yes":
                break
            if found == "done" or time.monotonic() > deadline:
                log = await _run(provider, handle, f"tail -c 1500 {REMOTE}/run.log || true")
                raise ProjectError(f"The detached run did not start Job {job_id}:\n{log}")
            await asyncio.sleep(2)
    except BaseException:
        await provider.destroy(handle)
        raise
    record = Detached(
        job_id=job_id,
        provider=provider.name,
        sandbox_id=handle.sandbox_id,
        pid=pid,
        project=folder,
        started_at=_now(),
        key_expires_at=key_expires_at,
        runtime=runtime,
    )
    _write(workspace, record)
    return record


async def sync(
    workspace: Workspace,
    job_id: str,
    *,
    provider: SandboxProvider,
    on_finish: Callable[[Detached], None] | None = None,
) -> Detached | None:
    """Copy a detached Job's files back from its sandbox.

    Once the runner has exited, the last copy is final: ``on_finish`` runs, to
    revoke the Job's key, and the sandbox is deleted.

    Returns:
        The updated record, or ``None`` when the Job is not detached.
    """
    record = detached(workspace, job_id)
    if record is None or record.finished:
        return record
    handle = await provider.attach(record.sandbox_id)
    state = await _run(provider, handle, _ALIVE.format(pid=record.pid))
    await _run(
        provider,
        handle,
        _PACK.format(project=shlex.quote(record.project), remote=REMOTE, job=job_id),
    )
    (archive,) = await provider.download_files(handle, ["detached/sync.tgz"], root="/workspace")
    jobs = workspace.project.jobs_dir
    with tarfile.open(fileobj=io.BytesIO(archive.data), mode="r:gz") as tar:
        tar.extractall(jobs, filter="data")
    finished = state == "done"
    record = Detached(**{**record.to_json(), "synced_at": _now(), "finished": finished})
    _write(workspace, record)
    if finished:
        if on_finish is not None:
            on_finish(record)
        await provider.destroy(handle)
    return record


def detached(workspace: Workspace, job_id: str) -> Detached | None:
    """The record of a detached local Job.

    Returns:
        It, or ``None`` when the Job ran here.
    """
    path = workspace.project.jobs_dir / job_id / DETACHED_FILE
    if not path.is_file():
        return None
    return Detached(**json.loads(path.read_text("utf-8")))


def _write(workspace: Workspace, record: Detached) -> None:
    directory = workspace.project.jobs_dir / record.job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / DETACHED_FILE).write_text(
        json.dumps(record.to_json(), indent=2) + "\n", encoding="utf-8"
    )


def _root(workspace: Workspace) -> Path:
    return workspace.project.root.resolve()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
