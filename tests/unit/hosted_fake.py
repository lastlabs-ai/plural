"""An in-memory hosted Plural API for CLI and sync tests.

It follows the hosted contract the SDK depends on: parents addressed by slug,
immutable revisions deduplicated by version and content hash, conflicts as
409, content-addressed packages, project-limited API keys, and accounts.
Content hashes come from ``hasher`` because recomputing them is the real
server's job and is verified against it separately.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

Hasher = Callable[[str, str, dict[str, Any]], str]
COLLECTIONS = ("environments", "verifiers", "harnesses", "tasks", "agents", "benchmarks")
KIND = {
    "environments": "environment",
    "verifiers": "verifier",
    "harnesses": "harness",
    "tasks": "task",
    "agents": "agent",
    "benchmarks": "benchmark",
}


@dataclass
class Key:
    """One bearer credential the fake accepts."""

    kind: str = "login"
    account_id: str | None = None
    project_id: str | None = None


@dataclass
class FakeHosted:
    hasher: Hasher
    keys: dict[str, Key] = field(default_factory=lambda: {"token": Key()})
    accounts: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"id": "acc_personal", "type": "personal", "slug": "me", "display_name": "Me"},
            {"id": "acc_org", "type": "organization", "slug": "acme", "display_name": "Acme"},
        ]
    )
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    parents: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    revisions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    packages: dict[str, bytes] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"id": "openai/gpt-5.6-luna", "name": "Luna", "provider": "openai"},
            {"id": "anthropic/claude-sonnet-5", "name": "Sonnet", "provider": "anthropic"},
        ]
    )
    _ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    def add_project(self, slug: str, *, account_id: str = "acc_personal") -> dict[str, Any]:
        project = {
            "id": f"prj_{next(self._ids)}",
            "slug": slug,
            "name": slug,
            "owner_account_id": account_id,
            "visibility": "private",
            "role": "admin",
        }
        self.projects[project["id"]] = project
        return project

    @property
    def writes(self) -> list[tuple[str, str]]:
        return [item for item in self.requests if item[0] in {"POST", "PUT", "PATCH", "DELETE"}]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        key = self.keys.get(token)
        if key is None:
            return _error(401, "Invalid credentials")
        path = request.url.path.removeprefix("/api/v1")
        parts = [item for item in path.split("/") if item]
        body = (
            json.loads(request.content)
            if request.headers.get("content-type", "").startswith("application/json")
            and request.content
            else None
        )
        account = key.account_id or request.headers.get("x-account-id") or "acc_personal"
        if parts == ["auth", "status"]:
            return _ok(
                {
                    "authenticated": True,
                    "subject": "usr_1",
                    "credential": key.kind,
                    "account_id": key.account_id,
                    "project_id": key.project_id,
                }
            )
        if parts == ["accounts"]:
            visible = [a for a in self.accounts if key.account_id in {None, a["id"]}]
            return _ok(visible)
        if parts == ["models"]:
            provider = request.url.params.get("provider")
            return _ok([m for m in self.models if provider in {None, m["provider"]}])
        if parts and parts[0] == "projects":
            return self._projects(request, parts[1:], body, key, account)
        if parts and parts[0] == "packages":
            return self._packages(request, parts[1])
        project_id = key.project_id or request.headers.get("x-project-id")
        if project_id not in self.projects:
            return _error(400, "Project is required")
        if parts and parts[0] in COLLECTIONS:
            return self._collection(request, project_id, parts, body)
        if parts == ["jobs"] and request.method == "POST":
            job = {"id": f"job_{next(self._ids)}", "status": "queued", **(body or {})}
            self.jobs.append(job)
            return _ok(job)
        if parts == ["jobs"]:
            return _ok(self.jobs)
        return _error(404, f"no route {request.method} {path}")

    def _projects(
        self,
        request: httpx.Request,
        rest: list[str],
        body: Any,
        key: Key,
        account: str,
    ) -> httpx.Response:
        if not rest and request.method == "GET":
            return _ok(
                [
                    p
                    for p in self.projects.values()
                    if p["owner_account_id"] == account and key.project_id in {None, p["id"]}
                ]
            )
        if not rest and request.method == "POST":
            if key.project_id:
                return _error(403, "Project API keys cannot create projects")
            return _ok(self.add_project(str(body["name"]), account_id=account))
        project = self.projects.get(rest[0])
        if project is None or key.project_id not in {None, project["id"]}:
            return _error(404, "Project not found")
        return _ok(project)

    def _packages(self, request: httpx.Request, digest: str) -> httpx.Response:
        if request.method == "PUT":
            if "sha256:" + hashlib.sha256(request.content).hexdigest() != digest:
                return _error(422, "digest mismatch")
            self.packages[digest] = request.content
            return httpx.Response(204)
        if digest not in self.packages:
            return _error(404, "Package not found")
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, content=self.packages[digest])

    def _collection(
        self, request: httpx.Request, project_id: str, parts: list[str], body: Any
    ) -> httpx.Response:
        collection = parts[0]
        parents = {k[2]: v for k, v in self.parents.items() if k[:2] == (project_id, collection)}
        if len(parts) == 1 and request.method == "GET":
            return _ok(list(parents.values()))
        if len(parts) == 1 and request.method == "POST":
            parent = {
                "id": f"{collection[:3]}_{next(self._ids)}",
                "slug": body["slug"],
                "name": body["name"],
                "description": body.get("description", ""),
                "visibility": "private",
            }
            self.parents[(project_id, collection, parent["slug"])] = parent
            self.revisions[parent["id"]] = []
            return _ok(parent)
        parent = next((p for p in parents.values() if parts[1] in {p["id"], p["slug"]}), None)
        if parent is None:
            return _error(404, "Not found")
        if len(parts) == 2:
            return _ok(parent)
        revisions = self.revisions[parent["id"]]
        if len(parts) == 3 and request.method == "GET":
            return _ok(revisions)
        if len(parts) == 3 and request.method == "POST":
            content_hash = self.hasher(collection, parent["slug"], body)
            for existing in revisions:
                same_version = existing["version"] == body["version"]
                same_hash = existing["content_hash"] == content_hash
                if same_version and same_hash:
                    return _ok(existing)
                if same_version or same_hash:
                    return _error(409, "revision conflict")
            revision = {
                "id": f"rev_{next(self._ids)}",
                "version": body["version"],
                "content_hash": content_hash,
                "package_digest": request.url.params.get("package_digest"),
                "status": "available",
                "dependencies": self._dependencies(project_id, body),
                "payload": body,
            }
            revisions.append(revision)
            return _ok(revision)
        found = next((r for r in revisions if r["id"] == parts[3]), None)
        return _ok(found) if found else _error(404, "Not found")

    def _dependencies(self, project_id: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        ids: list[str] = []
        for field_name in ("environment_revision_id", "harness_revision_id"):
            if body.get(field_name):
                ids.append(body[field_name])
        for field_name in ("verifier_revision_ids", "task_revision_ids"):
            ids.extend(body.get(field_name) or [])
        output = []
        for revision_id in ids:
            for (project, collection, slug), parent in self.parents.items():
                if project != project_id:
                    continue
                if any(r["id"] == revision_id for r in self.revisions[parent["id"]]):
                    output.append(
                        {"kind": KIND[collection], "slug": slug, "revision_id": revision_id}
                    )
        return output

    def revision_count(self) -> int:
        return sum(len(items) for items in self.revisions.values())


def _ok(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _error(status: int, detail: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": detail})


@contextmanager
def routed(monkeypatch: pytest.MonkeyPatch, fake: FakeHosted) -> Iterator[FakeHosted]:
    """Send every ``httpx`` call made by the SDK and CLI to ``fake``."""
    transport = httpx.MockTransport(fake)
    real_client = httpx.Client
    client = real_client(transport=transport)

    def make_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", make_client)
    monkeypatch.setattr(httpx, "request", client.request)
    monkeypatch.setattr(httpx, "stream", client.stream)
    yield fake
