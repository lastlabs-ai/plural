"""Push project resources to a hosted project and pull them back.

A push makes one immutable, private revision usable in the bound project. A
revision is identified by its version and canonical content hash, which the
SDK and the server compute identically, so pushing unchanged content reuses
the existing revision rather than creating a duplicate.

Every push is planned in full before anything is written: unresolved
references, cycles, dependencies that are not already hosted, and version
conflicts all fail with no upload. Resources are then pushed dependencies
first, so a parent is never saved pointing at a dependency that is missing.

Each revision also stores the resource's exact source package, addressed by
the SHA-256 of its archive, so ``pull`` restores the editable files.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from plural.common import PackageSource
from plural.errors import NotFoundError
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
    TASK,
    ProjectError,
    ResourceKind,
    ResourceRef,
)
from plural.project.manifests import LockEntry, LockFile, ProjectBinding
from plural.project.resources import LocalResource, Workspace
from plural.studio import RevisionResourceAPI, Studio, slugify


@dataclass(frozen=True)
class HostedRevision:
    """One hosted revision, as far as push and pull need it."""

    resource_id: str
    revision_id: str
    version: str
    content_hash: str
    package_digest: str | None
    dependencies: tuple[tuple[ResourceRef, str], ...] = ()

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
        return cls(
            resource_id=resource_id,
            revision_id=str(payload["id"]),
            version=str(payload.get("version") or ""),
            content_hash=str(payload.get("content_hash") or ""),
            package_digest=payload.get("package_digest"),
            dependencies=dependencies,
        )


@dataclass(frozen=True)
class PushStep:
    """What push did, or will do, for one resource."""

    ref: ResourceRef
    version: str
    content_hash: str
    status: Literal["unchanged", "pushed", "planned"]
    revision_id: str | None = None


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
    version: str
    revision_id: str
    status: Literal["restored", "unchanged", "replaced"]
    backup: Path | None = None


def push(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    ref: ResourceRef,
    *,
    with_deps: bool = False,
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

    Returns:
        One step per resource in the dependency graph.

    Raises:
        ProjectError: When the graph is invalid or cannot be pushed as-is.
    """
    order = workspace.dependency_order([ref])
    resources = {item: workspace.load(item) for item in order}
    hosted = {item: _hosted_revisions(studio, item) for item in order}

    problems: list[str] = []
    resolved: dict[ResourceRef, HostedRevision] = {}
    to_push: list[ResourceRef] = []
    for item in order:
        resource = resources[item]
        match, problem = _match(resource, hosted[item], workspace)
        if problem:
            problems.append(problem)
        elif match is not None:
            resolved[item] = match
        elif item != ref and not with_deps:
            latest = hosted[item][-1].version if hosted[item] else None
            state = (
                f"changed locally since version {latest} was pushed" if latest else "not pushed yet"
            )
            problems.append(f"{item} {resource.version} is {state}")
        else:
            to_push.append(item)
        problems.extend(_package_problems(resource, workspace))
    if problems:
        hint = (
            f"\nPush the dependencies too with `plural {ref.info.cli} push {ref.name} --with-deps`."
            if not with_deps and any("pushed" in item for item in problems)
            else ""
        )
        raise ProjectError(f"Cannot push {ref}; nothing was uploaded.{hint}", problems)

    result = PushResult(target=ref)
    lock = _lock_for(workspace, binding)
    for item in order:
        resource = resources[item]
        if item in to_push:
            revision = _push_one(studio, resource, resolved)
            resolved[item] = revision
            status: Literal["unchanged", "pushed"] = "pushed"
        else:
            revision = resolved[item]
            status = "unchanged"
        lock.resources[str(item)] = LockEntry(
            version=resource.version,
            content_hash=resource.content_hash,
            package_digest=revision.package_digest,
            dependencies=[str(dependency) for dependency in resource.dependencies],
            resource_id=revision.resource_id,
            revision_id=revision.revision_id,
        )
        result.steps.append(
            PushStep(
                ref=item,
                version=resource.version,
                content_hash=resource.content_hash,
                status=status,
                revision_id=revision.revision_id,
            )
        )
        workspace.project.write_lock(lock)
    return result


def resolve_hosted(
    workspace: Workspace, studio: Studio, refs: list[ResourceRef]
) -> dict[ResourceRef, HostedRevision]:
    """Find the hosted revision matching each local resource exactly.

    Used to run on hosted infrastructure without uploading: every resource in
    the graph must already be pushed with identical content.

    Returns:
        The matching revision for every resource in the dependency graph.

    Raises:
        ProjectError: Naming each resource that must be pushed first.
    """
    order = workspace.dependency_order(refs)
    problems = []
    resolved: dict[ResourceRef, HostedRevision] = {}
    for item in order:
        resource = workspace.load(item)
        match, problem = _match(resource, _hosted_revisions(studio, item), workspace)
        if match is not None:
            resolved[item] = match
        else:
            problems.append(problem or f"{item} {resource.version} is not pushed")
    if problems:
        targets = " ".join(f"`plural {ref.info.cli} push {ref.name} --with-deps`" for ref in refs)
        raise ProjectError(
            "Hosted runs use pushed revisions only, and some local files differ from them. "
            f"Push first with {targets}.",
            problems,
        )
    return resolved


def pull(
    workspace: Workspace,
    studio: Studio,
    ref: ResourceRef,
    *,
    version: str | None = None,
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
        version: Revision version. Defaults to the current revision.
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

    def restore(item: ResourceRef, wanted_version: str | None, wanted_id: str | None) -> None:
        if item in seen:
            return
        seen.add(item)
        revision = _hosted_revision(studio, item, version=wanted_version, revision_id=wanted_id)
        if with_deps:
            for dependency, dependency_id in revision.dependencies:
                restore(dependency, None, dependency_id)
        steps.append(_restore(workspace, studio, item, revision, force=force))

    restore(ref, version, revision_id)
    lock = workspace.project.read_lock()
    if project_id and lock.project_id not in {None, project_id}:
        lock = LockFile(project_id=project_id)
    elif project_id:
        lock = lock.model_copy(update={"project_id": project_id})
    for step in steps:
        revision = _hosted_revision(studio, step.ref, revision_id=step.revision_id)
        lock.resources[str(step.ref)] = LockEntry(
            version=revision.version,
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


def _match(
    resource: LocalResource, hosted: list[HostedRevision], workspace: Workspace
) -> tuple[HostedRevision | None, str | None]:
    manifest = workspace.project.manifest_path(resource.ref).relative_to(workspace.project.root)
    for revision in hosted:
        same_version = revision.version == resource.version
        same_content = revision.content_hash == resource.content_hash
        if same_version and same_content:
            return revision, None
        if same_version:
            return None, (
                f"{resource.ref} version {resource.version} is already pushed with different "
                f"content. Bump `version:` in {manifest}."
            )
        if same_content:
            return None, (
                f"{resource.ref} is already pushed with this content as version "
                f"{revision.version}. Set `version: {revision.version}` in {manifest}."
            )
    return None, None


def _package_problems(resource: LocalResource, workspace: Workspace) -> list[str]:
    problems = []
    for relative, _path in package_files(resource.directory):
        if looks_like_credential(relative):
            location = (resource.directory / relative).relative_to(workspace.project.root)
            problems.append(
                f"Refusing to upload {location}: it looks like a credential. Remove it or list "
                f"it in {resource.directory.name}/.pluralignore."
            )
    return problems


def _push_one(
    studio: Studio, resource: LocalResource, resolved: dict[ResourceRef, HostedRevision]
) -> HostedRevision:
    payload = archive_bytes(resource.directory)
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ProjectError(
            f"{resource.ref} is {len(payload)} bytes compressed, over the "
            f"{MAX_ARCHIVE_BYTES}-byte package limit. List large data in .pluralignore."
        )
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if not studio.packages.exists(digest):
        studio.packages.upload(digest, payload)
    value = resource.value
    references: dict[str, Any] = {}
    ids = [resolved[dependency].revision_id for dependency in resource.dependencies]
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
    elif resource.ref.kind == TASK.name:
        references = {"environment_revision_id": ids[0], "verifier_revision_ids": ids[1:]}
    elif resource.ref.kind == AGENT.name:
        references = {"harness_revision_id": ids[0] if ids else None}
    elif resource.ref.kind == BENCHMARK.name:
        references = {"task_revision_ids": ids}
    api = _api(studio, resource.ref)
    record = api.push(value, package_digest=digest, **references)
    parent_id = str(record.get(f"{resource.ref.kind}_id") or record.get("resource_id") or "")
    revision = HostedRevision.from_payload(parent_id, record)
    if revision.content_hash != resource.content_hash:
        raise ProjectError(
            f"{resource.ref} was saved as revision {revision.revision_id}, but the server "
            f"computed content hash {revision.content_hash} where this SDK computed "
            f"{resource.content_hash}. The SDK and server versions disagree; upgrade both."
        )
    if not revision.resource_id:
        parent = api.find(slugify(resource.ref.name))
        revision = HostedRevision(
            resource_id=str(parent["id"]) if parent else "",
            revision_id=revision.revision_id,
            version=revision.version,
            content_hash=revision.content_hash,
            package_digest=revision.package_digest or digest,
            dependencies=revision.dependencies,
        )
    return revision


def _restore(
    workspace: Workspace,
    studio: Studio,
    ref: ResourceRef,
    revision: HostedRevision,
    *,
    force: bool,
) -> PullStep:
    if not revision.package_digest:
        raise ProjectError(
            f"{ref} {revision.version} has no source package, so its files cannot be restored. "
            "Revisions created in the web app or before plural 0.15 store only the compiled "
            "definition. Push it again from its source directory."
        )
    payload = studio.packages.download(revision.package_digest)
    actual = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if actual != revision.package_digest:
        raise ProjectError(
            f"The package for {ref} {revision.version} failed verification: expected "
            f"{revision.package_digest}, received {actual}. Nothing was written."
        )
    target = workspace.project.resource_dir(ref)
    workspace.project.state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workspace.project.state_dir) as scratch:
        staged = Path(scratch) / ref.name
        extract_archive(payload, staged)
        if not (staged / ref.info.manifest).is_file():
            raise ProjectError(f"The package for {ref} has no {ref.info.manifest}.")
        if target.exists():
            if tree_digest(target) == tree_digest(staged):
                return PullStep(ref, revision.version, revision.revision_id, "unchanged")
            if not force:
                relative = target.relative_to(workspace.project.root)
                raise ProjectError(
                    f"{relative}/ differs from {ref} {revision.version}. Nothing was changed. "
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
            return PullStep(ref, revision.version, revision.revision_id, "replaced", backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), target)
    return PullStep(ref, revision.version, revision.revision_id, "restored")


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


def _hosted_revisions(studio: Studio, ref: ResourceRef) -> list[HostedRevision]:
    api = _api(studio, ref)
    parent = api.find(slugify(ref.name))
    return _revisions(api, parent) if parent is not None else []


def _hosted_revision(
    studio: Studio,
    ref: ResourceRef,
    *,
    version: str | None = None,
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
    if version is not None:
        for revision in revisions:
            if revision.version == version:
                return revision
        known = ", ".join(revision.version for revision in revisions) or "none"
        raise ProjectError(f"{ref} has no version {version}. Hosted versions: {known}.")
    current = parent.get("current_revision_id")
    for revision in revisions:
        if revision.revision_id == current:
            return revision
    if revisions:
        return revisions[-1]
    raise ProjectError(f"{ref} has no revisions in the hosted project.")


__all__ = [
    "HostedRevision",
    "PullStep",
    "PushResult",
    "PushStep",
    "hosted_list",
    "hosted_resource",
    "pull",
    "push",
    "resolve_hosted",
]
