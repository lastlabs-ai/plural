"""The sandbox conformance suite: the bar a provider passes for verified Trials.

Each check is a real probe in a real sandbox, never a capability lookup. A
provider that passes every check gets ``verified`` Trials without any engine
change; one that fails a check gets ``standard`` Trials whose reasons name it.

======  ====================================================================
ISO-1   The Agent user cannot read the App host's folder
ISO-2   The Agent user cannot escalate
ISO-3   Seats can't read each other
ISO-4   The App host's processes are invisible or untouchable
NET-1   ``no-network`` blocks egress
NET-2   ``allowlist`` permits only listed hosts
NET-3   DNS can't be used to reach a blocked host by IP
LIFE-1  ``destroy`` is idempotent
LIFE-2  ``cancel`` kills every process
LIFE-3  A sandbox can't outlive its Trial
LIFE-4  Orphans are found and removed
REP-1   The image identity is recorded, and pins one image
RES-1   Resource limits apply
LOG-1   Logs are captured
======  ====================================================================

Reports are cached per provider name, provider version, and suite version in
``<config home>/conformance/``. The engine reads the cache to compute each
Trial's trust tier, so run ``plural runtime doctor --conformance`` again after
upgrading a provider.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from plural.common import FrozenModel
from plural.sandbox.base import SandboxProvider
from plural.sandbox.models import (
    AppIsolation,
    ExecRequest,
    ExecResult,
    NetworkMode,
    ResourceRequirements,
    SandboxHandle,
    SandboxRequirements,
    SandboxSummary,
)
from plural.sandbox.sweep import JOB_LABEL, OWNER_LABEL, sweep

CONFORMANCE_VERSION = "1.0"
CHECKS: dict[str, str] = {
    "ISO-1": "The Agent user cannot read the App host's folder",
    "ISO-2": "The Agent user cannot escalate",
    "ISO-3": "Seats can't read each other",
    "ISO-4": "The App host's processes are invisible or untouchable",
    "NET-1": "no-network blocks egress",
    "NET-2": "allowlist permits only listed hosts",
    "NET-3": "DNS can't be used to reach a blocked host by IP",
    "LIFE-1": "destroy is idempotent",
    "LIFE-2": "cancel kills every process",
    "LIFE-3": "A sandbox can't outlive its Trial",
    "LIFE-4": "Orphans are found and removed",
    "REP-1": "The image identity is recorded",
    "RES-1": "Resource limits apply",
    "LOG-1": "Logs are captured",
}
_LIST_ATTEMPTS = 15
_LIST_INTERVAL_SECONDS = 2.0
_GONE = frozenset({"destroyed", "destroying", "deleted", "removing", "exited"})
LIFETIME_SECONDS = 1_800
"""The lifetime conformance sandboxes ask for, which LIFE-3 reads back."""
CPU = 1.0
MEMORY_MB = 1024
_CONNECT = (
    "import socket, ssl, sys\n"
    "host, port, name = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
    "try:\n"
    "    raw = socket.create_connection((host, port), 8)\n"
    "    ssl.create_default_context().wrap_socket(raw, server_hostname=name).close()\n"
    "except (OSError, ValueError) as exc:\n"
    "    print(f'blocked: {exc}')\n"
    "    sys.exit(7)\n"
    "print('connected')\n"
)
"""Reachable means a verified TLS handshake with ``name``: a proxy that accepts
every TCP connection and drops what it won't forward does not count as reaching
the host, and one that answers for a host itself cannot present its certificate."""
_LIMITS = r"""
cpu=""; mem=""
if [ -r /sys/fs/cgroup/cpu.max ]; then cpu=$(cat /sys/fs/cgroup/cpu.max); fi
if [ -z "$cpu" ] && [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]; then
  cpu="$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us) $(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)"
fi
if [ -r /sys/fs/cgroup/memory.max ]; then mem=$(cat /sys/fs/cgroup/memory.max); fi
if [ -z "$mem" ] && [ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
  mem=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
fi
total=$(awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo 2>/dev/null)
echo "cpu=$cpu"; echo "mem=$mem"; echo "memtotal=$total"; echo "nproc=$(nproc 2>/dev/null)"
"""


class CheckResult(FrozenModel):
    """One conformance check's outcome.

    Attributes:
        id: The check's id, such as ``"NET-2"``.
        title: What it checks.
        passed: Whether the provider passed it.
        detail: What the probe saw, in one line.
    """

    id: str
    title: str
    passed: bool
    detail: str = ""


class ConformanceReport(FrozenModel):
    """A provider's conformance suite result.

    Attributes:
        provider: Provider name, such as ``"daytona"``.
        provider_version: The provider's version, from
            :meth:`SandboxProvider.version`.
        conformance_version: The suite's version.
        checked_at: When the suite ran.
        checks: Each check's result, in suite order.
    """

    provider: str
    provider_version: str
    conformance_version: str = CONFORMANCE_VERSION
    checked_at: datetime
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """Whether every check in the suite passed."""
        ids = {item.id for item in self.checks if item.passed}
        return ids >= set(CHECKS)

    @property
    def failures(self) -> tuple[str, ...]:
        """Ids of the checks that failed or did not run."""
        passed = {item.id for item in self.checks if item.passed}
        return tuple(name for name in CHECKS if name not in passed)

    @property
    def summary(self) -> str:
        """``passed 14/14``, or how many passed.

        Examples:
            >>> report = ConformanceReport(
            ...     provider="docker",
            ...     provider_version="docker-29",
            ...     checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ...     checks=(CheckResult(id="LOG-1", title="Logs are captured", passed=True),),
            ... )
            >>> report.summary
            '1/14'
        """
        count = sum(1 for item in self.checks if item.passed and item.id in CHECKS)
        prefix = "passed " if self.passed else ""
        return f"{prefix}{count}/{len(CHECKS)}"


def conformance_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Where conformance reports are cached.

    Returns:
        ``<config home>/conformance``.
    """
    from plural.auth import config_home

    return config_home(environ) / "conformance"


def report_path(
    provider: str, provider_version: str, environ: Mapping[str, str] | None = None
) -> Path:
    """The cache file for one provider version under this suite version.

    Returns:
        The path, whether or not it exists.
    """
    name = f"{provider}--{provider_version}--{CONFORMANCE_VERSION}.json"
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in name)
    return conformance_dir(environ) / safe


def save_report(report: ConformanceReport, environ: Mapping[str, str] | None = None) -> Path:
    """Cache a report where the engine looks for it.

    Returns:
        The file written.
    """
    path = report_path(report.provider, report.provider_version, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_report(
    provider: str, provider_version: str, environ: Mapping[str, str] | None = None
) -> ConformanceReport | None:
    """The cached report for one provider version, if the suite ran on it.

    Returns:
        The report, or ``None`` when there is none or it can't be read.
    """
    path = report_path(provider, provider_version, environ)
    try:
        return ConformanceReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def conformance_status(
    provider: SandboxProvider, environ: Mapping[str, str] | None = None
) -> tuple[Literal["passed", "failed", "missing"], tuple[str, ...]]:
    """Whether ``provider`` passed the suite at its current version, for a trust tier.

    Returns:
        ``("passed", ())``, ``("failed", failed ids)``, or ``("missing", ())``.
    """
    try:
        version = await provider.version()
    except Exception:  # noqa: BLE001 - an unknown version has no report
        return "missing", ()
    report = load_report(provider.name, version, environ)
    if report is None:
        return "missing", ()
    if report.passed:
        return "passed", ()
    return "failed", report.failures


@dataclass
class _Context:
    provider: SandboxProvider
    image: str | None
    snapshot: str | None
    allowed_host: str
    blocked_host: str
    owner: str
    handles: list[SandboxHandle] = field(default_factory=list)

    def requirements(self, **update: object) -> SandboxRequirements:
        base = SandboxRequirements(
            image=self.image,
            snapshot=self.snapshot,
            timeout_seconds=300,
            lifetime_seconds=LIFETIME_SECONDS,
            labels={OWNER_LABEL: self.owner, JOB_LABEL: f"conformance-{self.owner}"},
        )
        return base.model_copy(update=update)

    async def create(self, **update: object) -> SandboxHandle:
        handle = await self.provider.create(self.requirements(**update))
        self.handles.append(handle)
        return handle

    async def run(
        self, handle: SandboxHandle, script: str, *args: str, user: str | None = None
    ) -> ExecResult:
        return await self.provider.exec(
            handle,
            ExecRequest(
                command=("sh", "-c", script, "plural", *args),
                cwd="/",
                timeout_seconds=60,
                user=user,
            ),
        )

    async def python(self, handle: SandboxHandle, code: str, *args: str) -> ExecResult:
        return await self.provider.exec(
            handle,
            ExecRequest(command=("python3", "-c", code, *args), cwd="/", timeout_seconds=60),
        )


def _text(result: ExecResult) -> str:
    return (result.stdout + result.stderr).decode(errors="replace").strip()


def _result(check: str, passed: bool, detail: str) -> CheckResult:
    return CheckResult(id=check, title=CHECKS[check], passed=passed, detail=detail[:300])


async def _isolation(context: _Context, handle: SandboxHandle) -> list[CheckResult]:
    results = []
    isolation: AppIsolation = await context.provider.isolate_apps(handle)
    app, agent = isolation.app_user, isolation.agent_user
    if not app:
        reason = "the provider gave the App host no OS user of its own"
        return [
            _result("ISO-1", False, reason),
            _result("ISO-2", False, reason),
            _result("ISO-4", False, reason),
        ]
    made = await context.run(
        handle,
        'd=$(mktemp -d /tmp/plural-conformance-host.XXXXXX) && chmod 700 "$d" '
        '&& echo plural-secret > "$d/secret" && echo "$d"',
        user=app,
    )
    folder = made.stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
    if made.exit_code != 0 or not folder[0]:
        results.append(_result("ISO-1", False, f"could not make a private folder: {_text(made)}"))
    else:
        read = await context.run(handle, 'cat "$1/secret"', folder[0], user=agent)
        leaked = "plural-secret" in read.stdout.decode(errors="replace")
        results.append(
            _result(
                "ISO-1",
                read.exit_code != 0 and not leaked,
                "denied" if not leaked else "the agent user read the App host's file",
            )
        )
    escalate = await context.run(
        handle, "sudo -n true >/dev/null 2>&1 && echo escalated; id -u", user=agent
    )
    lines = escalate.stdout.decode(errors="replace").split()
    escalated = "escalated" in lines or lines[-1:] == ["0"]
    results.append(
        _result(
            "ISO-2",
            not escalated,
            "the agent user is not root and sudo refused it"
            if not escalated
            else "the agent user is root or ran sudo",
        )
    )
    started = await context.run(handle, "nohup sleep 300 >/dev/null 2>&1 & echo $!", user=app)
    pid = started.stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
    alive = await context.run(handle, 'kill -0 "$1"', pid[0], user=app) if pid[0] else None
    if alive is None or alive.exit_code != 0:
        results.append(_result("ISO-4", False, f"could not start a host process: {_text(started)}"))
    else:
        signal = await context.run(handle, 'kill -0 "$1"', pid[0], user=agent)
        results.append(
            _result(
                "ISO-4",
                signal.exit_code != 0,
                "the agent user could not signal it"
                if signal.exit_code != 0
                else "the agent user can signal the App host's process",
            )
        )
        await context.run(handle, 'kill "$1"', pid[0], user=app)
    return results


async def _seats(context: _Context, handle: SandboxHandle) -> CheckResult:
    users = await context.provider.isolate_seats(handle, ["seat_1", "seat_2"])
    if len(users) < 2:
        return _result("ISO-3", False, "the provider gave seats no OS users of their own")
    made = await context.run(
        handle,
        'd=$(mktemp -d /tmp/plural-conformance-seat.XXXXXX) && chmod 700 "$d" '
        '&& echo seat-secret > "$d/secret" && echo "$d"',
        user=users["seat_1"],
    )
    folder = made.stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
    if made.exit_code != 0 or not folder[0]:
        return _result("ISO-3", False, f"seat 1 could not make a folder: {_text(made)}")
    read = await context.run(handle, 'cat "$1/secret"', folder[0], user=users["seat_2"])
    leaked = "seat-secret" in read.stdout.decode(errors="replace")
    return _result(
        "ISO-3", read.exit_code != 0 and not leaked, "denied" if not leaked else "seat 2 read it"
    )


async def _records(context: _Context, handle: SandboxHandle) -> list[CheckResult]:
    identity = handle.image_identity or ""
    results = [
        _result(
            "REP-1",
            bool(identity) and handle.image_pinned,
            f"{identity or 'no identity'}"
            + ("" if handle.image_pinned else " is not a digest or immutable snapshot"),
        )
    ]
    logged = await context.run(handle, "echo plural-out; echo plural-err >&2; exit 3")
    text = _text(logged)
    results.append(
        _result(
            "LOG-1",
            logged.exit_code == 3 and "plural-err" in text,
            f"exit {logged.exit_code}, stderr {'captured' if 'plural-err' in text else 'lost'}",
        )
    )
    limits = await context.run(handle, _LIMITS)
    results.append(_resources(limits.stdout.decode(errors="replace")))
    lifetime = await context.provider.lifetime(handle)
    if lifetime is None or lifetime.stop_after_seconds is None:
        results.append(_result("LIFE-3", False, "no time to live or auto-stop was set"))
    else:
        ok = 0 < lifetime.stop_after_seconds <= LIFETIME_SECONDS * 1.1 + 120
        results.append(
            _result(
                "LIFE-3",
                ok,
                f"stops after {lifetime.stop_after_seconds:.0f}s"
                + (", then deleted" if lifetime.delete_after_stop else ""),
            )
        )
    return results


def _resources(output: str) -> CheckResult:
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    cpu: float | None = None
    quota = values.get("cpu", "").split()
    if len(quota) == 2 and quota[0] not in {"max", "-1"}:
        try:
            cpu = float(quota[0]) / float(quota[1])
        except (ValueError, ZeroDivisionError):
            cpu = None
    if cpu is None and values.get("nproc", "").isdigit():
        cpu = float(values["nproc"])
    memory: float | None = None
    for key in ("mem", "memtotal"):
        text = values.get(key, "").strip()
        if text.isdigit() and int(text) < 1 << 50:
            memory = min(memory, float(text)) if memory is not None else float(text)
    wanted = MEMORY_MB * 1024 * 1024
    ok = cpu is not None and cpu <= CPU * 1.5 and memory is not None and memory <= wanted * 1.3
    seen_cpu = f"{cpu:g}" if cpu is not None else "unlimited"
    seen_memory = f"{memory / 1024 / 1024:.0f} MB" if memory is not None else "unlimited"
    return _result(
        "RES-1", ok, f"asked for {CPU:g} CPU and {MEMORY_MB} MB; saw {seen_cpu} and {seen_memory}"
    )


async def _network(context: _Context) -> list[CheckResult]:
    results = []
    try:
        closed = await context.create(network=NetworkMode.NONE)
    except Exception as exc:  # noqa: BLE001 - the provider can't do it
        results.append(_result("NET-1", False, f"could not create a no-network sandbox: {exc}"))
    else:
        probe = await context.python(
            closed, _CONNECT, context.allowed_host, "443", context.allowed_host
        )
        results.append(
            _result(
                "NET-1",
                probe.exit_code != 0,
                f"{context.allowed_host} blocked"
                if probe.exit_code != 0
                else f"reached {context.allowed_host}",
            )
        )
    try:
        listed = await context.create(
            network=NetworkMode.ALLOWLIST, network_allowlist=(context.allowed_host,)
        )
    except Exception as exc:  # noqa: BLE001 - the provider can't do it
        reason = f"allowlist not enforced by {context.provider.name}: {exc}"
        return [*results, _result("NET-2", False, reason), _result("NET-3", False, reason)]
    allowed = await context.python(
        listed, _CONNECT, context.allowed_host, "443", context.allowed_host
    )
    blocked = await context.python(
        listed, _CONNECT, context.blocked_host, "443", context.blocked_host
    )
    results.append(
        _result(
            "NET-2",
            allowed.exit_code == 0 and blocked.exit_code != 0,
            f"{context.allowed_host} "
            + ("reachable" if allowed.exit_code == 0 else f"unreachable ({_text(allowed)[-160:]})")
            + f", {context.blocked_host} "
            + ("blocked" if blocked.exit_code != 0 else "reachable"),
        )
    )
    address = await asyncio.to_thread(_address, context.blocked_host)
    direct = await context.python(listed, _CONNECT, address, "443", context.blocked_host)
    results.append(
        _result(
            "NET-3",
            direct.exit_code != 0,
            f"{address} (resolved outside) "
            + ("blocked" if direct.exit_code != 0 else "reachable by IP"),
        )
    )
    return results


def _address(host: str) -> str:
    try:
        return str(socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0])
    except OSError:
        return "1.1.1.1"


async def _cancel(context: _Context) -> CheckResult:
    handle = await context.create()
    started = await context.run(handle, "nohup sleep 300 >/dev/null 2>&1 & echo $!")
    pid = started.stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
    if not pid[0]:
        return _result("LIFE-2", False, f"could not start a sleeper: {_text(started)}")
    await context.provider.cancel(handle)
    try:
        after = await context.run(handle, 'kill -0 "$1"', pid[0])
    except Exception:  # noqa: BLE001 - the sandbox is gone, so is the process
        return _result("LIFE-2", True, "the sandbox stopped with every process")
    remains = after.exit_code == 0 and not after.timed_out
    return _result(
        "LIFE-2",
        not remains,
        "the sleeper is gone" if not remains else "the sleeper survived cancel",
    )


async def _orphans(context: _Context) -> CheckResult:
    owner = f"conformance-{uuid.uuid4().hex[:12]}"
    try:
        orphan = await context.provider.create(
            context.requirements(labels={OWNER_LABEL: owner, JOB_LABEL: owner})
        )
    except Exception as exc:  # noqa: BLE001
        return _result("LIFE-4", False, f"could not create a labeled sandbox: {exc}")
    # Nothing here destroys it: like a client that died, only the labels remain.
    # Some providers list a new sandbox a few seconds after creating it.
    for _ in range(_LIST_ATTEMPTS):
        if await context.provider.list_sandboxes({OWNER_LABEL: owner}):
            break
        await asyncio.sleep(_LIST_INTERVAL_SECONDS)
    found = await sweep(context.provider, owner=owner, delete=True)
    ids = {item.sandbox_id for item in found.orphans}
    if orphan.sandbox_id not in ids:
        context.handles.append(orphan)
        return _result("LIFE-4", False, "the sweep did not find the labeled sandbox")
    active: list[SandboxSummary] = []
    for _ in range(_LIST_ATTEMPTS):
        remaining = await context.provider.list_sandboxes({OWNER_LABEL: owner})
        active = [item for item in remaining if item.state not in _GONE]
        if not active:
            break
        await asyncio.sleep(_LIST_INTERVAL_SECONDS)
    return _result(
        "LIFE-4",
        not active and not found.failed,
        "found and removed" if not active else f"{len(active)} still listed after the sweep",
    )


async def run_conformance(
    provider: SandboxProvider,
    *,
    image: str | None = None,
    snapshot: str | None = None,
    allowed_host: str = "pypi.org",
    blocked_host: str = "example.com",
    progress: Callable[[CheckResult], None] | None = None,
) -> ConformanceReport:
    """Run every check against ``provider``, in real sandboxes.

    Args:
        provider: The provider under test.
        image: The image sandboxes start from; the provider's default if left out.
        snapshot: A snapshot to start from instead of an image.
        allowed_host: A public host the allowlist sandbox may reach.
        blocked_host: A public host it must not reach.
        progress: Called with each result as it is known.

    Returns:
        The report, with every check in suite order.
    """
    context = _Context(
        provider=provider,
        image=image,
        snapshot=snapshot,
        allowed_host=allowed_host,
        blocked_host=blocked_host,
        owner=f"conformance-{uuid.uuid4().hex[:12]}",
    )
    found: dict[str, CheckResult] = {}

    def record(items: Sequence[CheckResult]) -> None:
        for item in items:
            found[item.id] = item
            if progress is not None:
                progress(item)

    async def guarded(
        ids: Sequence[str], step: Callable[[], Awaitable[Sequence[CheckResult]]]
    ) -> None:
        try:
            record(await step())
        except Exception as exc:  # noqa: BLE001 - a crash fails the checks it covers
            record([_result(item, False, f"{type(exc).__name__}: {exc}") for item in ids])

    try:
        main: SandboxHandle | None = None
        try:
            main = await context.create(
                resources=ResourceRequirements(cpu=CPU, memory_mb=MEMORY_MB)
            )
        except Exception as exc:  # noqa: BLE001
            reason = f"could not create a sandbox: {exc}"
            record(
                [
                    _result(item, False, reason)
                    for item in ("ISO-1", "ISO-2", "ISO-3", "ISO-4", "REP-1", "LOG-1", "RES-1")
                ]
            )
            record([_result("LIFE-3", False, reason), _result("LIFE-1", False, reason)])
        if main is not None:
            sandbox = main
            await guarded(("REP-1", "LOG-1", "RES-1", "LIFE-3"), lambda: _records(context, sandbox))
            await guarded(("ISO-1", "ISO-2", "ISO-4"), lambda: _isolation(context, sandbox))
            await guarded(("ISO-3",), lambda: _one(_seats(context, sandbox)))

            async def destroy_twice() -> Sequence[CheckResult]:
                await provider.destroy(sandbox)
                await provider.destroy(sandbox)
                return [_result("LIFE-1", True, "destroyed twice without an error")]

            await guarded(("LIFE-1",), destroy_twice)
        await guarded(("NET-1", "NET-2", "NET-3"), lambda: _network(context))
        await guarded(("LIFE-2",), lambda: _one(_cancel(context)))
        await guarded(("LIFE-4",), lambda: _one(_orphans(context)))
    finally:
        for handle in context.handles:
            with contextlib.suppress(Exception):
                await provider.destroy(handle)
    return ConformanceReport(
        provider=provider.name,
        provider_version=await provider.version(),
        checked_at=datetime.now(timezone.utc),
        checks=tuple(found[item] for item in CHECKS if item in found),
    )


async def _one(step: Awaitable[CheckResult]) -> Sequence[CheckResult]:
    return [await step]


def report_json(report: ConformanceReport) -> dict[str, object]:
    """The report as plain JSON, with its summary, for ``--json`` and the backend.

    Returns:
        A JSON-serializable mapping.
    """
    payload: dict[str, object] = json.loads(report.model_dump_json())
    payload["passed"] = report.passed
    payload["summary"] = report.summary
    payload["failures"] = list(report.failures)
    return payload


__all__ = [
    "CHECKS",
    "CONFORMANCE_VERSION",
    "CheckResult",
    "ConformanceReport",
    "conformance_dir",
    "conformance_status",
    "load_report",
    "report_json",
    "report_path",
    "run_conformance",
    "save_report",
]
