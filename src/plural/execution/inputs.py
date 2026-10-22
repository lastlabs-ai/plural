"""Materialize per-Trial inputs and resolve launch-time declarations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from plural.blobs import read_blob
from plural.environments.definition import EnvironmentDefinition, EnvironmentResource
from plural.mcp import ENVIRONMENT_RESOURCES, TASK_RESOURCES
from plural.sandbox.models import FileUpload

ResourceResolver = Callable[[EnvironmentResource], bytes]
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
RESOURCES_ROOT = "/workspace/resources"


def runtime_values(
    environment: EnvironmentDefinition, environ: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Values for the Runtime's declared variables, and which of them are secret.

    App secrets are resolved separately, because only the App host receives them.

    Returns:
        All values, and the secret subset for redaction.
    """
    values: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for item in environment.runtime.variables:
        value = environ.get(item.name)
        if value is None or value == "":
            if item.required:
                raise ValueError(f"Missing required runtime variable: {item.name}")
            continue
        kind = item.format
        try:
            if kind == "integer":
                int(value)
            elif kind == "json":
                json.loads(value)
            elif kind == "url" and not (urlsplit(value).scheme and urlsplit(value).netloc):
                raise ValueError("invalid URL")
        except (ValueError, TypeError):
            raise ValueError(f"Runtime variable {item.name} must contain {kind}") from None
        values[item.name] = value
        if item.secret:
            secrets[item.name] = value
    return values, secrets


def resource_uploads(
    shared: tuple[EnvironmentResource, ...],
    task: tuple[EnvironmentResource, ...],
    source: Path | None,
    resolvers: Mapping[str, ResourceResolver],
) -> tuple[FileUpload, ...]:
    """Stage the Environment's and the Task's resources, each in its own read-only folder.

    The folders are volumes the Trial references, not files it owns, so they are
    staged read-only and never share a path.

    Returns:
        The files to upload under the resources root, and their manifest.
    """
    uploads: list[FileUpload] = []
    manifest: list[dict[str, Any]] = []
    for scope, folder, resources in (
        ("environment", ENVIRONMENT_RESOURCES, shared),
        ("task", TASK_RESOURCES, task),
    ):
        paths: set[str] = set()
        for item in resources:
            if item.delivery == "descriptor":
                manifest.append(
                    {"scope": scope, "name": item.name, "delivery": "descriptor", "uri": item.uri}
                )
                continue
            path = item.path or ""
            if any(
                path == old or path.startswith(old + "/") or old.startswith(path + "/")
                for old in paths
            ):
                raise ValueError(f"Conflicting resource path in {scope}: {path}")
            paths.add(path)
            if item.delivery == "inline":
                data = (item.content or "").encode()
            elif item.delivery == "blob":
                try:
                    data = read_blob(item.digest or "")
                except FileNotFoundError as exc:
                    raise ValueError(f"Resource {item.name}: {exc}") from None
            elif item.delivery == "source":
                if source is None:
                    raise ValueError(f"Resource {item.name} needs Environment source files")
                location = (source / path).resolve()
                if not location.is_relative_to(source.resolve()) or not location.is_file():
                    raise ValueError(
                        f"Resource {item.name} is not a file inside Environment source"
                    )
                with location.open("rb") as stream:
                    data = stream.read(MAX_RESOURCE_BYTES + 1)
            else:
                resolver = resolvers.get(item.resolver or "")
                if resolver is None:
                    raise ValueError(f"Resource {item.name} needs resolver: {item.resolver}")
                data = resolver(item)
            if not isinstance(data, bytes) or len(data) > MAX_RESOURCE_BYTES:
                raise ValueError(f"Resource {item.name} must return at most 16 MiB of bytes")
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            if item.digest is not None and item.digest != digest:
                raise ValueError(f"Resource {item.name} does not match its expected digest")
            destination = f"{folder}/{path}"
            uploads.append(FileUpload(path=destination, data=data, mode=0o444))
            manifest.append(
                {
                    "scope": scope,
                    "name": item.name,
                    "path": destination,
                    "digest": digest,
                    "delivery": item.delivery,
                }
            )
    uploads.append(
        FileUpload(
            path="manifest.json",
            data=json.dumps({"schema_version": 2, "resources": manifest}, sort_keys=True).encode(),
            mode=0o444,
        )
    )
    return tuple(uploads)
