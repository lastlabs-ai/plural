"""Push project resources to a hosted project and pull them back.

A push makes one immutable, private revision usable in the bound project. A
revision is identified by its content hash alone, which the SDK and the
server compute identically (see :mod:`plural.identity`), so pushing unchanged
content reuses the existing revision rather than creating a duplicate. The
server numbers revisions in order; a version such as ``1.2.0`` is an optional
release label, never a reason a push fails.

Every push is planned in full before anything is written: unresolved
references, cycles, and dependencies that are not already hosted all fail
with no upload. Resources are then pushed dependencies first, so a parent is
never saved pointing at a dependency that is missing. A push never edits
local files.

A push never overwrites or deletes. Each new revision names the revision it
was based on, and a push refuses to add a revision on top of a hosted change
this checkout has not synced, the way git refuses a non-fast-forward push,
unless the caller forces it.

Each revision also stores the resource's exact source package, addressed by
the SHA-256 of its archive, so ``pull`` restores the editable files.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel

from plural.agents import Agent
from plural.blobs import read_blob, store_blob
from plural.common import PackageSource
from plural.environments.definition import EnvironmentResource
from plural.errors import NotFoundError, PluralError
from plural.harness.models import PLURAL_PACKAGE_PREFIX, HarnessDefinition
from plural.harness.retrieval import (
    MAX_ARCHIVE_BYTES,
    archive_bytes,
    extract_archive,
    looks_like_credential,
    package_files,
    tree_digest,
)
from plural.project.layout import (
    AGENT,
    BENCHMARK,
    ENVIRONMENT,
    HARNESS,
    KINDS,
    TASK,
    VERIFIER,
    Project,
    ProjectError,
    ResourceKind,
    ResourceRef,
)
from plural.project.manifests import (
    BenchmarkManifest,
    LockEntry,
    LockFile,
    ProjectBinding,
    TaskManifest,
)
from plural.project.resources import (
    SCAFFOLD_MARKER,
    LocalResource,
    Workspace,
    scaffold_problems,
)
from plural.studio import PUSH_REFERENCE_PREFIX, RevisionResourceAPI, Studio, slugify

# Concurrent requests per push or plan; each hosted call is one round trip.
_WORKERS = 8

_T = TypeVar("_T")
_R = TypeVar("_R")


def _parallel(work: Callable[[_T], _R], items: Sequence[_T]) -> list[_R]:
    """``work`` over ``items`` on a few threads, results in input order.

    Returns:
        One result per item.
    """
    if len(items) <= 1:
        return [work(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(items))) as pool:
        return list(pool.map(work, items))


class _Uploads:
    """Uploads each package and file once, even when resources pushed together share one."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._done: set[str] = set()

    def ensure(self, digest: str, payload: bytes) -> None:
        with self._guard:
            lock = self._locks.setdefault(digest, threading.Lock())
        with lock:
            if digest in self._done:
                return
            if not self._studio.packages.exists(digest):
                self._studio.packages.upload(digest, payload)
            self._done.add(digest)

    def ensure_blob(self, digest: str, content_type: str) -> None:
        with self._guard:
            lock = self._locks.setdefault(digest, threading.Lock())
        with lock:
            if digest in self._done:
                return
            if not self._studio.blobs.exists(digest):
                self._studio.blobs.upload(digest, read_blob(digest), content_type=content_type)
            self._done.add(digest)


@dataclass(frozen=True)
class HostedRevision:
    """One hosted revision, as far as push and pull need it."""

    resource_id: str
    revision_id: str
    version: str | None
    content_hash: str
    package_digest: str | None
    dependencies: tuple[tuple[ResourceRef, str], ...] = ()
    number: int | None = None
    legacy_content_hash: str | None = None

    @classmethod
    def from_payload(cls, resource_id: str, payload: dict[str, Any]) -> HostedRevision:
        """Read a revision record from the hosted API.

        Returns:
            The revision.
        """
        dependencies = tuple(
            (ResourceRef(str(item["kind"]), str(item["slug"])), str(item["revision_id"]))
            for item in payload.get("dependencies") or ()
            if isinstance(item, dict)
        )
        number = payload.get("number")
        return cls(
            resource_id=resource_id,
            revision_id=str(payload["id"]),
            version=str(payload["version"]) if payload.get("version") else None,
            content_hash=str(payload.get("content_hash") or ""),
            package_digest=payload.get("package_digest"),
            dependencies=dependencies,
            number=int(number) if isinstance(number, int) else None,
            legacy_content_hash=payload.get("legacy_content_hash") or None,
        )

    @property
    def label(self) -> str:
        """``#3``, or ``#3 (1.2.0)`` once it is released under a version."""
        return revision_label(self.number, self.version, self.revision_id)

    def holds(self, digest: str | None) -> bool:
        """Whether ``digest`` names this revision, under the current or the legacy identity rules.

        Returns:
            ``True`` when either hash matches.
        """
        return digest is not None and digest in {self.content_hash, self.legacy_content_hash}


def revision_label(number: int | None, version: str | None, fallback: str = "") -> str:
    """How a revision is named to people: its number and, if released, its version.

    Returns:
        ``#3 (1.2.0)``, ``#3``, ``1.2.0``, or ``fallback``.
    """
    base = f"#{number}" if number is not None else ""
    if version:
        return f"{base} ({version})" if base else version
    return base or fallback


@dataclass(frozen=True)
class PushStep:
    """What push did, or will do, for one resource."""

    ref: ResourceRef
    version: str | None
    content_hash: str
    status: Literal["unchanged", "pushed", "planned"]
    revision_id: str | None = None
    number: int | None = None
    # Why a requested version label was not applied.
    note: str | None = None

    @property
    def label(self) -> str:
        """The revision's number and release version, as people read it."""
        return revision_label(self.number, self.version, self.revision_id or "")


@dataclass
class PushResult:
    """Every resource a push touched, dependencies first."""

    target: ResourceRef
    steps: list[PushStep] = field(default_factory=list)

    @property
    def pushed(self) -> list[PushStep]:
        """Steps that created a new revision."""
        return [step for step in self.steps if step.status == "pushed"]


@dataclass(frozen=True)
class PullStep:
    """What pull did for one resource."""

    ref: ResourceRef
    version: str | None
    revision_id: str
    status: Literal["restored", "unchanged", "replaced"]
    backup: Path | None = None
    # Written from the stored definition because the revision has no package.
    rebuilt: bool = False
    number: int | None = None

    @property
    def label(self) -> str:
        """The revision as people read it, like ``#3 (1.2.0)``."""
        return revision_label(self.number, self.version, self.revision_id)


def push(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    ref: ResourceRef,
    *,
    with_deps: bool = False,
    force: bool = False,
) -> PushResult:
    """Validate ``ref`` and make it available as a revision in the bound project.

    Args:
        workspace: Project resources.
        studio: Hosted API addressed to ``binding.project_id``.
        binding: The hosted project this checkout is bound to.
        ref: Resource to push.
        with_deps: Also push local dependencies that are not hosted yet.
            Without it, every dependency must already have a hosted revision
            matching the local files exactly.
        force: Add revisions even where the hosted resource changed since
            this checkout last synced it. Nothing is overwritten either way.

    Returns:
        One step per resource in the dependency graph.

    Raises:
        ProjectError: When the graph is invalid or cannot be pushed as-is.
    """
    order = workspace.dependency_order([ref])
    resources = {item: workspace.load(item) for item in order}
    hosted = dict(
        zip(order, _parallel(lambda item: _hosted_state(studio, item), order), strict=True)
    )
    pins = _pins(workspace.project, binding.project_id)

    problems: list[str] = []
    resolved: dict[ResourceRef, HostedRevision] = {}
    to_push: list[ResourceRef] = []
    for item in order:
        resource = resources[item]
        parent, revisions = hosted[item]
        match = _match(resource.content_hash, parent, revisions)
        if match is not None:
            resolved[item] = match
        elif item != ref and not with_deps:
            current = _current(parent, revisions)
            state = (
                f"changed locally since {current.label} was pushed" if current else "not pushed yet"
            )
            problems.append(f"{item} is {state}")
        else:
            to_push.append(item)
            if not force:
                problems.extend(_diverged(item, parent, revisions, pins))
        problems.extend(_package_problems(resource, workspace))
    if problems:
        hint = (
            f"\nPush the dependencies too with `plural {ref.info.cli} push {ref.name} --with-deps`."
            if not with_deps and any("pushed" in item for item in problems)
            else ""
        )
        raise ProjectError(f"Cannot push {ref}; nothing was uploaded.{hint}", problems)

    result = PushResult(target=ref)
    result.steps = _commit(
        workspace, studio, binding, order, resources, hosted, resolved, to_push, force=force
    )
    return result


def release(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    ref: ResourceRef,
    version: str,
) -> PushResult:
    """Push ``ref`` if needed, then label the revision matching the local files ``version``.

    A version names one revision forever: it cannot move to other content,
    and a revision keeps the first version it is released under.

    Returns:
        The push steps, the last one carrying the release.

    Raises:
        ProjectError: When ``version`` is not ``MAJOR.MINOR.PATCH`` or already
            names a different revision.
    """
    if _SEMVER.fullmatch(version) is None:
        raise ProjectError(
            f"{version!r} is not a release version. Use MAJOR.MINOR.PATCH, like 1.0.0."
        )
    result = push(workspace, studio, binding, ref, with_deps=True)
    step = result.steps[-1]
    if step.version == version:
        return result
    if step.version is not None:
        raise ProjectError(f"{ref} {step.label} is already released as {step.version}.")
    parent, revisions = _hosted_state(studio, ref)
    taken = next((item for item in revisions if item.version == version), None)
    if taken is not None:
        raise ProjectError(
            f"{ref} version {version} already names {taken.label}. A version names one "
            "revision forever; choose another."
        )
    assert parent is not None and step.revision_id is not None
    labeled = HostedRevision.from_payload(
        str(parent["id"]), _api(studio, ref).release(str(parent["id"]), step.revision_id, version)
    )
    lock = _lock_for(workspace, binding)
    entry = lock.resources.get(str(ref))
    if entry is not None:
        lock.resources[str(ref)] = entry.model_copy(update={"version": version})
        workspace.project.write_lock(lock)
    result.steps[-1] = PushStep(
        ref=ref,
        version=labeled.version,
        content_hash=step.content_hash,
        status=step.status,
        revision_id=labeled.revision_id,
        number=labeled.number,
    )
    return result


def declared_version(project: Project, ref: ResourceRef) -> str | None:
    """The ``version:`` a manifest spells out, or ``None`` when it leaves it out.

    Returns:
        The version text as written.
    """
    path = project.manifest_path(ref)
    if not path.is_file():
        return None
    found = _VERSION_LINE.search(path.read_text(encoding="utf-8"))
    return found.group(2) if found else None


def _label(wanted: str | None, revisions: list[HostedRevision]) -> tuple[str | None, str | None]:
    """The release version to give a new revision, and why a wanted one was skipped.

    Returns:
        ``(version, note)``: the manifest's version when no revision has it yet.
    """
    if wanted is None:
        return None, None
    if wanted.isdigit():
        return None, f"version {wanted} is only digits, which reads as revision #{wanted}"
    taken = next((item for item in revisions if item.version == wanted), None)
    if taken is None:
        return wanted, None
    return None, f"version {wanted} already names {taken.label}"


def _commit(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    order: list[ResourceRef],
    resources: dict[ResourceRef, LocalResource],
    hosted: dict[ResourceRef, tuple[dict[str, Any] | None, list[HostedRevision]]],
    resolved: dict[ResourceRef, HostedRevision],
    to_push: list[ResourceRef],
    *,
    force: bool = False,
) -> list[PushStep]:
    """Push ``to_push`` dependencies first and record every revision in the lock.

    A manifest's ``version:`` labels the new revision when no revision has that
    version yet. A title change renames the hosted resource even when its
    content, and so its revision, is unchanged.

    Every field is checked against what the server's Plural accepts before
    anything is uploaded. A server that takes a whole push at once saves every
    revision or none. An older one is sent each resource on its own,
    dependencies first; when one fails, the lock still records every revision
    that was pushed.

    Returns:
        One step per resource in ``order``.

    Raises:
        ProjectError: When the server would refuse a field, or refused a push.
    """
    lock = _lock_for(workspace, binding)
    prepared = dict(
        zip(to_push, _parallel(lambda item: _prepare(resources[item]), to_push), strict=True)
    )
    labels: dict[ResourceRef, tuple[str | None, str | None]] = {
        item: _label(declared_version(workspace.project, item), hosted[item][1]) for item in to_push
    }
    bases = {
        item: _base(lock.resources.get(str(item)), hosted[item][0], hosted[item][1])
        for item in to_push
    }

    def item_for(item: ResourceRef) -> dict[str, Any]:
        ids = [
            resolved[dependency].revision_id
            if dependency in resolved
            else f"{PUSH_REFERENCE_PREFIX}{dependency}"
            for dependency in resources[item].dependencies
        ]
        return _api(studio, item).batch_item(
            prepared[item].value,
            ref=str(item),
            slug=slugify(item.name),
            package_digest=prepared[item].digest,
            version=labels[item][0],
            parent_revision_id=bases[item],
            **prepared[item].references(ids),
        )

    items = [item_for(item) for item in order if item in prepared]
    server = studio.server_version() if items else None
    refused = _field_problems(
        server, [(item["ref"], item["kind"], item["revision"]) for item in items]
    )
    if refused and server is not None:
        raise ProjectError(
            f"This server's Plural ({_server_label(server)}) would refuse these fields, so "
            "nothing was uploaded. Upgrade the server's Plural, or remove the fields.",
            refused,
        )
    uploads = _Uploads(studio)
    if server is not None and "batch_push" in server.get("capabilities", []):
        _parallel(lambda item: _upload(item, uploads), list(prepared.values()))
        try:
            saved = studio.push_batch(items, force=force)
        except PluralError as exc:
            raise ProjectError(
                "The server refused the push, so nothing was saved.", _refusals(exc)
            ) from exc
        by_ref = {str(item["ref"]): item["revision"] for item in saved.get("items", [])}
        for item in order:
            if item in prepared:
                parent = hosted[item][0]
                resolved[item] = _saved(
                    studio,
                    prepared[item],
                    by_ref[str(item)],
                    str(parent["id"]) if parent else None,
                )
            else:
                _rename(studio, item, hosted[item][0], resources[item])
        for item in order:
            _record(lock, item, resources[item], resolved[item])
        workspace.project.write_lock(lock)
        return [_step(item, resources, resolved, prepared, labels) for item in order]

    steps: dict[ResourceRef, PushStep] = {}

    def one(item: ResourceRef) -> PushStep:
        resource = resources[item]
        parent, _revisions = hosted[item]
        if item in to_push:
            resolved[item] = _push_one(
                studio,
                resource,
                resolved,
                uploads=uploads,
                resource_id=str(parent["id"]) if parent else None,
                version=labels[item][0],
                parent_revision_id=bases[item],
                force=force,
            )
        else:
            _rename(studio, item, parent, resource)
        return _step(item, resources, resolved, prepared, labels)

    for level in _levels(order, resources):
        with ThreadPoolExecutor(max_workers=min(_WORKERS, len(level))) as pool:
            futures = [(item, pool.submit(one, item)) for item in level]
        failure: BaseException | None = None
        for item, future in futures:
            error = future.exception()
            if error is None:
                steps[item] = future.result()
                _record(lock, item, resources[item], resolved[item])
            elif failure is None:
                failure = error
        workspace.project.write_lock(lock)
        if failure is not None:
            raise failure
    return [steps[item] for item in order]


def _step(
    item: ResourceRef,
    resources: dict[ResourceRef, LocalResource],
    resolved: dict[ResourceRef, HostedRevision],
    prepared: dict[ResourceRef, _Prepared],
    labels: dict[ResourceRef, tuple[str | None, str | None]],
) -> PushStep:
    revision = resolved[item]
    return PushStep(
        ref=item,
        version=revision.version,
        content_hash=resources[item].content_hash,
        status="pushed" if item in prepared else "unchanged",
        revision_id=revision.revision_id,
        number=revision.number,
        note=labels[item][1] if item in labels else None,
    )


def _record(
    lock: LockFile, item: ResourceRef, resource: LocalResource, revision: HostedRevision
) -> None:
    lock.resources[str(item)] = LockEntry(
        version=revision.version,
        number=revision.number,
        content_hash=resource.content_hash,
        package_digest=revision.package_digest,
        dependencies=[str(dependency) for dependency in resource.dependencies],
        resource_id=revision.resource_id,
        revision_id=revision.revision_id,
    )


def _levels(
    order: list[ResourceRef], resources: dict[ResourceRef, LocalResource]
) -> list[list[ResourceRef]]:
    """``order`` grouped so each group depends only on earlier groups.

    Returns:
        The groups, each in ``order``'s order.
    """
    depth: dict[ResourceRef, int] = {}
    for item in order:
        below = [
            depth[dependency] for dependency in resources[item].dependencies if dependency in depth
        ]
        depth[item] = 1 + max(below, default=-1)
    levels: list[list[ResourceRef]] = [[] for _ in range(1 + max(depth.values(), default=-1))]
    for item in order:
        levels[depth[item]].append(item)
    return levels


def _base(
    pinned: LockEntry | None,
    parent: dict[str, Any] | None,
    revisions: list[HostedRevision],
) -> str | None:
    """The revision a new one is based on: what this checkout last synced, else the current one.

    Returns:
        A revision id, or ``None`` for the first revision.
    """
    known = {item.revision_id for item in revisions}
    if pinned is not None and pinned.revision_id in known:
        return pinned.revision_id
    current = _current(parent, revisions)
    return current.revision_id if current else None


def _rename(
    studio: Studio, ref: ResourceRef, parent: dict[str, Any] | None, resource: LocalResource
) -> None:
    """Give the hosted resource the local display name when only the title changed."""
    name = getattr(resource.value, "title", None) or getattr(resource.value, "name", None)
    if parent is None or not isinstance(name, str) or not name or parent.get("name") == name:
        return
    _api(studio, ref).update(str(parent["id"]), name=name)
    parent["name"] = name


@dataclass(frozen=True)
class ProjectPushStep:
    """What a project push will do for one resource."""

    ref: ResourceRef
    content_hash: str
    action: Literal["new", "update", "unchanged"]
    current: HostedRevision | None = None
    match: HostedRevision | None = None

    @property
    def hosted_label(self) -> str | None:
        """The hosted revision this push builds on, as people read it."""
        return self.current.label if self.current is not None else None


@dataclass
class ProjectPushPlan:
    """Every local resource, dependencies first, and what push will do with it."""

    steps: list[ProjectPushStep]
    hosted_only: list[ResourceRef] = field(default_factory=list)
    hosted: dict[ResourceRef, tuple[dict[str, Any] | None, list[HostedRevision]]] = field(
        default_factory=dict
    )

    @property
    def changes(self) -> list[ProjectPushStep]:
        """Steps that add a revision."""
        return [step for step in self.steps if step.action != "unchanged"]


def local_refs(project: Project) -> list[ResourceRef]:
    """Every resource directory in the project, in kind order.

    Returns:
        The references.
    """
    return [ResourceRef(kind.name, name) for kind in KINDS for name in project.names(kind)]


def plan_project_push(
    workspace: Workspace,
    studio: Studio | None,
    project_id: str | None,
    *,
    force: bool = False,
    roots: list[ResourceRef] | None = None,
) -> ProjectPushPlan:
    """Plan pushing every local resource, or ``roots`` and their dependencies, without writing.

    A Task's content hash includes its dependencies, so changing an
    Environment gives each Task and Benchmark that uses it a new revision too.
    Versions never block a push: new revisions are numbered by the service.

    Args:
        workspace: Project resources.
        studio: Hosted API addressed to the target project, or ``None`` for a
            hosted project that does not exist yet.
        project_id: Target hosted project, used to trust ``plural.lock`` pins.
        force: Allow new revisions on top of hosted changes this checkout has
            not synced.
        roots: Plan only these resources and their dependencies. The plan
            then lists no hosted-only resources.

    Returns:
        The plan.

    Raises:
        ProjectError: Listing every problem, before anything is uploaded.
    """
    project = workspace.project
    partial = roots is not None
    roots = roots if roots is not None else local_refs(project)
    if not roots:
        raise ProjectError(
            "This project has no resources to push yet. Create one with `plural env init <name>`."
        )
    order = workspace.dependency_order(roots)
    hosted: dict[ResourceRef, tuple[dict[str, Any] | None, list[HostedRevision]]] = (
        dict(zip(order, _parallel(lambda item: _hosted_state(studio, item), order), strict=True))
        if studio is not None
        else {item: (None, []) for item in order}
    )
    pins = _pins(project, project_id)
    steps: list[ProjectPushStep] = []
    problems: list[str] = []
    for item in order:
        resource = workspace.load(item)
        parent, revisions = hosted[item]
        problems.extend(_package_problems(resource, workspace))
        match = _match(resource.content_hash, parent, revisions)
        action: Literal["new", "update", "unchanged"]
        if match is not None:
            action = "unchanged"
        elif not revisions:
            action = "new"
        else:
            action = "update"
            if not force:
                problems.extend(_diverged(item, parent, revisions, pins))
        steps.append(
            ProjectPushStep(
                ref=item,
                content_hash=resource.content_hash,
                action=action,
                current=_current(parent, revisions),
                match=match,
            )
        )
    if problems:
        raise ProjectError(f"Cannot push project {project.name}; nothing was uploaded.", problems)

    hosted_only: list[ResourceRef] = []
    if studio is not None and not partial:
        local = {(item.kind, slugify(item.name)) for item in order}
        listed = _parallel(lambda kind: hosted_list(studio, kind), list(KINDS))
        for kind, records in zip(KINDS, listed, strict=True):
            for record in records:
                slug = str(record.get("slug") or slugify(str(record.get("name") or "")))
                if (kind.name, slug) not in local:
                    hosted_only.append(ResourceRef(kind.name, slug))
    return ProjectPushPlan(steps=steps, hosted_only=hosted_only, hosted=hosted)


def apply_project_push(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    plan: ProjectPushPlan,
    *,
    force: bool = False,
) -> list[PushStep]:
    """Push every planned change, dependencies first.

    Returns:
        One step per resource.

    Raises:
        ProjectError: When files were edited between planning and pushing.
    """
    order = [step.ref for step in plan.steps]
    resources = {ref: workspace.load(ref) for ref in order}
    moved = [
        str(step.ref)
        for step in plan.steps
        if resources[step.ref].content_hash != step.content_hash
    ]
    if moved:
        raise ProjectError(
            "These files were edited while the push was being prepared, so nothing was "
            "uploaded. Push again once your edits are saved.",
            moved,
        )
    resolved = {step.ref: step.match for step in plan.steps if step.match is not None}
    to_push = [step.ref for step in plan.changes]
    return _commit(
        workspace, studio, binding, order, resources, plan.hosted, resolved, to_push, force=force
    )


_VERSION_LINE = re.compile(r"^version:[ \t]*(['\"]?)([^'\"\s#]+)\1", re.MULTILINE)
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _diverged(
    ref: ResourceRef,
    parent: dict[str, Any] | None,
    revisions: list[HostedRevision],
    pins: dict[str, LockEntry],
) -> list[str]:
    """Why a new revision would land on hosted changes this checkout never synced.

    Returns:
        One message per divergence, or an empty list when the push is fast-forward.
    """
    current = _current(parent, revisions)
    if current is None:
        return []
    pinned = pins.get(str(ref))
    pull = f"`plural {ref.info.cli} pull {ref.name}`"
    if pinned is None or pinned.revision_id is None:
        return [
            f"{ref} already exists in the hosted project at {current.label}, but this "
            f"checkout has never pushed or pulled it. Pull it with {pull} to start from the "
            "hosted copy, or pass --force to add your revision on top."
        ]
    if pinned.revision_id != current.revision_id:
        synced = revision_label(pinned.number, pinned.version, pinned.revision_id)
        return [
            f"{ref} changed in the hosted project since this checkout last synced it "
            f"(hosted {current.label}, synced {synced}). Pull it with {pull}, or pass "
            "--force to add your revision on top."
        ]
    return []


def _pins(project: Project, project_id: str | None) -> dict[str, LockEntry]:
    """Lock entries that describe ``project_id``; entries for another project are ignored.

    Returns:
        The trusted pins, or an empty mapping when the lock belongs to another project.
    """
    lock = project.read_lock()
    if project_id is None or lock.project_id != project_id:
        return {}
    return dict(lock.resources)


def _current(
    parent: dict[str, Any] | None, revisions: list[HostedRevision]
) -> HostedRevision | None:
    if not revisions:
        return None
    wanted = parent.get("current_revision_id") if parent else None
    found = next((item for item in revisions if item.revision_id == wanted), None)
    return found or max(revisions, key=lambda item: item.number or 0)


def _match(
    digest: str, parent: dict[str, Any] | None, revisions: list[HostedRevision]
) -> HostedRevision | None:
    """The hosted revision holding exactly ``digest``: the current one if it does, else the newest.

    Returns:
        The revision, or ``None`` when no revision has this content.
    """
    same = [item for item in revisions if item.content_hash == digest]
    if not same:
        return None
    current = _current(parent, revisions)
    if current is not None and current in same:
        return current
    return max(same, key=lambda item: item.number or 0)


def select_revision(
    ref: ResourceRef, revisions: list[HostedRevision], selector: str
) -> HostedRevision:
    """The revision ``selector`` names: a number (``3`` or ``#3``), a version, or a content hash.

    Returns:
        The revision.

    Raises:
        ProjectError: When no revision matches, listing the ones that exist.
    """
    wanted = selector.strip()
    found: HostedRevision | None
    if wanted.lstrip("#").isdigit():
        number = int(wanted.lstrip("#"))
        found = next((item for item in revisions if item.number == number), None)
    elif wanted.startswith("sha256:"):
        found = next((item for item in revisions if item.holds(wanted)), None)
    else:
        found = next((item for item in revisions if item.version == wanted), None)
    if found is None:
        known = ", ".join(item.label for item in revisions) or "none"
        raise ProjectError(f"{ref} has no revision {selector}. Hosted revisions: {known}.")
    return found


def resolve_pinned(
    studio: Studio, pins: Mapping[str, Mapping[str, str]]
) -> dict[ResourceRef, HostedRevision]:
    """Find the hosted revision of every input a recorded run pinned.

    ``pins`` maps ``kind/name`` to the ``content_hash`` the run used, as
    ``run.json`` records them. Matching is by content, so the project's current
    files do not matter. Hashes from before revision identity 2 still match
    through each revision's legacy hash.

    Returns:
        The matching revision for every pinned input.

    Raises:
        ProjectError: Naming each input that has no revision with that content.
    """
    resolved: dict[ResourceRef, HostedRevision] = {}
    problems = []
    for key, pin in pins.items():
        ref = ResourceRef.parse(key)
        digest = pin.get("content_hash")
        match = next(
            (item for item in _hosted_revisions(studio, ref) if digest and item.holds(digest)),
            None,
        )
        if match is None:
            problems.append(f"{ref} with the content this Job ran is not pushed")
        else:
            resolved[ref] = match
    if problems:
        raise ProjectError(
            "The hosted project must hold the exact revisions a Job ran. Push them with "
            "`plural project push`; if the files changed since the run, restore those "
            "files first.",
            problems,
        )
    return resolved


def pull(
    workspace: Workspace,
    studio: Studio,
    ref: ResourceRef,
    *,
    selector: str | None = None,
    revision_id: str | None = None,
    force: bool = False,
    with_deps: bool = False,
    project_id: str | None = None,
) -> list[PullStep]:
    """Restore a hosted revision's editable files into the project.

    Local files that differ from the revision are never overwritten unless
    ``force`` is set, and then the previous directory is kept under
    ``.plural/backups/``.

    Args:
        workspace: Project resources.
        studio: Hosted API addressed to the source project.
        ref: Resource to restore.
        selector: Revision number (``3``), version, or content hash.
            Defaults to the current revision.
        revision_id: Exact revision, used when following dependency pins.
        force: Replace local files that differ.
        with_deps: Also restore the exact dependency revisions it pins.
        project_id: Hosted project recorded in ``plural.lock``.

    Returns:
        One step per restored resource, dependencies first.

    Raises:
        ProjectError: When the revision cannot be restored.
    """
    steps: list[PullStep] = []
    seen: set[ResourceRef] = set()

    def restore(item: ResourceRef, wanted: str | None, wanted_id: str | None) -> None:
        if item in seen:
            return
        seen.add(item)
        revision = _hosted_revision(studio, item, selector=wanted, revision_id=wanted_id)
        for dependency, dependency_id in revision.dependencies:
            # A dependency this project lacks is always restored; one it has is
            # replaced only when asked, so local edits are never lost.
            if with_deps or not _is_local(workspace, dependency):
                restore(dependency, None, dependency_id)
        steps.append(_restore(workspace, studio, item, revision, force=force))

    restore(ref, selector, revision_id)
    lock = workspace.project.read_lock()
    if project_id and lock.project_id not in {None, project_id}:
        lock = LockFile(project_id=project_id)
    elif project_id:
        lock = lock.model_copy(update={"project_id": project_id})
    for step in steps:
        revision = _hosted_revision(studio, step.ref, revision_id=step.revision_id)
        lock.resources[str(step.ref)] = LockEntry(
            version=revision.version,
            number=revision.number,
            content_hash=revision.content_hash,
            package_digest=revision.package_digest,
            dependencies=[str(dependency) for dependency, _ in revision.dependencies],
            resource_id=revision.resource_id,
            revision_id=revision.revision_id,
        )
    workspace.project.write_lock(lock)
    return steps


def hosted_resource(
    studio: Studio, ref: ResourceRef
) -> tuple[dict[str, Any], list[HostedRevision]]:
    """The hosted parent record and its revisions, oldest first.

    Returns:
        The parent record and its revisions.

    Raises:
        ProjectError: When the resource is not in the hosted project.
    """
    api = _api(studio, ref)
    parent = api.find(slugify(ref.name))
    if parent is None:
        raise ProjectError(f"{ref.info.label} {ref.name!r} is not in the hosted project.")
    return parent, _revisions(api, parent)


def hosted_list(studio: Studio, kind: ResourceKind) -> list[dict[str, Any]]:
    """Every resource of one kind in the hosted project.

    Returns:
        Parent records as the service returns them.
    """
    api: RevisionResourceAPI[Any] = getattr(studio, kind.collection)
    return [dict(item) for item in api.list()]


def _package_problems(resource: LocalResource, workspace: Workspace) -> list[str]:
    problems = [
        f"{marker}: unfinished. Finish it and delete the {SCAFFOLD_MARKER} line; "
        "unfinished work runs locally but is never uploaded."
        for marker in scaffold_problems(resource.directory, workspace.project.root)
    ]
    for relative, _path in package_files(resource.directory):
        if looks_like_credential(relative):
            location = (resource.directory / relative).relative_to(workspace.project.root)
            problems.append(
                f"Refusing to upload {location}: it looks like a credential. Remove it or list "
                f"it in {resource.directory.name}/.pluralignore."
            )
    return problems


@dataclass(frozen=True)
class _Prepared:
    """A resource as its revision is sent: the package and the value naming it."""

    resource: LocalResource
    digest: str
    payload: bytes
    value: Any

    @property
    def blobs(self) -> list[tuple[str, str]]:
        """Task resource files the revision refers to, as ``(digest, content_type)``."""
        if self.resource.ref.kind != TASK.name:
            return []
        return [
            (item.digest, item.content_type)
            for item in self.resource.value.resources
            if item.delivery == "blob" and item.digest
        ]

    def references(self, ids: list[str]) -> dict[str, Any]:
        """Dependency revision ids, in the fields this kind sends them in.

        Returns:
            The reference fields.
        """
        kind = self.resource.ref.kind
        if kind == TASK.name:
            return {"environment_revision_id": ids[0], "verifier_revision_ids": ids[1:]}
        if kind == AGENT.name:
            return {"harness_revision_id": ids[0] if ids else None}
        if kind == BENCHMARK.name:
            return {"task_revision_ids": ids}
        return {}


def _prepare(resource: LocalResource) -> _Prepared:
    payload = archive_bytes(resource.directory)
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ProjectError(
            f"{resource.ref} is {len(payload)} bytes compressed, over the "
            f"{MAX_ARCHIVE_BYTES}-byte package limit. List large data in .pluralignore."
        )
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    value = resource.value
    if resource.ref.kind == ENVIRONMENT.name:
        definition = value.definition()
        value = definition.model_copy(
            update={
                "source": PackageSource(
                    kind="package",
                    uri=f"{PLURAL_PACKAGE_PREFIX}{digest}",
                    digest=definition.source.digest if definition.source else None,
                )
            }
        )
    elif resource.ref.kind == HARNESS.name:
        value = HarnessDefinition.from_package(
            value._package(), source=f"{PLURAL_PACKAGE_PREFIX}{digest}"
        )
    return _Prepared(resource=resource, digest=digest, payload=payload, value=value)


def _upload(prepared: _Prepared, uploads: _Uploads) -> None:
    uploads.ensure(prepared.digest, prepared.payload)
    for digest, content_type in prepared.blobs:
        uploads.ensure_blob(digest, content_type)


def _saved(
    studio: Studio, prepared: _Prepared, record: dict[str, Any], resource_id: str | None
) -> HostedRevision:
    """The revision the server saved, checked against the local content hash.

    Returns:
        The revision, with its parent's id.

    Raises:
        ProjectError: When the server hashed the content differently.
    """
    resource = prepared.resource
    parent_id = str(
        record.get(f"{resource.ref.kind}_id") or record.get("resource_id") or resource_id or ""
    )
    revision = HostedRevision.from_payload(parent_id, record)
    if revision.content_hash != resource.content_hash:
        raise ProjectError(
            f"{resource.ref} was saved as revision {revision.revision_id}, but the server "
            f"computed content hash {revision.content_hash} where this SDK computed "
            f"{resource.content_hash}. The SDK and server versions disagree; upgrade both."
        )
    if not revision.resource_id:
        parent = _api(studio, resource.ref).find(slugify(resource.ref.name))
        revision = HostedRevision(
            resource_id=str(parent["id"]) if parent else "",
            revision_id=revision.revision_id,
            version=revision.version,
            content_hash=revision.content_hash,
            package_digest=revision.package_digest or prepared.digest,
            dependencies=revision.dependencies,
            number=revision.number,
            legacy_content_hash=revision.legacy_content_hash,
        )
    return revision


def _push_one(
    studio: Studio,
    resource: LocalResource,
    resolved: dict[ResourceRef, HostedRevision],
    *,
    uploads: _Uploads,
    resource_id: str | None = None,
    version: str | None = None,
    parent_revision_id: str | None = None,
    force: bool = False,
) -> HostedRevision:
    prepared = _prepare(resource)
    _upload(prepared, uploads)
    ids = [resolved[dependency].revision_id for dependency in resource.dependencies]
    try:
        record = _api(studio, resource.ref).push(
            prepared.value,
            package_digest=prepared.digest,
            slug=slugify(resource.ref.name),
            resource_id=resource_id,
            version=version,
            parent_revision_id=parent_revision_id,
            force=force,
            **prepared.references(ids),
        )
    except PluralError as exc:
        raise ProjectError(
            f"The server refused {resource.ref}.", _refusals(exc, str(resource.ref))
        ) from exc
    return _saved(studio, prepared, record, resource_id)


def _refusals(exc: PluralError, ref: str | None = None) -> list[str]:
    """Each problem the server reported, naming the resource and field.

    Returns:
        One line per problem.
    """
    body = exc.body if isinstance(exc.body, dict) else {}
    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        lines = []
        for error in errors:
            loc = ".".join(str(part) for part in error.get("loc") or ())
            name = error.get("ref") or ref
            text = f"{loc}: {error.get('msg')}" if loc else str(error.get("msg"))
            lines.append(f"{name}: {text}" if name else text)
        return lines
    message = exc.message.removeprefix("Nothing was saved.\n")
    return [line for line in message.splitlines() if line] or [str(exc)]


def _field_problems(
    server: dict[str, Any] | None, items: list[tuple[str, str, dict[str, Any]]]
) -> list[str]:
    """Fields this checkout sends that the server's Plural does not accept.

    Args:
        server: The server's ``/version`` report, or ``None`` when it has none.
        items: ``(ref, kind, revision body)`` for each revision to push.

    Returns:
        One line per kind and field, counting the resources that send it.
    """
    fields = (server or {}).get("fields")
    if not isinstance(fields, dict):
        return []
    sent: dict[tuple[str, str], list[str]] = {}
    for ref, kind, body in items:
        accepted = fields.get(kind)
        if not isinstance(accepted, list):
            continue
        for name in sorted(set(body) - set(accepted)):
            sent.setdefault((kind, name), []).append(ref)
    return [
        f"{name} on {', '.join(refs)}: the server's Plural does not accept {kind} {name}"
        for (kind, name), refs in sent.items()
    ]


def _server_label(server: dict[str, Any]) -> str:
    version = str(server.get("plural") or "unknown")
    if server.get("dirty"):
        return f"{version}, a checkout with uncommitted changes"
    if server.get("source") == "checkout" and not server.get("tag"):
        return f"{version}, an unreleased checkout"
    return version


def _restore(
    workspace: Workspace,
    studio: Studio,
    ref: ResourceRef,
    revision: HostedRevision,
    *,
    force: bool,
) -> PullStep:
    files: dict[str, str | bytes] | None = None
    payload = b""
    if revision.package_digest:
        payload = studio.packages.download(revision.package_digest)
        actual = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if actual != revision.package_digest:
            raise ProjectError(
                f"The package for {ref} {revision.label} failed verification: expected "
                f"{revision.package_digest}, received {actual}. Nothing was written."
            )
    else:
        files = _files_from_definition(studio, ref, revision)
    target = workspace.project.resource_dir(ref)
    workspace.project.state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workspace.project.state_dir) as scratch:
        staged = Path(scratch) / ref.name
        if files is None:
            extract_archive(payload, staged)
        else:
            staged.mkdir(parents=True)
            for name, content in files.items():
                path = staged / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    path.write_bytes(content)
                else:
                    path.write_text(content, encoding="utf-8")
        if not (staged / ref.info.manifest).is_file():
            raise ProjectError(f"The package for {ref} has no {ref.info.manifest}.")
        rebuilt = files is not None
        if target.exists():
            if tree_digest(target) == tree_digest(staged):
                return PullStep(
                    ref,
                    revision.version,
                    revision.revision_id,
                    "unchanged",
                    rebuilt=rebuilt,
                    number=revision.number,
                )
            if not force:
                relative = target.relative_to(workspace.project.root)
                raise ProjectError(
                    f"{relative}/ differs from {ref} {revision.label}. Nothing was changed. "
                    f"Commit or move your local edits, or pass --force to replace the directory "
                    f"(the current files are kept under .plural/backups/)."
                )
            backup = (
                workspace.project.state_dir
                / "backups"
                / f"{ref.kind}-{ref.name}-{time.strftime('%Y%m%dT%H%M%S')}"
            )
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged), target)
            return PullStep(
                ref,
                revision.version,
                revision.revision_id,
                "replaced",
                backup,
                rebuilt=rebuilt,
                number=revision.number,
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), target)
    return PullStep(
        ref,
        revision.version,
        revision.revision_id,
        "restored",
        rebuilt=rebuilt,
        number=revision.number,
    )


REBUILT_NOTE = (
    "Revisions created in the web app have no source files, so these were written from "
    "their stored definition. `title:` keeps the display name; the directory is the slug."
)


def pull_missing(
    workspace: Workspace, studio: Studio, refs: list[ResourceRef], *, project_id: str
) -> list[PullStep]:
    """Pull each of ``refs`` that this project lacks but the hosted project holds.

    Nothing local is replaced. A ref the hosted project does not hold either is
    skipped, so the caller reports it the usual way.

    Returns:
        One step per restored resource, dependencies first.
    """
    steps: list[PullStep] = []
    for ref in refs:
        if _is_local(workspace, ref):
            continue
        parent, _revisions = _hosted_state(studio, ref)
        if parent is None:
            continue
        steps.extend(pull(workspace, studio, ref, project_id=project_id))
    return steps


def _is_local(workspace: Workspace, ref: ResourceRef) -> bool:
    return workspace.project.manifest_path(ref).is_file()


def _is_default(model: type[BaseModel], key: str, value: Any) -> bool:
    default = model.model_fields[key].get_default(call_default_factory=True)
    if isinstance(default, BaseModel):
        default = default.model_dump(mode="json")
    if isinstance(default, tuple):
        default = list(default)
    return bool(value == default)


def _resource_files(
    studio: Studio, ref: ResourceRef, revision: HostedRevision, resources: list[Any]
) -> dict[str, str | bytes]:
    """The files a hosted Task's resources hold, keyed by their path.

    Returns:
        Inline text, or the verified bytes of each blob.

    Raises:
        ProjectError: When a resource holds neither.
    """
    files: dict[str, str | bytes] = {}
    for item in resources:
        resource = EnvironmentResource.model_validate(item)
        path = resource.path or resource.name
        if resource.delivery == "inline":
            files[path] = resource.content or ""
        elif resource.delivery == "blob" and resource.digest:
            data = studio.blobs.download(resource.digest)
            store_blob(data)
            files[path] = data
        else:
            raise ProjectError(
                f"{ref} {revision.label} lists {resource.name} as a {resource.delivery} "
                "resource, which only its source package holds. Push it again from there."
            )
    return files


def _files_from_definition(
    studio: Studio, ref: ResourceRef, revision: HostedRevision
) -> dict[str, str | bytes]:
    """Rebuild a manifest-only resource from the definition the server stored.

    Tasks, Agents, and Benchmarks created in the web app have no source package,
    but everything in them is data, so their files can be written back. Other
    kinds carry code that only a push from their source directory uploads.

    Returns:
        File contents keyed by path relative to the resource directory.

    Raises:
        ProjectError: When the revision cannot be written as files.
    """
    label = ref.info.label
    if ref.kind not in {TASK.name, AGENT.name, BENCHMARK.name}:
        raise ProjectError(
            f"{ref} {revision.label} has no source package, so its files cannot be "
            f"restored. An {label} carries code, which only a push from its source directory "
            "uploads. Push it again from there."
        )
    record = _api(studio, ref).revision(revision.resource_id, revision.revision_id)
    definition: dict[str, Any] = dict(record.get("definition") or {})

    def named(kind: str) -> list[str]:
        return [item.name for item, _id in revision.dependencies if item.kind == kind]

    manifest: dict[str, Any] = {"name": ref.name}
    # Revisions from before titles were their own field record the title as the name.
    title = definition.get("title") or definition.get("name")
    if isinstance(title, str) and title and title != ref.name:
        manifest["title"] = title
    if revision.version:
        manifest["version"] = revision.version
    files: dict[str, str | bytes] = {}
    if ref.kind == TASK.name:
        resources = _resource_files(studio, ref, revision, definition.get("resources") or [])
        environments, verifiers = named(ENVIRONMENT.name), named(VERIFIER.name)
        if not environments or not verifiers:
            raise ProjectError(
                f"{ref} {revision.label} does not name a hosted Environment and Verifier, "
                "so it cannot be written as a task.yaml."
            )
        manifest |= {
            "instructions": "instruction.md",
            "environment": environments[0],
            "verifiers": verifiers,
        }
        for key in (
            "goals",
            "info",
            "metadata",
            "initial_state",
            "expected",
            "seat_instructions",
        ):
            if key in definition and not _is_default(TaskManifest, key, definition[key]):
                manifest[key] = definition[key]
        if resources:
            manifest["resources"] = sorted(resources)
        TaskManifest.model_validate(manifest)
        files["instruction.md"] = str(definition.get("instructions") or "")
        files |= resources
    elif ref.kind == AGENT.name:
        manifest["model"] = definition.get("model")
        harness = definition.get("harness")
        harnesses = named(HARNESS.name)
        if harnesses:
            manifest["harness"] = harnesses[0]
        elif isinstance(harness, str):
            manifest["harness"] = harness
        elif harness:
            raise ProjectError(
                f"{ref} {revision.label} embeds a Harness that is not in the hosted project, "
                "so it cannot be written as an agent.yaml."
            )
        for key in (
            "provider",
            "instructions",
            "fallback_models",
            "temperature",
            "max_tokens",
            "harness_config",
            "auth",
            "secrets",
            "endpoint",
            "endpoint_key",
            "external",
            "credentials",
            "metadata",
        ):
            if key in definition and not _is_default(Agent, key, definition[key]):
                manifest[key] = definition[key]
    else:
        manifest["tasks"] = named(TASK.name)
        for key in BenchmarkManifest.model_fields:
            if key in manifest or key == "primary_metric":
                continue
            if key in definition and not _is_default(BenchmarkManifest, key, definition[key]):
                manifest[key] = definition[key]
        BenchmarkManifest.model_validate(manifest)
    files[ref.info.manifest] = (
        f"# {label} restored from a hosted revision that was created without source files.\n"
        + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    )
    return files


def _lock_for(workspace: Workspace, binding: ProjectBinding) -> LockFile:
    lock = workspace.project.read_lock()
    if lock.project_id not in {None, binding.project_id}:
        return LockFile(project_id=binding.project_id)
    return LockFile(project_id=binding.project_id, resources=dict(lock.resources))


def _api(studio: Studio, ref: ResourceRef) -> RevisionResourceAPI[Any]:
    return getattr(studio, ref.info.collection)  # type: ignore[no-any-return]


def _revisions(api: RevisionResourceAPI[Any], parent: dict[str, Any]) -> list[HostedRevision]:
    resource_id = str(parent["id"])
    items = [HostedRevision.from_payload(resource_id, item) for item in api.revisions(resource_id)]
    return items


def _hosted_state(
    studio: Studio, ref: ResourceRef
) -> tuple[dict[str, Any] | None, list[HostedRevision]]:
    """The hosted parent and its revisions, or an empty state when it is absent.

    Returns:
        The parent record and its revisions. Both are empty when the resource
        is not in the hosted project.
    """
    api = _api(studio, ref)
    parent = api.find(slugify(ref.name))
    if parent is None:
        return None, []
    return parent, _revisions(api, parent)


def _hosted_revisions(studio: Studio, ref: ResourceRef) -> list[HostedRevision]:
    _parent, revisions = _hosted_state(studio, ref)
    return revisions


def _hosted_revision(
    studio: Studio,
    ref: ResourceRef,
    *,
    selector: str | None = None,
    revision_id: str | None = None,
) -> HostedRevision:
    parent, revisions = hosted_resource(studio, ref)
    if revision_id is not None:
        for revision in revisions:
            if revision.revision_id == revision_id:
                return revision
        try:
            payload = _api(studio, ref).revision(str(parent["id"]), revision_id)
        except NotFoundError:
            raise ProjectError(f"{ref} has no revision {revision_id}.") from None
        return HostedRevision.from_payload(str(parent["id"]), payload)
    if selector is not None:
        return select_revision(ref, revisions, selector)
    current = _current(parent, revisions)
    if current is None:
        raise ProjectError(f"{ref} has no revisions in the hosted project.")
    return current


__all__ = [
    "HostedRevision",
    "PullStep",
    "PushResult",
    "PushStep",
    "hosted_list",
    "hosted_resource",
    "declared_version",
    "pull",
    "push",
    "release",
    "resolve_pinned",
    "revision_label",
    "select_revision",
]
