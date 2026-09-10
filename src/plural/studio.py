"""Canonical hosted schema-v2 parent, revision, Job, event, and review APIs."""

# Public method names map directly to HTTP operations; class-level API
# documentation carries the contract.
# ruff: noqa: D101, D102, DOC201

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from plural.errors import (
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PluralError,
)
from plural.foundation import (
    AgentDefinition,
    BenchmarkDefinition,
    DeterministicVerifier,
    EnvironmentManifest,
    HarnessPackage,
    HumanVerifier,
    JobSpec,
    TaskDefinition,
)
from plural.tracing.schema import Trace

if TYPE_CHECKING:
    from plural.client import Client
    from plural.foundation import VerifierDefinition

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
    }.get(response.status_code, PluralError)
    raise error_type(message, status_code=response.status_code)


def _dump(value: Any, *, exclude: set[str] | None = None) -> JsonObject:
    if not isinstance(value, BaseModel):
        raise InvalidRequestError("canonical SDK object must be a Pydantic model")
    payload = value.model_dump(mode="json", exclude_none=True, exclude=exclude or set())
    return payload


class RevisionResourceAPI(Generic[T]):
    """Common parent and immutable revision operations."""

    collection: str
    model_type: type[T]

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, **params: Any) -> JsonList:
        response = self._studio.request("GET", f"/{self.collection}", params=params)
        return cast(JsonList, response.get("items", response))

    def get(self, resource_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/{self.collection}/{resource_id}"))

    def create(
        self,
        *,
        name: str,
        slug: str | None = None,
        description: str = "",
    ) -> JsonObject:
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
            self._studio.request("PATCH", f"/{self.collection}/{resource_id}", json=fields),
        )

    def delete(self, resource_id: str) -> None:
        self._studio.request("DELETE", f"/{self.collection}/{resource_id}")

    def revisions(self, resource_id: str) -> JsonList:
        return cast(
            JsonList,
            self._studio.request("GET", f"/{self.collection}/{resource_id}/revisions"),
        )

    def revision(self, resource_id: str, revision_id: str) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "GET", f"/{self.collection}/{resource_id}/revisions/{revision_id}"
            ),
        )

    def _parent(self, value: T) -> JsonObject:
        slug = slugify(self._name(value), fallback=self.collection.rstrip("s"))
        try:
            return self.get(slug)
        except NotFoundError:
            return self.create(
                name=self._name(value),
                slug=slug,
                description=str(getattr(value, "description", "")),
            )

    @staticmethod
    def _name(value: T) -> str:
        name = getattr(value, "name", None) or getattr(value, "task_id", None)
        if not isinstance(name, str) or not name:
            raise InvalidRequestError("revision object has no parent name")
        return name

    def _publish_payload(self, value: T, **references: Any) -> JsonObject:
        del references
        return _dump(value, exclude={"name", "description"})

    def push(self, value: T, **references: Any) -> JsonObject:
        if not isinstance(value, self.model_type):
            raise InvalidRequestError(f"{self.collection} push requires {self.model_type.__name__}")
        parent = self._parent(value)
        resource_id = str(parent.get("id") or parent.get("slug"))
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/{self.collection}/{resource_id}/revisions",
                json=self._publish_payload(value, **references),
            ),
        )

    def publish_revision(self, resource_id: str, revision_id: str) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/{self.collection}/{resource_id}/revisions/{revision_id}/publish",
            ),
        )

    def publish(self, value: T, **references: Any) -> JsonObject:
        revision = self.push(value, **references)
        revision_id = revision.get("id")
        if not isinstance(revision_id, str) or not revision_id:
            raise InvalidRequestError("created revision response omitted id")
        parent = self._parent(value)
        resource_id = str(parent.get("id") or parent.get("slug"))
        return self.publish_revision(resource_id, revision_id)


class EnvironmentsAPI(RevisionResourceAPI[EnvironmentManifest]):
    collection = "environments"
    model_type = EnvironmentManifest

    def _publish_payload(self, value: EnvironmentManifest, **references: Any) -> JsonObject:
        del references
        return _dump(value, exclude={"name", "description"})


class TasksAPI(RevisionResourceAPI[TaskDefinition]):
    collection = "tasks"
    model_type = TaskDefinition

    def _publish_payload(self, value: TaskDefinition, **references: Any) -> JsonObject:
        environment_revision_id = references.get("environment_revision_id")
        verifier_revision_ids = references.get("verifier_revision_ids")
        if not isinstance(environment_revision_id, str) or not environment_revision_id:
            raise InvalidRequestError("Task publish requires environment_revision_id")
        if not isinstance(verifier_revision_ids, Sequence) or isinstance(
            verifier_revision_ids, (str, bytes)
        ):
            raise InvalidRequestError("Task publish requires verifier_revision_ids")
        ids = [str(item) for item in verifier_revision_ids]
        if len(ids) != len(value.verifiers):
            raise InvalidRequestError("verifier_revision_ids must align with Task verifiers")
        payload = _dump(
            value,
            exclude={"task_id", "environment", "verifiers"},
        )
        payload["environment_revision_id"] = environment_revision_id
        payload["verifiers"] = [
            {"verifier_revision_id": revision_id, "weight": weighted.weight}
            for revision_id, weighted in zip(ids, value.verifiers, strict=True)
        ]
        return payload


class VerifiersAPI(RevisionResourceAPI[Any]):
    collection = "verifiers"
    model_type = BaseModel

    def push(self, value: VerifierDefinition, **references: Any) -> JsonObject:
        if getattr(value, "kind", None) not in {"deterministic", "agent", "human"}:
            raise InvalidRequestError("Verifier push requires VerifierDefinition")
        return super().push(value, **references)

    def _publish_payload(self, value: Any, **references: Any) -> JsonObject:
        del references
        return _dump(value, exclude={"name"})


class AgentsAPI(RevisionResourceAPI[AgentDefinition]):
    """Hosted AgentDefinition parents and immutable revisions."""

    collection = "agents"
    model_type = AgentDefinition

    def _publish_payload(self, value: AgentDefinition, **references: Any) -> JsonObject:
        harness_revision_id = references.get("harness_revision_id")
        if value.harness is not None and not harness_revision_id:
            raise InvalidRequestError("Harness-bound Agent publish requires harness_revision_id")
        payload = _dump(value, exclude={"name", "harness", "harness_package"})
        payload["harness_revision_id"] = harness_revision_id
        return payload


class HarnessesAPI(RevisionResourceAPI[HarnessPackage]):
    collection = "harnesses"
    model_type = HarnessPackage

    @staticmethod
    def _name(value: HarnessPackage) -> str:
        return value.manifest.name

    def _publish_payload(self, value: HarnessPackage, **references: Any) -> JsonObject:
        del references
        return _dump(value)


class BenchmarksAPI(RevisionResourceAPI[BenchmarkDefinition]):
    collection = "benchmarks"
    model_type = BenchmarkDefinition

    def _publish_payload(self, value: BenchmarkDefinition, **references: Any) -> JsonObject:
        task_revision_ids = references.get("task_revision_ids")
        if not isinstance(task_revision_ids, Sequence) or isinstance(
            task_revision_ids, (str, bytes)
        ):
            raise InvalidRequestError("Benchmark publish requires task_revision_ids")
        ids = [str(item) for item in task_revision_ids]
        if len(ids) != len(value.tasks):
            raise InvalidRequestError("task_revision_ids must align with Benchmark tasks")
        payload = _dump(value, exclude={"name", "tasks"})
        payload["task_revision_ids"] = ids
        return payload


class TracesAPI:
    """Canonical Trace ingest, TITO upload, and reads."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, **params: Any) -> JsonList:
        response = self._studio.request("GET", "/traces", params=params)
        return cast(JsonList, response.get("items", response))

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
    """Hosted Job submission, transitions, and live events."""

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
    ) -> JsonObject:
        if len(agent_revision_ids) != len(spec.agents):
            raise InvalidRequestError("agent_revision_ids must align with Job agents")
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
                },
            ),
        )

    def list(self, **params: Any) -> JsonList:
        response = self._studio.request("GET", "/jobs", params=params)
        return cast(JsonList, response.get("items", response))

    def get(self, job_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/jobs/{job_id}"))

    def trials(self, job_id: str) -> JsonList:
        return cast(JsonList, self._studio.request("GET", f"/jobs/{job_id}/trials"))

    def transition(self, job_id: str, status: str, **fields: Any) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST", f"/jobs/{job_id}/transition", json={"status": status, **fields}
            ),
        )

    def cancel(self, job_id: str) -> JsonObject:
        return self.transition(job_id, "cancelled")

    def watch(self, job_id: str, *, cursor: int = 0) -> Iterator[JsonObject]:
        return self._studio.watch(f"/jobs/{job_id}/events", cursor=cursor)


class TrialsAPI:
    """Hosted Trial and TrialExecution operations."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def get(self, trial_id: str) -> JsonObject:
        return cast(JsonObject, self._studio.request("GET", f"/trials/{trial_id}"))

    def transition(self, trial_id: str, status: str, **fields: Any) -> JsonObject:
        return cast(
            JsonObject,
            self._studio.request(
                "POST", f"/trials/{trial_id}/transition", json={"status": status, **fields}
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
                f"/trials/{trial_id}/executions",
                json={"idempotency_key": idempotency_key, "worker_id": worker_id},
            ),
        )

    def watch(self, trial_id: str, *, cursor: int = 0) -> Iterator[JsonObject]:
        return self._studio.watch(f"/trials/{trial_id}/events", cursor=cursor)


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
    """Hosted client for canonical schema-v2 resources."""

    def __init__(self, client: Client) -> None:
        self.client = client
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

    def _headers(self) -> dict[str, str]:
        api_key = getattr(self.client, "api_key", None)
        if not api_key:
            raise ConfigurationError("hosted calls require api_key=... or PLURAL_API_KEY")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        project = getattr(self.client, "project", None)
        if project:
            headers["X-Project-Id"] = project
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: JsonObject | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> Any:
        if json is not None and content is not None:
            raise InvalidRequestError("hosted request cannot contain JSON and raw content")
        headers = self._headers()
        if content_type:
            headers["Content-Type"] = content_type
        response = httpx.request(
            method,
            f"{studio_base_url(self.client.base_url)}{path}",
            headers=headers,
            json=json,
            params=params,
            content=content,
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http(response)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def watch(self, path: str, *, cursor: int = 0) -> Iterator[JsonObject]:
        with httpx.stream(
            "GET",
            f"{studio_base_url(self.client.base_url)}{path}",
            headers={**self._headers(), "Accept": "text/event-stream"},
            params={"cursor": cursor},
            timeout=None,
        ) as response:
            if response.status_code >= 400:
                _raise_http(response)
            for line in response.iter_lines():
                if line.startswith("data:"):
                    value = json.loads(line.removeprefix("data:").strip())
                    if isinstance(value, dict):
                        yield value


def environment_manifest(environment: Any) -> JsonObject:
    """Serialize a Python Environment compiler or EnvironmentManifest."""
    value = environment.manifest() if hasattr(environment, "manifest") else environment
    if not isinstance(value, EnvironmentManifest):
        raise InvalidRequestError("environment must compile to EnvironmentManifest")
    return _dump(value)


def create_object(client: Client, obj: Any, **references: Any) -> JsonObject:
    """Publish one canonical revision or ingest one Trace."""
    studio = Studio(client)
    if hasattr(obj, "manifest") and callable(obj.manifest):
        obj = obj.manifest()
    if isinstance(obj, EnvironmentManifest):
        return studio.environments.push(obj)
    if isinstance(obj, TaskDefinition):
        return studio.tasks.push(obj, **references)
    if (
        isinstance(obj, (DeterministicVerifier, HumanVerifier))
        or getattr(obj, "kind", None) == "agent"
    ):
        return studio.verifiers.push(obj)
    if isinstance(obj, AgentDefinition):
        return studio.agents.push(obj, **references)
    if isinstance(obj, HarnessPackage):
        return studio.harnesses.push(obj)
    if isinstance(obj, BenchmarkDefinition):
        return studio.benchmarks.push(obj, **references)
    if isinstance(obj, Trace):
        return studio.traces.create(obj, **references)
    raise InvalidRequestError("unsupported canonical SDK object")


def update_object(client: Client, obj: Any, **references: Any) -> JsonObject:
    """Publish a new immutable revision; revisions are never patched."""
    return create_object(client, obj, **references)


def push_object(client: Client, obj: Any, **references: Any) -> JsonObject:
    """Publish a canonical revision; parent creation is idempotent by slug."""
    return create_object(client, obj, **references)


__all__ = [
    "AgentsAPI",
    "BenchmarksAPI",
    "EnvironmentsAPI",
    "HarnessesAPI",
    "JobsAPI",
    "ReviewsAPI",
    "Studio",
    "TasksAPI",
    "TracesAPI",
    "TrialsAPI",
    "VerifiersAPI",
    "create_object",
    "environment_manifest",
    "push_object",
    "slugify",
    "studio_base_url",
    "update_object",
]
