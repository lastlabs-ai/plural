"""Hosted Plural API: projects, resource revisions, packages, Jobs, and reviews."""

# Public method names map directly to HTTP operations; class-level API
# documentation carries the contract.
# ruff: noqa: D101, D102, DOC201

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from plural.agents import Agent
from plural.environments.definition import EnvironmentDefinition
from plural.errors import (
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PluralError,
)
from plural.harness.models import Harness, HarnessDefinition
from plural.jobs import JobSpec
from plural.tasks import Benchmark, Task
from plural.tracing.schema import Trace
from plural.verifiers import DeterministicVerifier, HumanVerifier

if TYPE_CHECKING:
    from plural.client import Client

JsonObject = dict[str, Any]
JsonList = list[JsonObject]
T = TypeVar("T", bound=BaseModel)


def slugify(name: str, *, fallback: str = "item") -> str:
    """Return a project-safe resource slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or fallback


def studio_base_url(gateway_base: str) -> str:
    """Map a model gateway URL to the hosted API root."""
    root = gateway_base.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return f"{root.rstrip('/')}/api/v1"


def _raise_http(response: httpx.Response) -> None:
    try:
        body = response.json()
        detail = str(body.get("detail") or body.get("message") or "")
    except Exception:
        detail = response.text.strip()
    message = detail or response.reason_phrase or "request failed"
    error_type = {
        400: InvalidRequestError,
        401: AuthenticationError,
        403: AuthenticationError,
        404: NotFoundError,
        409: ConflictError,
        422: InvalidRequestError,
    }.get(response.status_code, PluralError)
    raise error_type(message, status_code=response.status_code)


def _items(response: Any) -> JsonList:
    if isinstance(response, dict):
        return cast(JsonList, response.get("items", []))
    return cast(JsonList, response)


def _dump(value: Any, *, exclude: set[str] | None = None) -> JsonObject:
    if not isinstance(value, BaseModel):
        raise InvalidRequestError("canonical SDK object must be a Pydantic model")
    return value.model_dump(mode="json", exclude_none=True, exclude=exclude or set())


class RevisionResourceAPI(Generic[T]):
    """Parents addressed by slug, each with immutable revisions.

    A pushed revision is usable as soon as it is saved. Pushing the same
    version with the same content returns the existing revision; the same
    version with different content is rejected by the server.
    """

    collection: str
    model_type: type[Any]

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, **params: Any) -> JsonList:
        response = self._studio.request("GET", f"/{self.collection}", params=params)
        return _items(response)

    def get(self, resource_id: str) -> JsonObject:
        return cast(
            JsonObject, self._studio.request("GET", f"/{self.collection}/{quote(resource_id)}")
        )

    def find(self, slug: str) -> JsonObject | None:
        try:
            return self.get(slug)
        except NotFoundError:
            return None

    def create(self, *, name: str, slug: str | None = None, description: str = "") -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/{self.collection}",
                json={"name": name, "slug": slug, "description": description},
            ),
        )

    def update(self, resource_id: str, **fields: Any) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request("PATCH", f"/{self.collection}/{quote(resource_id)}", json=fields),
        )

    def delete(self, resource_id: str) -> None:
        self._studio.request("DELETE", f"/{self.collection}/{quote(resource_id)}")

    def revisions(self, resource_id: str) -> JsonList:
        return cast(
            JsonList,
            self._studio.request("GET", f"/{self.collection}/{quote(resource_id)}/revisions"),
        )

    def revision(self, resource_id: str, revision_id: str) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "GET", f"/{self.collection}/{quote(resource_id)}/revisions/{quote(revision_id)}"
            ),
        )

    def parent(self, name: str, *, description: str = "") -> JsonObject:
        """Return the parent with this name's slug, creating it if needed."""
        slug = slugify(name, fallback=self.collection.rstrip("s"))
        return self.find(slug) or self.create(name=name, slug=slug, description=description)

    @staticmethod
    def _name(value: Any) -> str:
        name = getattr(value, "name", None) or getattr(value, "task_id", None)
        if not isinstance(name, str) or not name:
            raise InvalidRequestError("revision object has no parent name")
        return name

    def _revision_payload(self, value: Any, **references: Any) -> JsonObject:
        del references
        return _dump(value, exclude={"name", "description"})

    def push(self, value: T, *, package_digest: str | None = None, **references: Any) -> JsonObject:
        if not isinstance(value, self.model_type):
            raise InvalidRequestError(f"{self.collection} push requires {self.model_type.__name__}")
        parent = self.parent(
            self._name(value), description=str(getattr(value, "description", "") or "")
        )
        payload = self._revision_payload(value, **references)
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/{self.collection}/{quote(str(parent['id']))}/revisions",
                json=payload,
                params={"package_digest": package_digest} if package_digest else None,
            ),
        )


class EnvironmentsAPI(RevisionResourceAPI[EnvironmentDefinition]):
    collection = "environments"
    model_type = EnvironmentDefinition

    def stamp_harness(
        self,
        *,
        environment_id: str,
        revision_id: str,
        harness_revision_id: str,
        compatible: bool = True,
        evidence: dict[str, Any] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                (
                    f"/environments/{quote(environment_id)}/revisions/"
                    f"{quote(revision_id)}/harness-evidence"
                ),
                json={
                    "harness_revision_id": harness_revision_id,
                    "compatible": compatible,
                    "evidence": evidence or {},
                },
            ),
        )


class TasksAPI(RevisionResourceAPI[Task]):
    collection = "tasks"
    model_type = Task

    def _revision_payload(self, value: Task, **references: Any) -> JsonObject:
        environment_revision_id = references.get("environment_revision_id")
        verifier_revision_ids = references.get("verifier_revision_ids")
        if not isinstance(environment_revision_id, str) or not environment_revision_id:
            raise InvalidRequestError("Task push requires environment_revision_id")
        if not isinstance(verifier_revision_ids, Sequence) or isinstance(
            verifier_revision_ids, (str, bytes)
        ):
            raise InvalidRequestError("Task push requires verifier_revision_ids")
        ids = [str(item) for item in verifier_revision_ids]
        if len(ids) != len(value.verifiers):
            raise InvalidRequestError("verifier_revision_ids must align with Task verifiers")
        payload = _dump(
            value,
            exclude={"name", "environment", "verifiers"},
        )
        payload["environment_revision_id"] = environment_revision_id
        payload["verifier_revision_ids"] = ids
        return payload


class VerifiersAPI(RevisionResourceAPI[Any]):
    collection = "verifiers"
    model_type = BaseModel

    def push(
        self, value: Any, *, package_digest: str | None = None, **references: Any
    ) -> JsonObject:
        if getattr(value, "kind", None) not in {"deterministic", "agent", "human"}:
            raise InvalidRequestError("Verifier push requires a Verifier")
        return super().push(value, package_digest=package_digest, **references)

    def _revision_payload(self, value: Any, **references: Any) -> JsonObject:
        del references
        return _dump(value, exclude={"name"})


class AgentsAPI(RevisionResourceAPI[Agent]):
    collection = "agents"
    model_type = Agent

    def _revision_payload(self, value: Agent, **references: Any) -> JsonObject:
        harness_revision_id = references.get("harness_revision_id")
        builtin = value.harness if isinstance(value.harness, str) else None
        if value.harness is not None and builtin is None and not harness_revision_id:
            raise InvalidRequestError("An Agent with a custom Harness needs harness_revision_id")
        payload = _dump(value, exclude={"name", "harness"})
        payload["harness"] = builtin
        payload["harness_revision_id"] = harness_revision_id
        return payload


class HarnessesAPI(RevisionResourceAPI[HarnessDefinition]):
    collection = "harnesses"
    model_type = HarnessDefinition

    def _revision_payload(self, value: HarnessDefinition, **references: Any) -> JsonObject:
        del references
        return _dump(value)


class BenchmarksAPI(RevisionResourceAPI[Benchmark]):
    collection = "benchmarks"
    model_type = Benchmark

    def _revision_payload(self, value: Benchmark, **references: Any) -> JsonObject:
        task_revision_ids = references.get("task_revision_ids")
        if not isinstance(task_revision_ids, Sequence) or isinstance(
            task_revision_ids, (str, bytes)
        ):
            raise InvalidRequestError("Benchmark push requires task_revision_ids")
        ids = [str(item) for item in task_revision_ids]
        if len(ids) != len(value.tasks):
            raise InvalidRequestError("task_revision_ids must align with Benchmark tasks")
        payload = _dump(value, exclude={"name", "tasks"})
        payload["task_revision_ids"] = ids
        return payload


class ProjectsAPI:
    """Projects visible to the credential within the selected account."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self) -> JsonList:
        return cast(JsonList, self._studio.request("GET", "/projects", project=False))

    def get(self, project_id: str) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request("GET", f"/projects/{quote(project_id)}", project=False),
        )

    def find(self, name: str) -> JsonObject | None:
        """Match a project by id, slug, or exact name."""
        for item in self.list():
            if name in {item.get("id"), item.get("slug"), item.get("name")}:
                return item
        return None

    def create(self, *, name: str, description: str = "") -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/projects",
                json={"name": name, "description": description},
                project=False,
            ),
        )


class AccountsAPI:
    """Personal and organization accounts the signed-in user may act for."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self) -> JsonList:
        return cast(JsonList, self._studio.request("GET", "/accounts", project=False))


class PackagesAPI:
    """Content-addressed resource packages within the selected project.

    A package is the exact source tree of one resource revision. Its digest is
    the SHA-256 of the archive bytes, so an upload is idempotent and a download
    is verified before use.
    """

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def exists(self, digest: str) -> bool:
        try:
            self._studio.request("HEAD", f"/packages/{quote(digest)}")
        except NotFoundError:
            return False
        return True

    def upload(self, digest: str, data: bytes) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "PUT",
                f"/packages/{quote(digest)}",
                content=data,
                content_type="application/gzip",
            ),
        )

    def download(self, digest: str) -> bytes:
        return self._studio.request_bytes("GET", f"/packages/{quote(digest)}")


class ModelsAPI:
    """Models the selected account may use, after organization policy."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, *, provider: str | None = None) -> JsonList:
        params = {"provider": provider} if provider else None
        response = self._studio.request("GET", "/models", params=params)
        return _items(response)


class TracesAPI:
    """Canonical Trace ingest, TITO upload, and reads."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, **params: Any) -> JsonList:
        response = self._studio.request("GET", "/traces", params=params)
        return _items(response)

    def get(self, trace_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/traces/{trace_id}"))

    def create(self, trace: Trace | JsonObject, **links: Any) -> JsonObject:
        payload = trace.model_dump(mode="json") if isinstance(trace, Trace) else trace
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/traces",
                json={"trace": payload, **{k: v for k, v in links.items() if v is not None}},
            ),
        )

    def upload_tito(
        self,
        trace_id: str,
        data: bytes,
        *,
        content_type: str = "application/x-ndjson; profile=tito-v1",
    ) -> JsonObject:
        """Upload immutable, server-validated TITO NDJSON for a hosted Trace."""
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/traces/{quote(trace_id, safe='')}/artifacts/tito",
                content=data,
                content_type=content_type,
            ),
        )


class JobsAPI:
    """Hosted Job submission, reruns, transitions, and live events."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def submit(
        self,
        spec: JobSpec,
        *,
        source_revision_id: str,
        agent_revision_ids: Sequence[str],
        idempotency_key: str,
        name: str = "Job",
        description: str = "",
        executor: Literal["hosted", "client"] = "hosted",
        client_job_id: str | None = None,
    ) -> JsonObject:
        """Create a hosted Job from pushed revisions.

        ``executor="client"`` records a Job that this client runs and reports,
        as ``plural run --track`` does; hosted workers never claim its Trials.
        ``client_job_id`` names the client's own record of it.
        """
        if len(agent_revision_ids) != len(spec.agents):
            raise InvalidRequestError("agent_revision_ids must align with Job agents")
        extra: dict[str, Any] = {}
        if executor != "hosted":
            extra["executor"] = executor
        if client_job_id is not None:
            extra["client_job_id"] = client_job_id
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/jobs",
                json={
                    "name": name,
                    "description": description,
                    "source": {
                        "type": spec.source.kind,
                        "revision_id": source_revision_id,
                    },
                    "agent_revision_ids": list(agent_revision_ids),
                    "attempts": spec.attempts,
                    "concurrency": spec.concurrency,
                    "per_runtime_concurrency": spec.per_runtime_concurrency,
                    "priority": spec.priority,
                    "retry": spec.retry.model_dump(mode="json"),
                    "mode": spec.mode.value,
                    "idempotency_key": idempotency_key,
                    **extra,
                },
            ),
        )

    def rerun(self, job_id: str, *, idempotency_key: str) -> JsonObject:
        """Create a new Job from the exact revisions and settings of ``job_id``."""
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/jobs/{quote(job_id)}/rerun",
                json={"idempotency_key": idempotency_key},
            ),
        )

    def list(self, **params: Any) -> JsonList:
        response = self._studio.request("GET", "/jobs", params=params)
        return _items(response)

    def get(self, job_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/jobs/{quote(job_id)}"))

    def trials(self, job_id: str) -> JsonList:
        return cast(JsonList, self._studio.request("GET", f"/jobs/{quote(job_id)}/trials"))

    def transition(self, job_id: str, status: str, **fields: Any) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST", f"/jobs/{quote(job_id)}/transition", json={"status": status, **fields}
            ),
        )

    def cancel(self, job_id: str) -> JsonObject:
        return self.transition(job_id, "cancelled")

    def watch(self, job_id: str, *, cursor: int = 0) -> Iterator[JsonObject]:
        return self._studio.watch(f"/jobs/{quote(job_id)}/events", cursor=cursor)


class TrialsAPI:
    """Hosted Trial and TrialExecution operations."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def get(self, trial_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/trials/{quote(trial_id)}"))

    def rerun(self, trial_id: str, *, idempotency_key: str) -> JsonObject:
        """Create a new one-Trial Job pinned to this Trial's Task, Agent, and settings."""
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/trials/{quote(trial_id)}/rerun",
                json={"idempotency_key": idempotency_key},
            ),
        )

    def transition(self, trial_id: str, status: str, **fields: Any) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST", f"/trials/{quote(trial_id)}/transition", json={"status": status, **fields}
            ),
        )

    def cancel(self, trial_id: str) -> JsonObject:
        return self.transition(trial_id, "cancelled")

    def create_execution(
        self,
        trial_id: str,
        *,
        idempotency_key: str,
        worker_id: str | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/trials/{quote(trial_id)}/executions",
                json={"idempotency_key": idempotency_key, "worker_id": worker_id},
            ),
        )

    def watch(self, trial_id: str, *, cursor: int = 0) -> Iterator[JsonObject]:
        return self._studio.watch(f"/trials/{quote(trial_id)}/events", cursor=cursor)


class ReviewsAPI:
    """Human review assignments and submissions."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, *, status: str | None = "awaiting_review") -> JsonList:
        return cast(
            JsonList,
            self._studio.request("GET", "/reviews", params={"status": status}),
        )

    def get(self, assignment_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/reviews/{assignment_id}"))

    def claim(self, assignment_id: str) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request("POST", f"/reviews/{assignment_id}/claim", json={}),
        )

    def assign(self, assignment_id: str, user_id: str) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/reviews/{assignment_id}/assign",
                json={"assigned_to_user_id": user_id},
            ),
        )

    def submit(
        self,
        assignment_id: str,
        *,
        scores: dict[str, float],
        idempotency_key: str,
        feedback: str = "",
        payload: JsonObject | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/reviews/{assignment_id}/submissions",
                json={
                    "scores": scores,
                    "idempotency_key": idempotency_key,
                    "feedback": feedback,
                    "payload": payload or {},
                },
            ),
        )


class Studio:
    """Hosted API client for one credential, account, and optional project.

    Args:
        api_root: API root ending in ``/api/v1``.
        token: A Plural API key or a signed-in access token.
        project: Project id sent as ``X-Project-Id``. Project-scoped API keys
            already carry their project.
        account: Account id sent as ``X-Account-Id`` to act for an
            organization. The server still applies the user's permissions.
        refresh: Called once after a 401 to obtain a fresh access token.
        http: HTTP client, injectable for tests.
    """

    def __init__(
        self,
        *,
        api_root: str,
        token: str | None,
        project: str | None = None,
        account: str | None = None,
        refresh: Callable[[], str | None] | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.api_root = api_root.rstrip("/")
        self.token = token
        self.project = project
        self.account = account
        self._refresh = refresh
        self._http = http
        self.projects = ProjectsAPI(self)
        self.accounts = AccountsAPI(self)
        self.packages = PackagesAPI(self)
        self.models = ModelsAPI(self)
        self.environments = EnvironmentsAPI(self)
        self.tasks = TasksAPI(self)
        self.verifiers = VerifiersAPI(self)
        self.agents = AgentsAPI(self)
        self.harnesses = HarnessesAPI(self)
        self.benchmarks = BenchmarksAPI(self)
        self.traces = TracesAPI(self)
        self.jobs = JobsAPI(self)
        self.trials = TrialsAPI(self)
        self.reviews = ReviewsAPI(self)

    @classmethod
    def for_client(cls, client: Client) -> Studio:
        """Hosted API for a gateway :class:`~plural.client.Client`."""
        return cls(
            api_root=studio_base_url(client.base_url),
            token=client.api_key,
            project=client.project,
        )

    def with_project(self, project: str | None) -> Studio:
        """The same credential and account, addressed to another project."""
        return Studio(
            api_root=self.api_root,
            token=self.token,
            project=project,
            account=self.account,
            refresh=self._refresh,
            http=self._http,
        )

    def _headers(self, *, project: bool = True) -> dict[str, str]:
        if not self.token:
            raise ConfigurationError(
                "Hosted calls need credentials. Run `plural auth login` or set PLURAL_API_KEY."
            )
        headers = {"Authorization": f"Bearer {self.token}", "User-Agent": "plural-sdk"}
        if self.account:
            headers["X-Account-Id"] = self.account
        if project and self.project:
            headers["X-Project-Id"] = self.project
        return headers

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: JsonObject | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        project: bool = True,
    ) -> httpx.Response:
        if json is not None and content is not None:
            raise InvalidRequestError("hosted request cannot contain JSON and raw content")
        for attempt in range(2):
            headers = self._headers(project=project)
            if content_type:
                headers["Content-Type"] = content_type
            url = f"{self.api_root}{path}"
            kwargs: dict[str, Any] = {
                "headers": headers,
                "json": json,
                "params": params,
                "content": content,
                "timeout": 60,
            }
            response = (
                self._http.request(method, url, **kwargs)
                if self._http is not None
                else httpx.request(method, url, **kwargs)
            )
            if response.status_code == 401 and attempt == 0 and self._refresh is not None:
                token = self._refresh()
                if token:
                    self.token = token
                    continue
            if response.status_code >= 400:
                _raise_http(response)
            return response
        raise AuthenticationError("hosted credentials were rejected", status_code=401)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: JsonObject | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        project: bool = True,
    ) -> Any:
        response = self._send(
            method,
            path,
            json=json,
            params=params,
            content=content,
            content_type=content_type,
            project=project,
        )
        if response.status_code == 204 or not response.content or method == "HEAD":
            return {}
        return response.json()

    def request_bytes(self, method: str, path: str) -> bytes:
        return self._send(method, path).content

    def watch(self, path: str, *, cursor: int = 0) -> Iterator[JsonObject]:
        headers = {**self._headers(), "Accept": "text/event-stream"}
        url = f"{self.api_root}{path}"
        stream = (
            self._http.stream("GET", url, headers=headers, params={"cursor": cursor}, timeout=None)
            if self._http is not None
            else httpx.stream("GET", url, headers=headers, params={"cursor": cursor}, timeout=None)
        )
        with stream as response:
            if response.status_code >= 400:
                response.read()
                _raise_http(response)
            event = ""
            for line in response.iter_lines():
                if not line:
                    event = ""
                elif line.startswith("event:"):
                    event = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    if event == "end":
                        # The stream is complete; the server closes it next.
                        return
                    value = json.loads(line.removeprefix("data:").strip())
                    if isinstance(value, dict):
                        yield value


def push_object(studio: Studio, obj: Any, **references: Any) -> JsonObject:
    """Push one revision of a public SDK object, or ingest one Trace.

    Graph edges are explicit hosted revision ids: a Task needs
    ``environment_revision_id`` and ``verifier_revision_ids``, an Agent with a
    custom Harness needs ``harness_revision_id``, and a Benchmark needs
    ``task_revision_ids``.
    """
    if isinstance(obj, Harness):
        obj = HarnessDefinition.from_package(obj._package())
    elif hasattr(obj, "definition") and callable(obj.definition) and not isinstance(obj, Task):
        obj = obj.definition()
    if isinstance(obj, EnvironmentDefinition):
        return studio.environments.push(obj, **references)
    if isinstance(obj, Task):
        return studio.tasks.push(obj, **references)
    if (
        isinstance(obj, (DeterministicVerifier, HumanVerifier))
        or getattr(obj, "kind", None) == "agent"
    ):
        return studio.verifiers.push(obj, **references)
    if isinstance(obj, Agent):
        return studio.agents.push(obj, **references)
    if isinstance(obj, HarnessDefinition):
        return studio.harnesses.push(obj, **references)
    if isinstance(obj, Benchmark):
        return studio.benchmarks.push(obj, **references)
    if isinstance(obj, Trace):
        return studio.traces.create(obj, **references)
    raise InvalidRequestError("unsupported SDK object")


__all__ = [
    "AccountsAPI",
    "AgentsAPI",
    "BenchmarksAPI",
    "EnvironmentsAPI",
    "HarnessesAPI",
    "JobsAPI",
    "ModelsAPI",
    "PackagesAPI",
    "ProjectsAPI",
    "ReviewsAPI",
    "Studio",
    "TasksAPI",
    "TracesAPI",
    "TrialsAPI",
    "VerifiersAPI",
    "push_object",
    "slugify",
    "studio_base_url",
]
