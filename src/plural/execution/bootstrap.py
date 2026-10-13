"""Make Plural importable inside Docker and remote sandboxes.

An Environment's Apps run in the App host as ``python -m
plural.apps.daemon``, and a Python Harness as ``python -m
plural.harness.class_runner``, so the sandbox needs the ``plural`` package.
The local provider already runs the Python that has it. Every other provider
gets it here, before the Harness starts:

* Docker layers it onto the Environment's image once and reuses that image,
  keyed by the base image and the exact Plural code.
* Other providers install it into the running sandbox, which needs network.

The Environment's ``runtime.packages.python`` are installed the same way,
alongside Plural. On the local provider nothing is installed; they must
already be importable, and :func:`missing_packages` says which are not.

Either way an image that already has the same version is used as it is. By
default the sandbox gets this machine's own Plural code, so the protocol on
both sides matches even for an unreleased build. ``PLURAL_RUNTIME_VERSION``
selects a published release instead: a version such as ``0.16.0``, or
``latest``.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.metadata
import io
import json
import re
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plural.common import HarnessPackage
from plural.harness.retrieval import package_files, source_digest
from plural.sandbox import SandboxProvider
from plural.sandbox.models import (
    ExecRequest,
    FileUpload,
    NetworkMode,
    SandboxError,
    SandboxHandle,
    SandboxRequirements,
)
from plural.tasks import TaskDefinition

RUNTIME_VERSION_VARIABLE = "PLURAL_RUNTIME_VERSION"
IMAGE_SITE = "/opt/plural-runtime/site"
RUNTIME_SITE = "/tmp/plural-runtime/site"
SEARCH_PATH = f"{IMAGE_SITE}:{RUNTIME_SITE}"
_ARCHIVE = ".plural-runtime/plural.zip"
_PYPI = "https://pypi.org/pypi/plural/json"

_PROBE = """
import importlib.metadata, json, sys
try:
    import plural
    info = {"version": plural.__version__}
except Exception as exc:
    info = {"error": f"{type(exc).__name__}: {exc}"}
info["python"] = "%d.%d" % sys.version_info[:2]
missing = []
for name in sys.argv[1:]:
    try:
        importlib.metadata.version(name)
    except Exception:
        missing.append(name)
info["missing"] = missing
print(json.dumps(info))
"""

_INSTALL = """
import os, subprocess, sys, zipfile
site, archive, *requirements = sys.argv[1:]
if sys.version_info < (3, 10):
    sys.exit("Plural needs Python 3.10 or newer; this sandbox has %d.%d" % sys.version_info[:2])
# Every Plural process imports from here, so no one else may own or write it.
top = os.path.dirname(site)
for path in (top, site):
    if os.path.lexists(path):
        info = os.lstat(path)
        if os.path.islink(path) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            sys.exit(path + " exists and is not this installer's own folder")
    else:
        os.mkdir(path, 0o755)
if requirements:
    code = subprocess.call([
        sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir",
        "--disable-pip-version-check", "--no-warn-script-location",
        "--target", site, *requirements,
    ])
    if code:
        sys.exit("pip could not install " + " ".join(requirements))
if archive != "-":
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(site)
"""

_DOCKERFILE = f"""ARG BASE
FROM ${{BASE}}
USER root
COPY requirements.txt /opt/plural-runtime/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \\
    --no-warn-script-location --target {IMAGE_SITE} \\
    -r /opt/plural-runtime/requirements.txt
COPY site/ {IMAGE_SITE}/
ENV PYTHONPATH={IMAGE_SITE}
"""


class PluralBootstrapError(SandboxError):
    """Plural could not be made importable in a sandbox."""


@dataclass(frozen=True)
class PluralDistribution:
    """The Plural a sandbox should import.

    ``source`` is this machine's package directory when the sandbox gets this
    machine's code; ``requirements`` are then only its dependencies.
    """

    version: str
    requirements: tuple[str, ...]
    source: Path | None = None
    packages: tuple[str, ...] = ()
    """The Environment's own Python packages, installed alongside Plural."""

    @functools.cached_property
    def key(self) -> str:
        """Identity of the exact code, for reusing an image built from it."""
        digest = source_digest(self.source) if self.source is not None else ""
        return "\n".join((self.version, *self.requirements, *self.packages, digest))

    def files(self) -> list[tuple[str, bytes]]:
        """Site-relative files to add on top of ``requirements``.

        Returns:
            The package source and its distribution metadata, or nothing for a
            published release.
        """
        if self.source is None:
            return []
        files = [
            (f"plural/{relative}", path.read_bytes())
            for relative, path in package_files(self.source)
        ]
        metadata = f"Metadata-Version: 2.1\nName: plural\nVersion: {self.version}\n"
        files.append((f"plural-{self.version}.dist-info/METADATA", metadata.encode()))
        return files

    @functools.cached_property
    def archive(self) -> bytes:
        """:meth:`files` as one zip, uploaded once instead of file by file."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for relative, data in self.files():
                bundle.writestr(relative, data)
        return buffer.getvalue()


def needs_plural(
    task: TaskDefinition,
    package: HarnessPackage | None = None,
    *extra: Sequence[str],
) -> bool:
    """Whether a Trial's sandbox runs any ``plural`` module.

    Returns:
        True when the Environment has Apps, whose host is Plural code, or when
        the Harness or one of the ``extra`` commands runs Plural code.
    """
    if task.environment.apps:
        return True
    commands = list(extra)
    if package is not None:
        commands.append(package.definition.command)
    return any(part.startswith("plural.") for command in commands for part in command)


def resolve_distribution(
    requested: str | None,
    extras: tuple[str, ...] = (),
    packages: tuple[str, ...] = (),
) -> PluralDistribution:
    """Pick the Plural a sandbox gets from ``PLURAL_RUNTIME_VERSION``.

    ``extras`` are optional dependency groups the Trial needs, such as ``mcp``
    for an App whose server is written with FastMCP. ``packages`` are the
    Environment's own Python packages, installed with it.

    Returns:
        This machine's code when unset, otherwise the named release.
    """
    value = (requested or "").strip()
    if value in {"", "current"}:
        return dataclasses.replace(_host_distribution(tuple(sorted(extras))), packages=packages)
    version = _latest_release() if value == "latest" else value.removeprefix("v")
    name = f"plural[{','.join(sorted(extras))}]" if extras else "plural"
    return PluralDistribution(
        version=version, requirements=(f"{name}=={version}",), packages=packages
    )


def missing_packages(requirements: Sequence[str]) -> list[str]:
    """The requirements this Python does not satisfy, for the local provider.

    A requirement whose environment marker excludes this Python is satisfied.

    Returns:
        Each unsatisfied requirement, as written.
    """
    missing: list[str] = []
    for item in requirements:
        parsed = _requirement(item)
        if parsed is not None and parsed.marker is not None and not parsed.marker.evaluate():
            continue
        try:
            version = importlib.metadata.version(_name(item))
        except importlib.metadata.PackageNotFoundError:
            missing.append(item)
            continue
        if parsed is not None and not parsed.specifier.contains(version, prereleases=True):
            missing.append(item)
    return missing


def needed_extras(task: Any) -> tuple[str, ...]:
    """The optional dependency groups a Task's Apps need in the sandbox.

    Returns:
        ``("mcp",)`` when an App's server is written with FastMCP, else nothing.
    """
    for app in task.environment.apps:
        if app.kind == "mcp" and app.config.get("server"):
            return ("mcp",)
    return ()


def _name(requirement: str) -> str:
    found = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    return found.group(0) if found else requirement


def _requirement(item: str) -> Any:
    """``item`` parsed by ``packaging`` when it is installed, else ``None``."""
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:
        return None
    try:
        return Requirement(item)
    except InvalidRequirement:
        return None


@functools.lru_cache(maxsize=4)
def _host_distribution(extras: tuple[str, ...] = ()) -> PluralDistribution:
    import plural

    wanted = {f'extra == "{item}"' for item in extras}
    requirements = tuple(
        requirement.strip()
        for item in importlib.metadata.requires("plural") or ()
        for requirement, _, marker in [item.partition(";")]
        if "extra" not in marker or marker.strip() in wanted
    )
    return PluralDistribution(
        version=plural.__version__,
        requirements=requirements,
        source=Path(plural.__file__).parent,
    )


@functools.lru_cache(maxsize=1)
def _latest_release() -> str:
    import httpx

    try:
        response = httpx.get(_PYPI, timeout=10)
        response.raise_for_status()
        return str(response.json()["info"]["version"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise PluralBootstrapError(
            f"Could not look up the latest Plural release on PyPI: {exc}. "
            f"Set {RUNTIME_VERSION_VARIABLE} to a version such as 0.16.0."
        ) from exc


async def prepare_requirements(
    provider: SandboxProvider,
    requirements: SandboxRequirements,
    distribution: PluralDistribution,
) -> SandboxRequirements:
    """Point a provider that can build images at an image with Plural in it.

    Returns:
        Requirements for the extended image, or the originals for a provider
        that installs into the running sandbox instead.
    """
    extend = getattr(provider, "extend_image", None)
    if extend is None:
        return requirements
    with tempfile.TemporaryDirectory(prefix="plural-runtime-") as directory:
        context = Path(directory)
        (context / "Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
        (context / "requirements.txt").write_text(
            "".join(f"{item}\n" for item in (*distribution.requirements, *distribution.packages)),
            encoding="utf-8",
        )
        site = context / "site"
        site.mkdir()
        for relative, data in distribution.files():
            target = site / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        extended: SandboxRequirements = await extend(requirements, context, distribution.key)
        return extended


async def install_plural(
    provider: SandboxProvider,
    handle: SandboxHandle,
    distribution: PluralDistribution,
    *,
    network: NetworkMode,
) -> dict[str, str]:
    """Make ``distribution`` importable in a running sandbox.

    Returns:
        The environment variables that select it, for every process that runs
        Plural code in the sandbox.

    Raises:
        PluralBootstrapError: When the sandbox cannot run or install it.
    """
    # Only the image's own folder until the Job installs into RUNTIME_SITE: an
    # entry the Job did not create is one a Harness could create first.
    env = {"PYTHONPATH": IMAGE_SITE}
    names = {_name(item): item for item in distribution.packages}
    found = await _probe(provider, handle, env, tuple(names))
    present = found.get("version") == distribution.version
    packages = tuple(names[name] for name in found.get("missing", list(names)) if name in names)
    if present and not packages:
        return env
    if network is NetworkMode.NONE:
        wanted = " ".join(packages) if present else f"plural=={distribution.version}"
        raise PluralBootstrapError(
            f"This sandbox has no network, so {wanted} cannot be installed in it. Use an "
            "image with them preinstalled, or allow network access."
        )
    archive = "-"
    requirements = packages
    if not present:
        requirements = (*distribution.requirements, *packages)
        if distribution.source is not None:
            await provider.upload_files(
                handle, [FileUpload(path=_ARCHIVE, data=distribution.archive)]
            )
            archive = f"/workspace/{_ARCHIVE}"
    result = await provider.exec(
        handle,
        ExecRequest(
            command=("python", "-c", _INSTALL, RUNTIME_SITE, archive, *requirements),
            cwd="/workspace",
            env={"HOME": "/tmp", "PIP_NO_INPUT": "1"},
            timeout_seconds=600,
            user="root",
        ),
    )
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()
        listed = ", ".join(packages)
        wanted = listed if present else f"Plural {distribution.version}"
        if listed and not present:
            wanted += f" and {listed}"
        raise PluralBootstrapError(
            f"Could not install {wanted} in the sandbox: {detail[-1500:] or result.exit_code}"
        )
    env = {"PYTHONPATH": SEARCH_PATH}
    found = await _probe(provider, handle, env, tuple(names))
    if found.get("version") != distribution.version:
        raise PluralBootstrapError(
            f"Installed Plural {distribution.version}, but the sandbox imports "
            f"{found.get('version') or found.get('error')!r}."
        )
    unseen = [names[name] for name in found.get("missing", []) if name in names]
    if unseen:
        raise PluralBootstrapError(
            f"Installed {', '.join(unseen)}, but the sandbox's Python cannot find them."
        )
    return env


async def _probe(
    provider: SandboxProvider,
    handle: SandboxHandle,
    env: dict[str, str],
    names: tuple[str, ...] = (),
) -> dict[str, Any]:
    result = await provider.exec(
        handle,
        ExecRequest(
            command=("python", "-c", _PROBE, *names),
            cwd="/workspace",
            env=env,
            timeout_seconds=60,
        ),
    )
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()
        raise PluralBootstrapError(
            "The sandbox image cannot run `python`, which Plural's runners need: "
            f"{detail[-500:] or result.exit_code}"
        )
    try:
        parsed = json.loads(result.stdout.decode(errors="replace").strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "RUNTIME_VERSION_VARIABLE",
    "PluralBootstrapError",
    "PluralDistribution",
    "install_plural",
    "missing_packages",
    "needed_extras",
    "needs_plural",
    "prepare_requirements",
    "resolve_distribution",
]
