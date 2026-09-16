"""Provider-neutral harness execution and conformance validation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from plural.domain import HarnessDefinition
from plural.harness.protocol import (
    HarnessEvent,
    HarnessProtocolError,
    HarnessRunRequest,
    encode_request,
    parse_events,
)
from plural.sandbox import ExecRequest, FileUpload, SandboxHandle, SandboxProvider


class HarnessExecution(BaseModel):
    """Validated harness completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    events: tuple[HarnessEvent, ...]
    output_paths: tuple[str, ...]
    artifact_paths: tuple[str, ...]
    stdout: bytes
    stderr: bytes
    duration_seconds: float
    trace_id: str | None = None


class HarnessExecutionError(HarnessProtocolError):
    """Protocol failure carrying process logs for redacted persistence."""

    def __init__(self, message: str, *, stdout: bytes = b"", stderr: bytes = b"") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class HarnessRunner:
    """Run one harness in one already-created sandbox."""

    def __init__(self, provider: SandboxProvider) -> None:
        self.provider = provider

    async def setup(
        self,
        handle: SandboxHandle,
        definition: HarnessDefinition,
        request: HarnessRunRequest,
        *,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Install Harness dependencies as root inside the existing Runtime."""
        if not definition.setup:
            return
        setup_env = dict(env or {})
        setup_env.setdefault("PLURAL_RUNTIME_PROVIDER", self.provider.name)
        setup_env.setdefault("PLURAL_HARNESS_NAME", definition.name)
        setup_env.setdefault("PLURAL_HARNESS_VERSION", definition.revision)
        setup_env.setdefault(
            "PLURAL_TOOLS_PREFIX", f"{request.workspace.rstrip('/')}/.plural/tools"
        )
        for command in definition.setup:
            result = await self.provider.exec(
                handle,
                ExecRequest(
                    command=command,
                    cwd=request.workspace,
                    env=setup_env,
                    timeout_seconds=timeout_seconds,
                    user="root",
                ),
            )
            if result.timed_out:
                raise TimeoutError("harness setup timed out")
            if result.exit_code != 0:
                message = result.stderr.decode("utf-8", errors="replace").strip()
                stdout = result.stdout.decode("utf-8", errors="replace").strip()
                detail = message or stdout
                raise HarnessExecutionError(
                    f"harness setup failed for {definition.name!r}: {detail[:2000]}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

    async def run(
        self,
        handle: SandboxHandle,
        definition: HarnessDefinition,
        request: HarnessRunRequest,
        *,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> HarnessExecution:
        """Execute and enforce protocol and declared-output boundaries."""
        await self.setup(
            handle,
            definition,
            request,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        if definition.healthcheck is not None:
            health = await self.provider.exec(
                handle,
                ExecRequest(
                    command=definition.healthcheck,
                    cwd=request.workspace,
                    env=env or {},
                    timeout_seconds=min(timeout_seconds or 30, 30),
                ),
            )
            if health.timed_out or health.exit_code != 0:
                raise HarnessProtocolError("harness healthcheck failed")
        request_payload = encode_request(request)
        stdin: bytes | None = request_payload
        command = definition.command
        if definition.protocol == "acp":
            if definition.protocol_adapter != "acp-client-v1":
                raise HarnessProtocolError(
                    "ACP execution requires protocol_adapter='acp-client-v1'"
                )
            adapter = Path(__file__).with_name("acp_adapter.py").read_bytes()
            await self.provider.upload_files(
                handle,
                (FileUpload(path=".plural/acp_adapter.py", data=adapter, mode=0o644),),
                root=request.workspace,
            )
            command = ("python", ".plural/acp_adapter.py", "--", *definition.command)
        if self.provider.name == "daytona":
            request_path = ".plural/request.jsonl"
            workspace = _validated_workspace(request.workspace)
            absolute_request_path = f"{workspace.rstrip('/')}/{request_path}"
            await self.provider.upload_files(
                handle,
                (FileUpload(path=request_path, data=request_payload),),
                root=workspace,
            )
            command = (
                "sh",
                "-c",
                'request_path="$1"; shift; exec "$@" < "$request_path"',
                "plural-harness",
                absolute_request_path,
                *command,
            )
            stdin = None
        run_env = dict(env or {})
        tools = f"{request.workspace.rstrip('/')}/.plural/tools/bin"
        path_value = run_env.get("PATH") or os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
        if tools not in path_value.split(":"):
            run_env["PATH"] = f"{tools}:{path_value}"
        run_env.setdefault("PLURAL_RUNTIME_PROVIDER", self.provider.name)
        run_env.setdefault("PLURAL_HARNESS_NAME", definition.name)
        run_env.setdefault("PLURAL_HARNESS_VERSION", definition.revision)
        result = await self.provider.exec(
            handle,
            ExecRequest(
                command=command,
                cwd=request.workspace,
                env=run_env,
                timeout_seconds=timeout_seconds,
                stdin=stdin,
            ),
        )
        if result.timed_out:
            raise TimeoutError("harness execution timed out")
        if result.exit_code != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise HarnessExecutionError(
                f"harness exited with code {result.exit_code}: {message[:2000]}",
                stdout=result.stdout,
                stderr=result.stderr,
            )
        try:
            events = parse_events(result.stdout)
        except HarnessProtocolError as exc:
            raise HarnessExecutionError(
                str(exc),
                stdout=result.stdout,
                stderr=result.stderr,
            ) from exc
        granted = set(request.granted_capabilities)
        for event in events:
            if event.type == "capability" and event.capability and event.capability not in granted:
                raise HarnessExecutionError(
                    f"harness used denied capability {event.capability!r}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
        terminal = events[-1]
        if terminal.type == "error" or terminal.status == "failed":
            raise HarnessExecutionError(
                terminal.message or "harness reported failure",
                stdout=result.stdout,
                stderr=result.stderr,
            )
        declared_outputs = {item.path: item for item in definition.outputs}
        declared_artifacts = {item.path: item for item in definition.artifacts}
        output_paths = tuple(dict.fromkeys(terminal.outputs))
        artifact_paths = tuple(dict.fromkeys(terminal.artifacts))
        _validate_declared("output", output_paths, declared_outputs)
        _validate_declared("artifact", artifact_paths, declared_artifacts)
        return HarnessExecution(
            status="succeeded",
            events=events,
            output_paths=output_paths,
            artifact_paths=artifact_paths,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=result.duration_seconds,
            trace_id=terminal.trace_id,
        )


def _validate_declared(kind: str, actual: tuple[str, ...], declared: Mapping[str, object]) -> None:
    unknown = set(actual) - set(declared)
    if unknown:
        raise HarnessProtocolError(f"harness emitted undeclared {kind} paths: {sorted(unknown)!r}")
    missing = [
        path
        for path, declaration in declared.items()
        if getattr(declaration, "required", False) and path not in actual
    ]
    if missing:
        raise HarnessProtocolError(f"harness omitted required {kind} paths: {missing!r}")


def _validated_workspace(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or path.as_posix() != value.rstrip("/"):
        raise HarnessProtocolError(f"invalid harness workspace path: {value!r}")
    return path.as_posix()


__all__ = ["HarnessExecution", "HarnessExecutionError", "HarnessRunner"]
