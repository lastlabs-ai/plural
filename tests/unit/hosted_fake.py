"""An in-memory hosted Plural API for CLI and sync tests.

It follows the hosted contract the SDK depends on: parents addressed by slug,
immutable numbered revisions deduplicated by content hash, optional unique
release versions, stale pushes refused with 409 unless forced,
content-addressed packages, project-limited API keys, and accounts.
Content hashes come from ``hasher`` because recomputing them is the real
server's job and is verified against it separately.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from plural.sandbox.catalog import RUNTIME_PROVIDERS, runtime_from_settings, runtime_provider

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
    blobs: dict[str, bytes] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"id": "openai/gpt-5.6-luna", "name": "Luna", "provider": "openai"},
            {"id": "anthropic/claude-sonnet-5", "name": "Sonnet", "provider": "anthropic"},
        ]
    )
    organization_models: list[str] | None = None
    runtime_policy: dict[str, Any] = field(
        default_factory=lambda: {
            "account_type": "user",
            "can_manage": True,
            "mode": "open",
            "allowed_providers": None,
        }
    )
    runtime_templates: list[dict[str, Any]] = field(default_factory=list)
    runtimes: list[dict[str, Any]] = field(default_factory=list)
    sandboxes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # ``collection/slug`` pairs whose revision pushes fail with a 500.
    failing: set[str] = field(default_factory=set)
    # What ``GET /version`` reports; ``None`` answers 404, like an older server.
    server: dict[str, Any] | None = None
    _ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    def add_project(self, slug: str, *, account_id: str = "acc_personal") -> dict[str, Any]:
        project = {
            "id": f"prj_{next(self._ids)}",
            "slug": slug,
            "name": slug,
            "owner_account_id": account_id,
            "role": "manager",
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
            models = [m for m in self.models if provider in {None, m["provider"]}]
            if request.url.params.get("all") == "true":
                scope = "all"
            elif self.organization_models is None:
                scope = "account"
            else:
                scope = "organization"
                models = [m for m in models if m["id"] in self.organization_models]
            response = _ok(models)
            response.headers["X-Plural-Model-Scope"] = scope
            return response
        if parts == ["runtime-providers"]:
            return _ok([item.model_dump(mode="json") for item in RUNTIME_PROVIDERS])
        if parts == ["runtime-policy"]:
            if request.method == "PUT":
                self.runtime_policy.update(body)
            return _ok(self.runtime_policy)
        if parts and parts[0] == "runtime-templates":
            return self._runtime_templates(request, parts[1:], body)
        if parts and parts[0] == "projects":
            return self._projects(request, parts[1:], body, key, account)
        if parts and parts[0] == "packages":
            return self._packages(request, parts[1])
        if parts and parts[0] == "blobs":
            return self._blobs(request, parts[1])
        if parts == ["version"]:
            return _ok(self.server) if self.server is not None else _error(404, "Not Found")
        project_id = key.project_id or request.headers.get("x-project-id")
        if project_id not in self.projects:
            return _error(400, "Project is required")
        if parts == ["push"] and request.method == "POST" and self.server is not None:
            return self._push(request, project_id, body)
        if parts and parts[0] in COLLECTIONS:
            return self._collection(request, project_id, parts, body)
        if parts and parts[0] == "runtimes":
            return self._runtimes(request, parts[1:], body)
        if parts[:2] == ["compute", "sandboxes"]:
            return self._sandboxes(request, parts[2:], body)
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

    def _runtime_templates(
        self, request: httpx.Request, rest: list[str], body: Any
    ) -> httpx.Response:
        if not rest and request.method == "GET":
            return _ok(self.runtime_templates)
        if not rest and request.method == "POST":
            credentials = body.pop("credentials", {})
            body["credential_mode"] = _mode(body, credentials)
            template = {
                "id": f"rtt_{next(self._ids)}",
                "slug": body["name"].lower().replace(" ", "-"),
                "status": "active",
                "project_runtime_count": 0,
                "credential_hints": {key: "…" + value[-4:] for key, value in credentials.items()},
                **body,
            }
            self.runtime_templates.append(template)
            return _ok(template)
        template = next(
            (t for t in self.runtime_templates if rest[0] in {t["id"], t["slug"]}), None
        )
        if template is None:
            return _error(404, "Runtime template not found")
        if request.method == "PATCH":
            body.pop("credentials", None)
            template.update(body)
        if request.method == "DELETE":
            self.runtime_templates.remove(template)
            return httpx.Response(204)
        return _ok(template)

    def _runtime_view(self, runtime: dict[str, Any]) -> dict[str, Any]:
        template = next(
            (t for t in self.runtime_templates if t["id"] == runtime.get("template_id")), None
        )
        settings = {**(template["settings"] if template else {}), **runtime["overrides"]}
        mode = (template or runtime).get("credential_mode", "own")
        return {
            **runtime,
            "template": template,
            "settings": settings,
            "locked_fields": template["locked_fields"] if template else [],
            "credential_mode": mode,
            "credential_source": (
                "plural" if mode == "plural" else "template" if template else "runtime"
            ),
            "credentials_ready": mode == "plural" or bool(template or runtime["credential_hints"]),
            "environment_count": 0,
            "environment_runtime": runtime_from_settings(
                runtime["provider"], settings, ref=runtime["slug"]
            ).model_dump(mode="json"),
        }

    def _runtimes(self, request: httpx.Request, rest: list[str], body: Any) -> httpx.Response:
        if not rest and request.method == "GET":
            return _ok([self._runtime_view(item) for item in self.runtimes])
        if not rest and request.method == "POST":
            template = next(
                (t for t in self.runtime_templates if t["id"] == body.get("template_id")), None
            )
            credentials = body.get("credentials") or {}
            runtime = {
                "id": f"rt_{next(self._ids)}",
                "slug": body["name"].lower().replace(" ", "-"),
                "name": body["name"],
                "description": body.get("description", ""),
                "provider": template["provider"] if template else body["provider"],
                "template_id": template["id"] if template else None,
                "overrides": body.get("settings") or {},
                "credential_hints": {key: "…" + value[-4:] for key, value in credentials.items()},
                "credential_mode": "own" if template else _mode(body, credentials),
                "secrets": credentials,
            }
            self.runtimes.append(runtime)
            return _ok(self._runtime_view(runtime))
        runtime = next((r for r in self.runtimes if rest[0] in {r["id"], r["slug"]}), None)
        if runtime is None:
            return _error(404, "Runtime not found")
        if rest[1:] == ["credentials"]:
            mode = self._runtime_view(runtime)["credential_mode"]
            return _ok(
                {
                    "provider": runtime["provider"],
                    "credentials": mode,
                    "environ": {} if mode == "plural" else runtime["secrets"],
                }
            )
        if request.method == "PATCH" and "settings" in body:
            runtime["overrides"] = body["settings"]
        if request.method == "DELETE":
            self.runtimes.remove(runtime)
            return httpx.Response(204)
        return _ok(self._runtime_view(runtime))

    def _sandboxes(self, request: httpx.Request, rest: list[str], body: Any) -> httpx.Response:
        if not rest and request.method == "POST":
            sandbox = {
                "id": f"cs_{next(self._ids)}",
                "runtime": body["runtime"],
                "requirements": body["requirements"],
                "status": "running",
                "files": {},
                "commands": [],
                "image_identity": body["requirements"].get("image"),
            }
            self.sandboxes[sandbox["id"]] = sandbox
            return _ok({key: value for key, value in sandbox.items() if key != "files"})
        sandbox = self.sandboxes.get(rest[0])
        if sandbox is None:
            return _error(404, "Sandbox not found")
        if rest[1:] == ["exec"]:
            sandbox["commands"].append(body)
            return _ok({"exit_code": 0, "stdout": " ".join(body["command"]), "stderr": ""})
        if rest[1:] == ["files"]:
            path = request.url.params["path"]
            if request.method == "PUT":
                sandbox["files"][path] = request.content
                return httpx.Response(204)
            return httpx.Response(200, content=sandbox["files"][path])
        if request.method == "DELETE":
            sandbox["status"] = "ended"
        return _ok({key: value for key, value in sandbox.items() if key != "files"})

    def _blobs(self, request: httpx.Request, digest: str) -> httpx.Response:
        if request.method == "PUT":
            if "sha256:" + hashlib.sha256(request.content).hexdigest() != digest:
                return _error(422, "digest mismatch")
            self.blobs[digest] = request.content
            return _ok({"digest": digest, "size_bytes": len(request.content)})
        if digest not in self.blobs:
            return _error(404, "File not found")
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, content=self.blobs[digest])

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
            return _ok([self._parent_view(item) for item in parents.values()])
        if len(parts) == 1 and request.method == "POST":
            parent = {
                "id": f"{collection[:3]}_{next(self._ids)}",
                "slug": body["slug"],
                "name": body["name"],
                "description": body.get("description", ""),
                "visibility": "private",
                "current_revision_id": None,
            }
            self.parents[(project_id, collection, parent["slug"])] = parent
            self.revisions[parent["id"]] = []
            return _ok(parent)
        parent = next((p for p in parents.values() if parts[1] in {p["id"], p["slug"]}), None)
        if parent is None:
            return _error(404, "Not found")
        revisions = self.revisions[parent["id"]]
        if len(parts) == 2 and request.method == "PATCH":
            parent.update({key: body[key] for key in ("name", "description") if key in body})
            return _ok(self._parent_view(parent))
        if len(parts) == 2:
            return _ok(self._parent_view(parent))
        if len(parts) == 3 and request.method == "GET":
            return _ok(revisions)
        if len(parts) == 3 and request.method == "POST":
            if f"{collection}/{parent['slug']}" in self.failing:
                return _error(500, "Internal Server Error")
            content_hash = self.hasher(collection, parent["slug"], body)
            same = [r for r in revisions if r["content_hash"] == content_hash]
            if same:
                current = [r for r in same if r["id"] == parent.get("current_revision_id")]
                return _ok((current or same)[-1])
            current_id = parent.get("current_revision_id")
            forced = request.url.params.get("force") == "true"
            if current_id and body.get("parent_revision_id") != current_id and not forced:
                return _error(409, "stale revision: the resource changed since this edit began")
            version = body.get("version")
            if version and any(r["version"] == version for r in revisions):
                return _error(409, f"version {version} already names another revision")
            revision = {
                "id": f"rev_{next(self._ids)}",
                "number": len(revisions) + 1,
                "version": version,
                "content_hash": content_hash,
                "package_digest": request.url.params.get("package_digest"),
                "status": "available",
                "dependencies": self._dependencies(project_id, body),
                "parent_revision_id": body.get("parent_revision_id"),
                "lineage": body.get("lineage") or [],
                "payload": body,
                "definition": body,
            }
            revisions.append(revision)
            parent["current_revision_id"] = revision["id"]
            if body.get("title") or body.get("name"):
                parent["name"] = body.get("title") or body["name"]
            return _ok(revision)
        found = next((r for r in revisions if r["id"] == parts[3]), None)
        if found is None:
            return _error(404, "Not found")
        if len(parts) == 5 and parts[4] == "release" and request.method == "POST":
            version = body["version"]
            if found["version"] == version:
                return _ok(found)
            if found["version"] or any(r["version"] == version for r in revisions):
                return _error(409, f"version {version} is taken")
            found["version"] = version
            return _ok(found)
        return _ok(found)

    def _push(self, request: httpx.Request, project_id: str, body: Any) -> httpx.Response:
        before = copy.deepcopy((self.parents, self.revisions))
        saved: dict[str, str] = {}
        results = []
        collections = {kind: collection for collection, kind in KIND.items()}

        def resolve(value: Any) -> Any:
            if isinstance(value, list):
                return [resolve(item) for item in value]
            if isinstance(value, str) and value.startswith("batch:"):
                return saved[value.removeprefix("batch:")]
            return value

        for item in body["items"]:
            collection = collections[item["kind"]]
            revision = {key: resolve(value) for key, value in item["revision"].items()}
            if (project_id, collection, item["slug"]) not in self.parents:
                self._collection(
                    request,
                    project_id,
                    [collection],
                    {"slug": item["slug"], "name": item["name"]},
                )
            params = {"package_digest": item.get("package_digest") or ""}
            if body.get("force"):
                params["force"] = "true"
            inner = httpx.Request("POST", request.url.copy_with(params=params))
            response = self._collection(
                inner, project_id, [collection, item["slug"], "revisions"], revision
            )
            if response.status_code >= 400:
                self.parents, self.revisions = before
                detail = json.loads(response.content)["detail"]
                error = {"ref": item["ref"], "loc": [], "msg": detail}
                return httpx.Response(
                    response.status_code,
                    json={
                        "detail": f"Nothing was saved.\n{item['ref']}: {detail}",
                        "errors": [error],
                    },
                )
            row = json.loads(response.content)
            expected = item.get("content_hash")
            if expected and expected != row["content_hash"]:
                self.parents, self.revisions = before
                server_plural = (self.server or {}).get("plural")
                msg = f"the server computed {row['content_hash']}, the client {expected}"
                error = {
                    "ref": item["ref"],
                    "loc": [],
                    "msg": msg,
                    "type": "content_hash_mismatch",
                    "server_plural": server_plural,
                    "server_content_hash": row["content_hash"],
                    "client_content_hash": expected,
                    "definition": row["definition"],
                }
                return httpx.Response(
                    409,
                    json={"detail": f"Nothing was saved.\n{item['ref']}: {msg}", "errors": [error]},
                )
            saved[item["ref"]] = row["id"]
            results.append({"ref": item["ref"], "revision": row})
        if body.get("dry_run"):
            self.parents, self.revisions = before
        return _ok({"dry_run": bool(body.get("dry_run")), "items": results})

    def _parent_view(self, parent: dict[str, Any]) -> dict[str, Any]:
        current = next(
            (
                r
                for r in self.revisions[parent["id"]]
                if r["id"] == parent.get("current_revision_id")
            ),
            None,
        )
        return {
            **parent,
            "current_revision_number": current["number"] if current else None,
            "current_version": current["version"] if current else None,
        }

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


def _mode(body: dict[str, Any], credentials: dict[str, str]) -> str:
    """What the service stores: Plural's account by default where it is offered."""
    if body.get("credential_mode"):
        return str(body["credential_mode"])
    spec = runtime_provider(str(body.get("provider") or ""))
    return "plural" if spec and spec.plural_credentials and not credentials else "own"
