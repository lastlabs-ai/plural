"""Resolve ``name@version`` to an exact retained version.

The working copy holds one version of each resource. Every pushed version
stays in the hosted project, immutable, so ``wordlebench@0.1.1`` keeps naming
the same revision after the working copy moves on. When a reference names a
version the working copy does not hold, that version and the exact revisions
it pins are restored into ``.plural/versions/<refs>/``, a project of their
own that shares this project's binding and Job records. The working copy is
never touched.
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
from plural.project.manifests import ProjectBinding
from plural.project.resources import Workspace
from plural.project.sync import pull
from plural.studio import Studio

_PROJECT_FILES = (PROJECT_FILE, "pyproject.toml")


def versioned(ref: ResourceRef, version: str) -> str:
    """``benchmark/wordlebench@0.1.1``: a resource reference with its version.

    Returns:
        The reference text.
    """
    return f"{ref}@{version}"


def holds_version(workspace: Workspace, ref: ResourceRef, version: str) -> bool:
    """Whether the working copy of ``ref`` is exactly ``version``.

    A local copy that declares the version but no longer matches what was
    pushed under it has been edited without a bump, so it is not that version.

    Returns:
        ``True`` when running the working copy runs ``version``.
    """
    if not workspace.project.has(ref):
        return False
    resource = workspace.load(ref)
    if resource.version != version:
        return False
    entry = workspace.project.read_lock().resources.get(str(ref))
    return entry is None or entry.version != version or entry.content_hash == resource.content_hash


def version_workspace(
    workspace: Workspace,
    studio: Studio,
    binding: ProjectBinding,
    versions: Mapping[ResourceRef, str],
    *,
    carry: Iterable[ResourceRef] = (),
) -> Workspace:
    """A workspace holding the requested hosted versions.

    ``carry`` names working-copy resources to use alongside them, such as an
    unversioned Agent run against a retained Benchmark. They are copied fresh
    on every call, together with their local dependencies.

    Returns:
        A workspace rooted under ``.plural/versions``.

    Raises:
        ProjectError: When a version is not in the hosted project.
    """
    if not versions:
        raise ProjectError("Name at least one version to restore.")
    root = workspace.project.versions_dir / "+".join(
        f"{ref.kind}-{ref.name}@{version}" for ref, version in sorted(versions.items())
    )
    _prepare(workspace.project, root)
    shadow = Workspace(Project.at(root), catalog=workspace.catalog)
    for ref, version in sorted(versions.items()):
        if shadow.project.has(ref) and shadow.load(ref).version == version:
            continue
        pull(
            shadow,
            studio,
            ref,
            version=version,
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
