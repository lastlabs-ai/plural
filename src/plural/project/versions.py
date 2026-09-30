"""Resolve ``name@revision`` to an exact retained revision.

The working copy holds one revision of each resource. Every pushed revision
stays in the hosted project, immutable, so ``wordlebench@3``,
``wordlebench@1.0.0``, and ``wordlebench@sha256:...`` keep naming the same
revision after the working copy moves on. When a reference names a revision
the working copy does not hold, that revision and the exact revisions it pins
are restored into ``.plural/versions/<refs>/``, a project of their own that
shares this project's binding and Job records. The working copy is never
touched.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from plural.project.layout import (
    BINDING_FILE,
    PROJECT_FILE,
    Project,
    ProjectError,
    ResourceRef,
)
from plural.project.manifests import LockEntry, ProjectBinding
from plural.project.resources import Workspace
from plural.project.sync import pull
from plural.studio import Studio

_PROJECT_FILES = (PROJECT_FILE, "pyproject.toml")


def versioned(ref: ResourceRef, selector: str) -> str:
    """``benchmark/wordlebench@3``: a resource reference with a revision selector.

    Returns:
        The reference text.
    """
    return f"{ref}@{selector}"


def names(entry: LockEntry | None, selector: str) -> bool:
    """Whether ``selector`` (a number, version, or content hash) names the locked revision.

    Returns:
        ``True`` on a match.
    """
    if entry is None:
        return False
    wanted = selector.strip().lstrip("#")
    if wanted.isdigit():
        return entry.number == int(wanted)
    if wanted.startswith("sha256:"):
        return entry.content_hash == wanted
    return entry.version == wanted


def holds_version(workspace: Workspace, ref: ResourceRef, selector: str) -> bool:
    """Whether the working copy of ``ref`` is exactly the revision ``selector`` names.

    Content decides: the working copy holds a revision only when its files
    hash to what that revision holds, so an edited copy never passes for it.

    Returns:
        ``True`` when running the working copy runs that revision.
    """
    if not workspace.project.has(ref):
        return False
    digest = workspace.load(ref).content_hash
    if selector.startswith("sha256:"):
        return digest == selector
    entry = workspace.project.read_lock().resources.get(str(ref))
    return names(entry, selector) and entry is not None and entry.content_hash == digest


def version_workspace(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    versions: Mapping[ResourceRef, str],
    *,
    carry: Iterable[ResourceRef] = (),
) -> Workspace:
    """A workspace holding the requested hosted revisions, keyed by revision selector.

    ``carry`` names working-copy resources to use alongside them, such as an
    unversioned Agent run against a retained Benchmark. They are copied fresh
    on every call, together with their local dependencies.

    Returns:
        A workspace rooted under ``.plural/versions``.

    Raises:
        ProjectError: When a revision is not in the hosted project.
    """
    if not versions:
        raise ProjectError("Name at least one revision to restore.")
    root = workspace.project.versions_dir / "+".join(
        f"{ref.kind}-{ref.name}@{_safe(selector)}" for ref, selector in sorted(versions.items())
    )
    _prepare(workspace.project, root)
    shadow = Workspace(Project.at(root), catalog=workspace.catalog)
    for ref, selector in sorted(versions.items()):
        if holds_version(shadow, ref, selector):
            continue
        pull(
            shadow,
            studio,
            ref,
            selector=selector,
            force=True,
            with_deps=True,
            project_id=binding.project_id,
        )
        shadow = Workspace(Project.at(root), catalog=workspace.catalog)
    carried = [ref for ref in carry if ref not in versions]
    for ref in workspace.dependency_order(carried) if carried else ():
        if ref in versions:
            continue
        target = shadow.project.resource_dir(ref)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(workspace.project.resource_dir(ref), target)
    return Workspace(Project.at(root), catalog=workspace.catalog)


def _safe(selector: str) -> str:
    return selector.strip().lstrip("#").replace(":", "-")[:23]


def _prepare(project: Project, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in _PROJECT_FILES:
        source = project.root / name
        if source.is_file():
            shutil.copyfile(source, root / name)
    state = root / ".plural"
    state.mkdir(exist_ok=True)
    binding = project.state_dir / BINDING_FILE
    if binding.is_file():
        shutil.copyfile(binding, state / BINDING_FILE)
    project.jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs = state / "jobs"
    if not jobs.exists() and not jobs.is_symlink():
        os.symlink(project.jobs_dir, jobs, target_is_directory=True)
