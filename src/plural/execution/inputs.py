"""Materialize per-Trial inputs and resolve launch-time declarations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from plural.environments.definition import EnvironmentDefinition, EnvironmentResource
from plural.sandbox.models import FileUpload

ResourceResolver = Callable[[EnvironmentResource], bytes]
MAX_RESOURCE_BYTES = 16 * 1024 * 1024


def runtime_values(
    environment: EnvironmentDefinition, environ: Mapping[str, str], *, target: str = "environment"
) -> tuple[dict[str, str], dict[str, str]]:
    values: dict[str, str] = {}
    secrets: dict[str, str] = {}
    declarations: list[Any] = list(environment.runtime.variables) if target == "environment" else []
    declarations += [item for item in environment.secrets if item.target == target]
    for item in declarations:
        value = environ.get(item.name)
        if value is None or value == "":
            if item.required:
                raise ValueError(f"Missing required runtime variable: {item.name}")
            continue
        kind = getattr(item, "format", "text")
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
        if getattr(item, "secret", True):
            secrets[item.name] = value
    return values, secrets


def resource_uploads(
    shared: tuple[EnvironmentResource, ...],
    task: tuple[EnvironmentResource, ...],
    source: Path | None,
    resolvers: Mapping[str, ResourceResolver],
) -> tuple[FileUpload, ...]:
    uploads: list[FileUpload] = []
    manifest: list[dict[str, Any]] = []
    for scope, resources in (("shared", shared), ("task", task)):
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
            destination = f"{scope}/{path}"
            uploads.append(FileUpload(path=destination, data=data))
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
            data=json.dumps({"schema_version": 1, "resources": manifest}, sort_keys=True).encode(),
        )
    )
    return tuple(uploads)
