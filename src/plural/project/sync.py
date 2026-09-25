"""Push project resources to a hosted project and pull them back.

A push makes one immutable, private revision usable in the bound project. A
revision is identified by its version and canonical content hash, which the
SDK and the server compute identically, so pushing unchanged content reuses
the existing revision rather than creating a duplicate.

Every push is planned in full before anything is written: unresolved
references, cycles, dependencies that are not already hosted, and version
conflicts all fail with no upload. Resources are then pushed dependencies
first, so a parent is never saved pointing at a dependency that is missing.

A push never overwrites or deletes. It refuses to add a revision on top of a
hosted change this checkout has not synced, the way git refuses a
non-fast-forward push, unless the caller forces it.

Each revision also stores the resource's exact source package, addressed by
the SHA-256 of its archive, so ``pull`` restores the editable files.
"""

from __future__ import annotations

import hashlib
import re
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
    KINDS,
    TASK,
    Project,
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
    hosted = {item: _hosted_state(studio, item) for item in order}
    pins = _pins(workspace.project, binding.project_id)

    problems: list[str] = []
    resolved: dict[ResourceRef, HostedRevision] = {}
    to_push: list[ResourceRef] = []
    for item in order:
        resource = resources[item]
        parent, revisions = hosted[item]
        match, problem = _match(resource, revisions, workspace)
        if problem:
            problems.append(problem)
        elif match is not None:
            resolved[item] = match
        elif item != ref and not with_deps:
            latest = revisions[-1].version if revisions else None
            state = (
                f"changed locally since version {latest} was pushed" if latest else "not pushed yet"
            )
            problems.append(f"{item} {resource.version} is {state}")
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
    result.steps = _commit(workspace, studio, binding, order, resources, resolved, to_push)
    return result


def _commit(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    order: list[ResourceRef],
    resources: dict[ResourceRef, LocalResource],
    resolved: dict[ResourceRef, HostedRevision],
    to_push: list[ResourceRef],
) -> list[PushStep]:
    """Push ``to_push`` dependencies first and record every revision in the lock.

    Returns:
        One step per resource in ``order``.
    """
    steps: list[PushStep] = []
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
        steps.append(
            PushStep(
                ref=item,
                version=resource.version,
                content_hash=resource.content_hash,
                status=status,
                revision_id=revision.revision_id,
            )
        )
        workspace.project.write_lock(lock)
    return steps


@dataclass(frozen=True)
class ProjectPushStep:
    """What a project push will do for one resource."""

    ref: ResourceRef
    version: str
    content_hash: str
    action: Literal["new", "update", "unchanged"]
    previous_version: str | None = None
    hosted_version: str | None = None
    match: HostedRevision | None = None

    @property
    def bumped(self) -> bool:
        """Whether push gives this resource a new version."""
        return self.previous_version is not None and self.previous_version != self.version


@dataclass
class ProjectPushPlan:
    """Every local resource, dependencies first, and what push will do with it."""

    steps: list[ProjectPushStep]
    hosted_only: list[ResourceRef] = field(default_factory=list)

    @property
    def changes(self) -> list[ProjectPushStep]:
        """Steps that add a revision."""
        return [step for step in self.steps if step.action != "unchanged"]

    @property
    def bumps(self) -> dict[ResourceRef, str]:
        """New versions to write into local manifests before pushing."""
        return {step.ref: step.version for step in self.steps if step.bumped}


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
    bump: bool = False,
    force: bool = False,
) -> ProjectPushPlan:
    """Plan pushing every local resource without writing anything.

    A Task's content hash includes its dependencies, so changing an
    Environment changes each Task and Benchmark that pins it. With ``bump``,
    every resource whose version is taken by different content gets the next
    free patch version, repeated until its dependents settle. The plan is
    computed on a scratch copy, so local files change only in
    :func:`apply_project_push`.

    Args:
        workspace: Project resources.
        studio: Hosted API addressed to the target project, or ``None`` for a
            hosted project that does not exist yet.
        project_id: Target hosted project, used to trust ``plural.lock`` pins.
        bump: Give conflicting resources the next patch version.
        force: Allow new revisions on top of hosted changes this checkout has
            not synced.

    Returns:
        The plan.

    Raises:
        ProjectError: Listing every problem, before anything is uploaded.
    """
    project = workspace.project
    roots = local_refs(project)
    if not roots:
        raise ProjectError(
            "This project has no resources to push yet. Create one with `plural env init <name>`."
        )
    order = workspace.dependency_order(roots)
    hosted = {
        item: _hosted_state(studio, item) if studio is not None else (None, []) for item in order
    }
    pins = _pins(project, project_id)
    original = {item: workspace.load(item).version for item in order}

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / project.root.name
        shutil.copytree(project.root, root, ignore=shutil.ignore_patterns(*_SCRATCH_IGNORED))
        for _ in range(len(order) + 1):
            space = Workspace(Project.at(root), catalog=workspace.catalog)
            steps, conflicts, problems = _classify(space, order, hosted, pins, original, force)
            if not bump or not conflicts or problems:
                break
            for item in conflicts:
                taken = {revision.version for revision in hosted[item][1]}
                version = _next_patch(space.load(item).version, taken, item)
                _write_version(space.project.manifest_path(item), version)

    if conflicts and not bump:
        problems.extend(
            f"{item} {original[item]} is already pushed with different content; its files "
            "or a dependency changed."
            for item in conflicts
        )
    if problems:
        hint = (
            "\nRun again with --bump to give each changed resource the next patch version."
            if conflicts and not bump
            else ""
        )
        raise ProjectError(
            f"Cannot push project {project.name}; nothing was uploaded.{hint}", problems
        )

    hosted_only: list[ResourceRef] = []
    if studio is not None:
        local = set(order)
        for kind in KINDS:
            for record in hosted_list(studio, kind):
                ref = ResourceRef(kind.name, str(record.get("slug") or record.get("name")))
                if ref not in local:
                    hosted_only.append(ref)
    return ProjectPushPlan(steps=steps, hosted_only=hosted_only)


def apply_project_push(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    plan: ProjectPushPlan,
) -> list[PushStep]:
    """Write planned version bumps, then push every change dependencies first.

    Returns:
        One step per resource.

    Raises:
        ProjectError: When local files changed after the plan was made.
    """
    for ref, version in plan.bumps.items():
        _write_version(workspace.project.manifest_path(ref), version)
    space = Workspace(workspace.project, catalog=workspace.catalog)
    order = [step.ref for step in plan.steps]
    resources = {ref: space.load(ref) for ref in order}
    moved = [
        str(step.ref)
        for step in plan.steps
        if resources[step.ref].content_hash != step.content_hash
    ]
    if moved:
        raise ProjectError(
            "Local files changed after the push was planned; nothing was uploaded. "
            "Run the push again.",
            moved,
        )
    resolved = {step.ref: step.match for step in plan.steps if step.match is not None}
    to_push = [step.ref for step in plan.changes]
    return _commit(space, studio, binding, order, resources, resolved, to_push)


_SCRATCH_IGNORED = (".git", ".plural", ".venv", "__pycache__", "node_modules")
_VERSION_LINE = re.compile(r"^version:[ \t]*(['\"]?)([^'\"\s#]+)\1", re.MULTILINE)
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _classify(
    space: Workspace,
    order: list[ResourceRef],
    hosted: dict[ResourceRef, tuple[dict[str, Any] | None, list[HostedRevision]]],
    pins: dict[str, LockEntry],
    original: dict[ResourceRef, str],
    force: bool,
) -> tuple[list[ProjectPushStep], list[ResourceRef], list[str]]:
    steps: list[ProjectPushStep] = []
    conflicts: list[ResourceRef] = []
    problems: list[str] = []
    for item in order:
        resource = space.load(item)
        parent, revisions = hosted[item]
        current = _current(parent, revisions)
        problems.extend(_package_problems(resource, space))
        same = next(
            (
                revision
                for revision in revisions
                if revision.version == resource.version
                and revision.content_hash == resource.content_hash
            ),
            None,
        )
        action: Literal["new", "update", "unchanged"]
        if same is not None:
            action = "unchanged"
        elif any(revision.version == resource.version for revision in revisions):
            conflicts.append(item)
            action = "update"
        elif taken := next((r for r in revisions if r.content_hash == resource.content_hash), None):
            manifest = space.project.manifest_path(item).relative_to(space.project.root)
            problems.append(
                f"{item} is already pushed with this content as version {taken.version}. "
                f"Set `version: {taken.version}` in {manifest}."
            )
            action = "update"
        else:
            action = "new" if not revisions else "update"
        if action == "update" and not force:
            problems.extend(_diverged(item, parent, revisions, pins))
        steps.append(
            ProjectPushStep(
                ref=item,
                version=resource.version,
                content_hash=resource.content_hash,
                action=action,
                previous_version=original[item],
                hosted_version=current.version if current else None,
                match=same,
            )
        )
    return steps, conflicts, problems


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
            f"{ref} already exists in the hosted project at version {current.version}, but "
            f"this checkout has never pushed or pulled it. Pull it with {pull} to start from "
            "the hosted copy, or pass --force to add your version on top."
        ]
    if pinned.revision_id != current.revision_id:
        return [
            f"{ref} changed in the hosted project since this checkout last synced it "
            f"(hosted {current.version}, synced {pinned.version}). Pull it with {pull}, or "
            "pass --force to add your version on top."
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
    return next((item for item in revisions if item.revision_id == wanted), revisions[-1])


def _next_patch(version: str, taken: set[str], ref: ResourceRef) -> str:
    match = _SEMVER.match(version)
    if match is None:
        raise ProjectError(
            f"Cannot bump {ref}: version {version!r} is not MAJOR.MINOR.PATCH. "
            f"Set a new `version:` in {ref.info.directory}/{ref.name}/{ref.info.manifest}."
        )
    major, minor, patch = (int(part) for part in match.groups())
    while True:
        patch += 1
        candidate = f"{major}.{minor}.{patch}"
        if candidate not in taken:
            return candidate


def _write_version(manifest: Path, version: str) -> None:
    """Replace the top-level ``version:`` in one manifest, keeping comments and layout."""
    text = manifest.read_text(encoding="utf-8")
    updated, count = _VERSION_LINE.subn(
        lambda m: f"version: {m.group(1)}{version}{m.group(1)}", text, count=1
    )
    if count == 0:
        raise ProjectError(f"Cannot bump {manifest}: it has no top-level `version:` line.")
    manifest.write_text(updated, encoding="utf-8")


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
