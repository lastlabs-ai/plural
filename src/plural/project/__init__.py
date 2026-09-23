"""Plural projects: the standard directory layout and its resources.

A project is a directory containing ``project.yaml``. Each resource lives in
its own directory, such as ``tasks/refund/task.yaml``, and is named by that
directory. The CLI and the Python SDK share this package::

    from plural.project import Project, Workspace, ResourceRef

    workspace = Workspace(Project.find())
    task = workspace.load(ResourceRef("task", "refund")).value
"""

from __future__ import annotations

from plural.project.layout import (
    KINDS,
    Project,
    ProjectError,
    ResourceKind,
    ResourceRef,
    check_name,
    find_project_root,
    resource_kind,
)
from plural.project.manifests import LockEntry, LockFile, ProjectBinding, ProjectManifest
from plural.project.resources import LocalResource, Workspace
from plural.project.schemas import manifest_schemas, public_schema

__all__ = [
    "KINDS",
    "LocalResource",
    "LockEntry",
    "LockFile",
    "Project",
    "ProjectBinding",
    "ProjectError",
    "ProjectManifest",
    "ResourceKind",
    "ResourceRef",
    "Workspace",
    "check_name",
    "find_project_root",
    "manifest_schemas",
    "public_schema",
    "resource_kind",
]
