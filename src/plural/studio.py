"""Hosted studio resources: environments, agents, benchmarks, and traces.

Account API keys must pass ``project`` on :class:`~plural.client.Client`.
Project API keys already know the project.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

import httpx

from plural.errors import (
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PluralError,
)
from plural.types import ChatResponse, Choice, Message

if TYPE_CHECKING:
    from plural.client import Client
    from plural.environments.env import Environment

JsonObject = dict[str, Any]
JsonList = list[dict[str, Any]]


def slugify(name: str, *, fallback: str = "item") -> str:
    """Turn a display name into the hosted slug.

    Args:
        name: Human-readable name.
        fallback: Used when the name has no slug characters.

    Returns:
        A lowercase hyphenated slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:80] or fallback


def studio_base_url(gateway_base: str) -> str:
    """Map a gateway ``/v1`` URL to the studio ``/api/v1`` prefix.

    Args:
        gateway_base: Hosted gateway base, usually ending in ``/v1``.

    Returns:
        Studio API root such as ``https://host/api/v1``.
    """
    root = gateway_base.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root.rstrip('/')}/api/v1"


def _raise_http(response: httpx.Response) -> None:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("message") or "")
    except Exception:
        detail = response.text.strip()
    message = detail or response.reason_phrase or "request failed"
    if response.status_code in (401, 403):
        raise AuthenticationError(message, status_code=response.status_code)
    if response.status_code == 404:
        raise NotFoundError(message, status_code=response.status_code)
    if response.status_code == 409:
        raise ConflictError(message, status_code=response.status_code)
    if response.status_code == 400:
        raise InvalidRequestError(message, status_code=response.status_code)
    raise PluralError(message, status_code=response.status_code)


class EnvironmentsAPI:
    """Create, read, update, and push hosted environments."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self) -> JsonList:
        """List environments in the resolved project.

        Returns:
            Environment summaries.
        """
        items = self._studio.request("GET", "/environments").get("items", [])
        return cast(JsonList, items)

    def get(self, slug: str) -> JsonObject:
        """Fetch one environment.

        Args:
            slug: Project-unique slug, or the hosted id.

        Returns:
            Environment detail.
        """
        return cast(JsonObject, self._studio.request("GET", f"/environments/{slug}"))

    def create(
        self,
        *,
        name: str,
        version: str = "0.1.0",
        description: str = "",
        instructions: str = "",
        readme_md: str = "",
        tasks: JsonList | None = None,
    ) -> JsonObject:
        """Create an environment.

        Args:
            name: Display name.
            version: Starting version string.
            description: Optional description.
            instructions: System prompt / instructions.
            readme_md: Optional markdown overview.
            tasks: Optional initial tasks.

        Returns:
            Created environment detail.
        """
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/environments",
                json={
                    "name": name,
                    "version": version,
                    "description": description,
                    "instructions": instructions,
                    "readme_md": readme_md,
                    "tasks": tasks or [],
                },
            ),
        )

    def update(self, slug: str, **fields: Any) -> JsonObject:
        """Patch an environment.

        Args:
            slug: Project-unique slug, or the hosted id.
            **fields: Fields accepted by the studio PATCH route.

        Returns:
            Updated environment detail.
        """
        return cast(
            JsonObject,
            self._studio.request("PATCH", f"/environments/{slug}", json=fields),
        )

    def delete(self, slug: str) -> None:
        """Delete an environment.

        Args:
            slug: Project-unique slug, or the hosted id.
        """
        self._studio.request("DELETE", f"/environments/{slug}")

    def bind_harness(
        self,
        environment_id: str,
        revision_id: str,
        harness_revision_id: str,
        *,
        policy: dict[str, Any] | None = None,
    ) -> JsonObject:
        """Allow one exact hosted harness revision for an environment revision."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/environments/{environment_id}/revisions/{revision_id}/harnesses",
                json={
                    "harness_revision_id": harness_revision_id,
                    "policy": policy or {},
                },
            ),
        )

    def list_harnesses(self, environment_id: str, revision_id: str) -> JsonList:
        """List exact harness bindings for an environment revision."""  # noqa: DOC201
        return cast(
            JsonList,
            self._studio.request(
                "GET",
                f"/environments/{environment_id}/revisions/{revision_id}/harnesses",
            ),
        )

    def publish_manifest(self, manifest: Any) -> JsonObject:
        """Publish one exact v1 environment package revision."""  # noqa: DOC201
        from plural.domain import EnvironmentManifest

        package = (
            manifest
            if isinstance(manifest, EnvironmentManifest)
            else EnvironmentManifest.model_validate(manifest)
        )
        try:
            environment = self.get(slugify(package.name, fallback="environment"))
        except NotFoundError:
            environment = self.create(
                name=package.name,
                version=package.revision,
                description=package.description,
                instructions=package.instructions,
            )
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/environments/{environment['id']}/revisions",
                json={
                    "package_manifest": _exact_package_payload(package),
                    "source": "sdk_sync",
                },
            ),
        )


class HarnessesAPI:
    """Create packages and publish immutable hosted harness revisions."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self) -> JsonList:
        """List harness package definitions."""  # noqa: DOC201
        return cast(JsonList, self._studio.request("GET", "/harnesses").get("items", []))

    def get(self, ref: str) -> JsonObject:
        """Get a harness package by project-unique slug or id."""  # noqa: DOC201
        return cast(JsonObject, self._studio.request("GET", f"/harnesses/{ref}"))

    def create(
        self,
        *,
        name: str,
        description: str = "",
        slug: str | None = None,
    ) -> JsonObject:
        """Create a harness package definition."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/harnesses",
                json={"name": name, "description": description, "slug": slug},
            ),
        )

    def update(self, ref: str, **fields: Any) -> JsonObject:
        """Patch mutable harness package metadata."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request("PATCH", f"/harnesses/{ref}", json=fields),
        )

    def delete(self, ref: str) -> None:
        """Delete an unreferenced harness package."""
        self._studio.request("DELETE", f"/harnesses/{ref}")

    def revisions(self, ref: str) -> JsonList:
        """List immutable revisions for one harness package."""  # noqa: DOC201
        return cast(
            JsonList,
            self._studio.request("GET", f"/harnesses/{ref}/revisions"),
        )

    def create_revision(self, ref: str, package: Any) -> JsonObject:
        """Publish a validated v1 ``HarnessPackage`` revision without secrets."""  # noqa: DOC201
        from plural.domain import HarnessPackage

        validated = (
            package
            if isinstance(package, HarnessPackage)
            else HarnessPackage.model_validate(package)
        )
        source = validated.source.model_dump(mode="json")
        if source["kind"] == "local":
            source["uri"] = "local"
        source.pop("trusted", None)
        source.pop("unsafe_local", None)
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/harnesses/{ref}/revisions",
                json={
                    "manifest": validated.manifest.model_dump(mode="json"),
                    "source": source,
                },
            ),
        )

    def resolve_revision(self, *, name: str, digest: str) -> JsonObject:
        """Resolve one immutable hosted revision by package name and digest."""  # noqa: DOC201
        package = self.get(slugify(name, fallback="harness"))
        for revision in self.revisions(str(package["id"])):
            if revision.get("source_digest") == digest:
                return revision
        raise NotFoundError(
            f"hosted harness revision {name!r} with digest {digest!r} was not found"
        )


class RemoteAgent:
    """A hosted agent that can be invoked through the gateway."""

    def __init__(self, studio: Studio, payload: dict[str, Any]) -> None:
        self._studio = studio
        self.id = str(payload["id"])
        self.name = str(payload.get("name") or "")
        self.slug = str(payload.get("slug") or "")
        self.description = str(payload.get("description") or "")
        self.model = payload.get("model")
        self.environment_id = payload.get("environment_id")
        self.invoke_url = str(payload.get("invoke_url") or "")
        self.data = payload

    def invoke(
        self,
        prompt: str | Sequence[Message | dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """Call this agent.

        Args:
            prompt: User text or a full message list.
            **kwargs: Extra chat-completion fields.

        Returns:
            Gateway chat response.
        """
        return self._studio.agents.invoke(self.slug or self.id, prompt, **kwargs)


class AgentsAPI:
    """Create, read, update, and invoke hosted agents."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self) -> JsonList:
        """List agents in the resolved project.

        Returns:
            Agent summaries.
        """
        return cast(JsonList, self._studio.request("GET", "/agents").get("items", []))

    def get(self, slug: str) -> RemoteAgent:
        """Fetch one agent.

        Args:
            slug: Project-unique slug, or the hosted id.

        Returns:
            Agent handle.
        """
        return RemoteAgent(
            self._studio,
            cast(JsonObject, self._studio.request("GET", f"/agents/{slug}")),
        )

    def create(
        self,
        *,
        name: str,
        model: str,
        description: str = "",
        environment_id: str | None = None,
        environment_revision_id: str | None = None,
        harness_revision_id: str | None = None,
        routing: dict[str, Any] | None = None,
        package_spec: Any | None = None,
    ) -> RemoteAgent:
        """Create an agent.

        Args:
            name: Display name.
            model: Routed model id.
            description: Optional description.
            environment_id: Optional environment to bind.
            environment_revision_id: Optional pinned revision.
            harness_revision_id: Exact hosted harness revision.
            routing: Portable model routing configuration.
            package_spec: Exact v1 AgentSpec used for content identity.

        Returns:
            Created agent handle.
        """
        payload = self._studio.request(
            "POST",
            "/agents",
            json={
                "name": name,
                "model": model,
                "description": description,
                "environment_id": environment_id,
                "environment_revision_id": environment_revision_id,
                "harness_revision_id": harness_revision_id,
                "routing": routing or {},
                "package_spec": (
                    package_spec.model_dump(mode="json")
                    if package_spec is not None and hasattr(package_spec, "model_dump")
                    else package_spec
                ),
            },
        )
        return RemoteAgent(self._studio, cast(JsonObject, payload))

    def update(self, slug: str, **fields: Any) -> RemoteAgent:
        """Patch an agent.

        Args:
            slug: Project-unique slug, or the hosted id.
            **fields: Fields accepted by the studio PATCH route.

        Returns:
            Updated agent handle.
        """
        return RemoteAgent(
            self._studio,
            cast(JsonObject, self._studio.request("PATCH", f"/agents/{slug}", json=fields)),
        )

    def delete(self, slug: str) -> None:
        """Delete an agent.

        Args:
            slug: Project-unique slug, or the hosted id.
        """
        self._studio.request("DELETE", f"/agents/{slug}")

    def invoke(
        self,
        slug: str,
        prompt: str | Sequence[Message | dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """Invoke an agent through the gateway.

        Args:
            slug: Project-unique slug, or the hosted id.
            prompt: User text or a full message list.
            **kwargs: Extra chat-completion fields.

        Returns:
            Gateway chat response.
        """
        messages: Sequence[Message | dict[str, Any]] = (
            [Message(role="user", content=prompt)] if isinstance(prompt, str) else prompt
        )
        client = self._studio.client
        if not client.api_key:
            raise ConfigurationError("agent invoke requires api_key=... or PLURAL_API_KEY")
        serialized = [item.model_dump() if isinstance(item, Message) else item for item in messages]
        headers = {
            "Authorization": f"Bearer {client.api_key}",
            "Content-Type": "application/json",
        }
        project = getattr(client, "project", None)
        if project:
            headers["X-Project-Id"] = project
        response = httpx.post(
            f"{client.base_url.rstrip('/')}/agents/{slug}/chat/completions",
            headers=headers,
            json={
                "model": str(kwargs.pop("model", None) or "plural/agent"),
                "messages": serialized,
                **kwargs,
            },
            timeout=60.0,
        )
        if response.status_code >= 400:
            _raise_http(response)
        data = response.json()
        choices = []
        for row in data.get("choices") or []:
            message = row.get("message") or {}
            choices.append(
                Choice(
                    message=Message(
                        role=message.get("role") or "assistant",
                        content=message.get("content"),
                    )
                )
            )
        if not choices:
            choices = [Choice(message=Message(role="assistant", content=""))]
        return ChatResponse(
            id=str(data.get("id") or slug),
            model=str(data.get("model") or ""),
            choices=choices,
            raw=data,
        )


class BenchmarksAPI:
    """Create, read, and update hosted benchmark reports."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self) -> JsonList:
        """List benchmarks in the resolved project.

        Returns:
            Benchmark summaries.
        """
        return cast(JsonList, self._studio.request("GET", "/benchmarks").get("items", []))

    def get(self, slug: str) -> JsonObject:
        """Fetch one benchmark.

        Args:
            slug: Project-unique slug, or the hosted id.

        Returns:
            Benchmark detail.
        """
        return cast(JsonObject, self._studio.request("GET", f"/benchmarks/{slug}"))

    def create(
        self,
        *,
        name: str,
        notes: str = "",
        report: dict[str, Any] | None = None,
        environment_id: str | None = None,
        environment_revision_id: str | None = None,
        agent_id: str | None = None,
        description: str = "",
        methodology: str = "",
        primary_metric: str = "reward",
        slug: str | None = None,
    ) -> JsonObject:
        """Create a benchmark definition, optionally with a first run.

        Args:
            name: Display name.
            notes: Optional notes.
            report: Optional scored report payload.
            environment_id: Optional environment to attach.
            environment_revision_id: Optional pinned revision.
            agent_id: Optional agent to attach.
            description: What this eval measures.
            methodology: How the task set and metric were chosen.
            primary_metric: Ranking path such as ``reward`` or ``scores.solved``.
            slug: Optional project-unique slug.

        Returns:
            Created benchmark detail.
        """
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/benchmarks",
                json={
                    "name": name,
                    "slug": slug,
                    "notes": notes,
                    "description": description,
                    "methodology": methodology,
                    "primary_metric": primary_metric,
                    "report": report or {},
                    "environment_id": environment_id,
                    "environment_revision_id": environment_revision_id,
                    "agent_id": agent_id,
                },
            ),
        )

    def create_run(
        self,
        slug: str,
        *,
        report: dict[str, Any],
        notes: str = "",
        environment_id: str | None = None,
        environment_revision_id: str | None = None,
        agent_id: str | None = None,
    ) -> JsonObject:
        """Attach a scored run to an existing benchmark.

        Args:
            slug: Project-unique slug, or the hosted id.
            report: Scored report payload.
            notes: Optional run notes.
            environment_id: Optional environment to attach.
            environment_revision_id: Optional pinned revision.
            agent_id: Optional agent to attach.

        Returns:
            Updated benchmark detail including the new latest run.
        """
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/benchmarks/{slug}/runs",
                json={
                    "notes": notes,
                    "report": report,
                    "environment_id": environment_id,
                    "environment_revision_id": environment_revision_id,
                    "agent_id": agent_id,
                },
            ),
        )

    def list_runs(self, slug: str) -> JsonList:
        """List runs for one benchmark.

        Args:
            slug: Project-unique slug, or the hosted id.

        Returns:
            Run summaries.
        """
        return cast(
            JsonList,
            self._studio.request("GET", f"/benchmarks/{slug}/runs").get("items", []),
        )

    def update(self, slug: str, **fields: Any) -> JsonObject:
        """Patch a benchmark.

        Args:
            slug: Project-unique slug, or the hosted id.
            **fields: Fields accepted by the studio PATCH route.

        Returns:
            Updated benchmark detail.
        """
        return cast(
            JsonObject,
            self._studio.request("PATCH", f"/benchmarks/{slug}", json=fields),
        )

    def delete(self, slug: str) -> None:
        """Delete a benchmark.

        Args:
            slug: Project-unique slug, or the hosted id.
        """
        self._studio.request("DELETE", f"/benchmarks/{slug}")

    def revisions(self, ref: str) -> JsonList:
        """List immutable revisions for one benchmark definition."""  # noqa: DOC201
        return cast(
            JsonList,
            self._studio.request("GET", f"/benchmarks/{ref}/revisions"),
        )

    def create_revision(
        self,
        ref: str,
        *,
        environment_revision_id: str,
        task_ids: Sequence[str],
        primary_metric: str | None = None,
        description: str | None = None,
        methodology: str | None = None,
        package_definition: Any | None = None,
    ) -> JsonObject:
        """Create and promote an ordered benchmark revision."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/benchmarks/{ref}/revisions",
                json={
                    "environment_revision_id": environment_revision_id,
                    "task_ids": list(task_ids),
                    "primary_metric": primary_metric,
                    "description": description,
                    "methodology": methodology,
                    "package_definition": (
                        package_definition.model_dump(mode="json")
                        if package_definition is not None
                        and hasattr(package_definition, "model_dump")
                        else package_definition
                    ),
                },
            ),
        )

    def get_revision(self, ref: str, revision_id: str) -> JsonObject:
        """Get one immutable benchmark revision."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request("GET", f"/benchmarks/{ref}/revisions/{revision_id}"),
        )

    def promote_revision(self, ref: str, revision_id: str) -> JsonObject:
        """Promote a prior immutable benchmark revision."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request("POST", f"/benchmarks/{ref}/revisions/{revision_id}/promote"),
        )


class TracesAPI:
    """Ingest and read hosted traces."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def list(self, **params: Any) -> JsonList:
        """List traces in the resolved project.

        Args:
            **params: Optional list filters such as ``kind``.

        Returns:
            Trace summaries.
        """
        query = {key: value for key, value in params.items() if value is not None}
        return cast(JsonList, self._studio.request("GET", "/traces", params=query).get("items", []))

    def get(self, trace_id: str) -> JsonObject:
        """Fetch one trace.

        Args:
            trace_id: Hosted row id or trace id accepted by the API.

        Returns:
            Trace detail.
        """
        return cast(JsonObject, self._studio.request("GET", f"/traces/{trace_id}"))

    def create(
        self,
        trace: dict[str, Any],
        *,
        environment_id: str | None = None,
        environment_revision_id: str | None = None,
        agent_id: str | None = None,
        run_group_id: str | None = None,
        job_id: str | None = None,
        trial_id: str | None = None,
    ) -> JsonObject:
        """Ingest a trace.

        Args:
            trace: Trace payload.
            environment_id: Optional environment to attach.
            environment_revision_id: Optional pinned revision.
            agent_id: Optional agent to attach.
            run_group_id: Optional run grouping id.
            job_id: Optional evaluation job provenance.
            trial_id: Optional evaluation trial provenance.

        Returns:
            Stored trace detail.
        """
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/traces",
                json={
                    "trace": trace,
                    "environment_id": environment_id,
                    "environment_revision_id": environment_revision_id,
                    "agent_id": agent_id,
                    "run_group_id": run_group_id,
                    "job_id": job_id,
                    "trial_id": trial_id,
                },
            ),
        )


def _safe_sync_payload(value: Any) -> Any:
    """Drop credential-shaped fields and bound uploaded diagnostic strings."""  # noqa: DOC201
    sensitive = {
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "api_key",
        "access_token",
        "refresh_token",
    }
    if isinstance(value, dict):
        return {
            str(key): ("[redacted]" if str(key).lower() in sensitive else _safe_sync_payload(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_sync_payload(item) for item in value]
    if isinstance(value, str):
        return value[:20_000]
    return value


def _exact_package_payload(value: Any) -> Any:
    dumped = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    sensitive = {
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "api_key",
        "access_token",
        "refresh_token",
    }

    def reject_secret(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if str(key).lower() in sensitive and nested is not None and nested != "":
                    raise InvalidRequestError(
                        "exact package payload contains a credential-shaped field"
                    )
                reject_secret(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                reject_secret(nested)

    reject_secret(dumped)
    return dumped


class TrialsAPI:
    """Read and cancel hosted immutable trials."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    def get(self, trial_id: str) -> JsonObject:
        """Get a hosted trial and all append-only executions."""  # noqa: DOC201
        return cast(JsonObject, self._studio.request("GET", f"/trials/{trial_id}"))

    def cancel(self, trial_id: str) -> JsonObject:
        """Cancel a pending hosted trial record."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request("POST", f"/trials/{trial_id}/cancel"),
        )


class JobsAPI:
    """Register local execution, append receipts, and finalize reports."""

    def __init__(self, studio: Studio) -> None:
        self._studio = studio

    @staticmethod
    def _registration(
        *,
        benchmark_revision_id: str,
        agent_revision_ids: Sequence[str],
        n_attempts: int,
        idempotency_key: str,
        spec_hash: str | None = None,
        job_spec: Any,
    ) -> JsonObject:
        return {
            "benchmark_revision_id": benchmark_revision_id,
            "agent_revision_ids": list(agent_revision_ids),
            "n_attempts": n_attempts,
            "idempotency_key": idempotency_key,
            "spec_hash": spec_hash,
            "job_spec": _exact_package_payload(job_spec),
        }

    def preflight(
        self,
        *,
        benchmark_revision_id: str,
        agent_revision_ids: Sequence[str],
        n_attempts: int = 1,
        idempotency_key: str = "preflight",
        job_spec: Any,
    ) -> JsonObject:
        """Validate exact hosted compatibility without launching anything."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/jobs/preflight",
                json=self._registration(
                    benchmark_revision_id=benchmark_revision_id,
                    agent_revision_ids=agent_revision_ids,
                    n_attempts=n_attempts,
                    idempotency_key=idempotency_key,
                    job_spec=job_spec,
                ),
            ),
        )

    def create(
        self,
        *,
        benchmark_revision_id: str,
        agent_revision_ids: Sequence[str],
        idempotency_key: str,
        n_attempts: int = 1,
        spec_hash: str | None = None,
        job_spec: Any,
    ) -> JsonObject:
        """Idempotently register a client-orchestrated job."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                "/jobs",
                json=self._registration(
                    benchmark_revision_id=benchmark_revision_id,
                    agent_revision_ids=agent_revision_ids,
                    n_attempts=n_attempts,
                    idempotency_key=idempotency_key,
                    spec_hash=spec_hash,
                    job_spec=job_spec,
                ),
            ),
        )

    def list(self, **params: Any) -> JsonList:
        """List hosted jobs with optional status and pagination filters."""  # noqa: DOC201
        query = {key: value for key, value in params.items() if value is not None}
        return cast(
            JsonList,
            self._studio.request("GET", "/jobs", params=query).get("items", []),
        )

    def get(self, job_id: str) -> JsonObject:
        """Get one hosted job."""  # noqa: DOC201
        return cast(JsonObject, self._studio.request("GET", f"/jobs/{job_id}"))

    def trials(self, job_id: str) -> JsonList:
        """List deterministic hosted trial expansion order."""  # noqa: DOC201
        return cast(JsonList, self._studio.request("GET", f"/jobs/{job_id}/trials"))

    def batch(
        self,
        job_id: str,
        executions: Sequence[dict[str, Any]],
    ) -> JsonObject:
        """Idempotently append self-reported trial receipts."""  # noqa: DOC201
        payload = [_safe_sync_payload(item) for item in executions]
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/jobs/{job_id}/trials/batch",
                json={"executions": payload},
            ),
        )

    def upload_results(
        self,
        job_id: str,
        *,
        trial_keys: Sequence[str],
        results: Sequence[Any],
        batch_size: int = 50,
    ) -> int:
        """Upload complete local results in replay-safe chunks."""  # noqa: DOC201
        if len(trial_keys) != len(results):
            raise InvalidRequestError("hosted trial expansion does not match local results")
        uploaded = 0
        pending: list[dict[str, Any]] = []
        for trial_key, raw in zip(trial_keys, results, strict=True):
            dumped = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else dict(raw)
            receipt = dumped.get("receipt")
            if not isinstance(receipt, dict):
                raise InvalidRequestError("trial result is missing its receipt")
            pending.append(
                {
                    "trial_key": trial_key,
                    "result": dumped,
                    "verifier_metadata": {"verifier_hash": receipt.get("verifier_hash")}
                    if receipt.get("verifier_hash")
                    else {},
                }
            )
            if len(pending) >= batch_size:
                self.batch(job_id, pending)
                uploaded += len(pending)
                pending = []
        if pending:
            self.batch(job_id, pending)
            uploaded += len(pending)
        return uploaded

    def finalize(self, job_id: str, report: Any) -> JsonObject:
        """Idempotently link a final local report to one BenchmarkRun."""  # noqa: DOC201
        dumped = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report)
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/jobs/{job_id}/finalize",
                json={"report": _safe_sync_payload(dumped)},
            ),
        )

    def fail(self, job_id: str, *, error_code: str, error_message: str = "") -> JsonObject:
        """Mark a hosted job failed without implying hosted execution."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request(
                "POST",
                f"/jobs/{job_id}/fail",
                json={
                    "error_code": error_code,
                    "error_message": _safe_sync_payload(error_message),
                },
            ),
        )

    def cancel(self, job_id: str) -> JsonObject:
        """Cancel hosted records for a client-orchestrated job."""  # noqa: DOC201
        return cast(
            JsonObject,
            self._studio.request("POST", f"/jobs/{job_id}/cancel"),
        )


class Studio:
    """Hosted studio client bound to a :class:`~plural.client.Client`."""

    def __init__(self, client: Client) -> None:
        self.client = client
        self.environments = EnvironmentsAPI(self)
        self.harnesses = HarnessesAPI(self)
        self.agents = AgentsAPI(self)
        self.benchmarks = BenchmarksAPI(self)
        self.traces = TracesAPI(self)
        self.jobs = JobsAPI(self)
        self.trials = TrialsAPI(self)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send an authenticated studio request.

        Args:
            method: HTTP method.
            path: Path under ``/api/v1``.
            json: Optional JSON body.
            params: Optional query string.

        Returns:
            Parsed JSON, or ``None`` for an empty 204.
        """
        api_key = getattr(self.client, "api_key", None)
        if not api_key:
            raise ConfigurationError("studio calls require api_key=... or PLURAL_API_KEY")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        project = getattr(self.client, "project", None)
        if project:
            headers["X-Project-Id"] = project
        url = f"{studio_base_url(self.client.base_url)}{path}"
        response = httpx.request(
            method,
            url,
            headers=headers,
            json=json,
            params=params,
            timeout=30.0,
        )
        if response.status_code == 204:
            return None
        if response.status_code >= 400:
            _raise_http(response)
        if not response.content:
            return {}
        return response.json()


def environment_manifest(env: Environment[Any, Any]) -> JsonObject:
    """Build the hosted revision manifest from a local environment.

    Args:
        env: Local environment instance.

    Returns:
        Manifest with actions, schemas, guardrails, skills, and context.
    """
    tools = []
    for definition in env.tool_defs:
        dumped = definition.model_dump(mode="json")
        function = dumped.get("function") if isinstance(dumped, dict) else None
        if isinstance(function, dict):
            tools.append(
                {
                    "name": function.get("name"),
                    "description": function.get("description") or "",
                    "parameters": function.get("parameters") or {},
                }
            )
    observation_type, state_type = env._contract_names()
    scorers = [
        {
            "name": name,
            "weight": weight,
            "description": (getattr(fn, "__doc__", None) or "").strip(),
        }
        for name, fn, weight in env.scorers
    ]
    return {
        "tools": tools,
        "scorers": scorers,
        "skills": env.normalized_skills(),
        "hooks": env.overridden_hooks(),
        "observation_type": observation_type,
        "state_type": state_type,
        "observation_schema": env.observation_schema(),
        "state_schema": env.state_schema(),
        "guardrails": env.normalized_guardrails(),
        "context": env.context_policy(),
    }


def _environment_ref(
    env: Environment[Any, Any],
    *,
    environment_id: str | None = None,
    name: str | None = None,
) -> str:
    return environment_id or slugify(name or env.name, fallback="environment")


def _ingest_environment_revision(
    studio: Studio,
    env: Environment[Any, Any],
    ref: str,
) -> JsonObject:
    from plural import __version__

    revision = studio.request(
        "POST",
        f"/environments/{ref}/revisions",
        json={
            "version": env.version,
            "instructions": env.system_prompt or "",
            "fingerprint": env.fingerprint(),
            "plural_package_version": __version__,
            "max_turns": env.max_turns,
            "manifest": environment_manifest(env),
            "source": "sdk_sync",
        },
    )
    payload = revision if isinstance(revision, dict) else {}
    return payload


def create_environment(
    client: Client,
    env: Environment[Any, Any],
    *,
    name: str | None = None,
    description: str | None = None,
    readme: str | None = None,
) -> JsonObject:
    """Create a hosted environment from ``env``. Fails if the slug exists.

    Args:
        client: Authenticated Plural client.
        env: Local environment instance.
        name: Optional name override.
        description: Optional description override.
        readme: Optional markdown overview override.

    Returns:
        Created revision plus ``environment_id`` and ``slug``.
    """
    studio = Studio(client)
    label = name or env.name
    created = studio.environments.create(
        name=label,
        version=env.version,
        description=env.description if description is None else description,
        instructions=env.system_prompt or "",
        readme_md=env.readme if readme is None else readme,
    )
    ref = str(created.get("slug") or created["id"])
    env.remote_id = created["id"]
    payload = _ingest_environment_revision(studio, env, ref)
    return {**payload, "environment_id": created["id"], "slug": ref}


def update_environment(
    client: Client,
    env: Environment[Any, Any],
    *,
    environment_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    readme: str | None = None,
) -> JsonObject:
    """Update a hosted environment found by slug or id.

    Args:
        client: Authenticated Plural client.
        env: Local environment instance.
        environment_id: Optional slug or id override.
        name: Optional display-name patch.
        description: Optional description override.
        readme: Optional markdown overview override.

    Returns:
        Created revision plus ``environment_id`` and ``slug``.
    """
    studio = Studio(client)
    ref = _environment_ref(env, environment_id=environment_id, name=name)
    existing = studio.environments.get(ref)
    env.remote_id = existing["id"]
    fields: dict[str, Any] = {
        "description": env.description if description is None else description,
        "readme_md": env.readme if readme is None else readme,
    }
    if name is not None:
        fields["name"] = name
    studio.environments.update(ref, **fields)
    payload = _ingest_environment_revision(studio, env, ref)
    return {
        **payload,
        "environment_id": existing["id"],
        "slug": existing.get("slug") or ref,
    }


def push_environment(
    client: Client,
    env: Environment[Any, Any],
    *,
    environment_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    readme: str | None = None,
) -> JsonObject:
    """Create or update ``env`` using its slug.

    Prefer :func:`create_environment` or :func:`update_environment` when the
    intent is explicit. This helper updates the existing slug or creates it.

    Args:
        client: Authenticated Plural client.
        env: Local environment instance.
        environment_id: Optional slug or id override.
        name: Optional name override when creating.
        description: Optional description when creating.
        readme: Optional markdown overview when creating.

    Returns:
        Created revision plus ``environment_id`` and ``slug``.
    """
    studio = Studio(client)
    ref = _environment_ref(env, environment_id=environment_id, name=name)
    try:
        existing = studio.environments.get(ref)
    except NotFoundError:
        return create_environment(client, env, name=name, description=description, readme=readme)
    env.remote_id = existing["id"]
    return update_environment(
        client,
        env,
        environment_id=ref,
        name=name,
        description=description,
        readme=readme,
    )


def push_trace(
    client: Client,
    trace: Any,
    *,
    environment_id: str | None = None,
    environment_revision_id: str | None = None,
    agent_id: str | None = None,
    run_group_id: str | None = None,
) -> JsonObject:
    """Ingest a local trace on the hosted project.

    Args:
        client: Authenticated Plural client.
        trace: Local :class:`~plural.tracing.schema.Trace`.
        environment_id: Optional environment to attach.
        environment_revision_id: Optional pinned revision.
        agent_id: Optional agent to attach.
        run_group_id: Optional run grouping id.

    Returns:
        Stored trace detail.
    """
    payload = trace.model_dump(mode="json") if hasattr(trace, "model_dump") else dict(trace)
    return Studio(client).traces.create(
        payload,
        environment_id=environment_id,
        environment_revision_id=environment_revision_id,
        agent_id=agent_id,
        run_group_id=run_group_id,
    )


def push_report(
    client: Client,
    report: Any,
    *,
    name: str | None = None,
    notes: str = "",
    environment_id: str | None = None,
    environment_revision_id: str | None = None,
    agent_id: str | None = None,
    description: str = "",
    methodology: str = "",
    primary_metric: str | None = None,
    traces: list[Any] | None = None,
) -> JsonObject:
    """Store a benchmark report on the hosted project.

    Creates the definition on first push and appends a run afterwards.
    Case traces are uploaded with ``run_group_id`` set to the run id.

    Args:
        client: Authenticated Plural client.
        report: Local :class:`~plural.benchmarks.runner.Report`.
        name: Optional display name.
        notes: Optional notes.
        environment_id: Optional environment to attach.
        environment_revision_id: Optional pinned revision.
        agent_id: Optional agent to attach.
        description: What this eval measures.
        methodology: How the task set and metric were chosen.
        primary_metric: Ranking path such as ``reward`` or ``scores.solved``.
        traces: Optional episode traces to upload with the run.

    Returns:
        Created or updated benchmark detail.
    """
    from plural.errors import NotFoundError

    payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report)
    env_name = payload.get("environment") or "benchmark"
    label = name or str(payload.get("name") or env_name)
    metric = (
        primary_metric
        or payload.get("primary_metric")
        or (payload.get("manifest") or {}).get("primary_metric")
        or "reward"
    )
    studio = Studio(client)
    slug = slugify(label, fallback="benchmark")
    try:
        studio.benchmarks.get(slug)
        created = studio.benchmarks.create_run(
            slug,
            notes=notes,
            report=payload,
            environment_id=environment_id,
            environment_revision_id=environment_revision_id,
            agent_id=agent_id,
        )
    except NotFoundError:
        created = studio.benchmarks.create(
            name=label,
            notes=notes,
            description=description or str(payload.get("description") or ""),
            methodology=methodology,
            primary_metric=str(metric),
            report=payload,
            environment_id=environment_id,
            environment_revision_id=environment_revision_id,
            agent_id=agent_id,
        )
    run_group = ""
    latest = created.get("latest_run") if isinstance(created, dict) else None
    if isinstance(latest, dict):
        run_group = str(latest.get("run_group_id") or latest.get("id") or "")
    if not run_group:
        raw_manifest = payload.get("manifest")
        manifest = raw_manifest if isinstance(raw_manifest, dict) else {}
        run_group = str(manifest.get("run_id") or "")
    for trace in traces or []:
        try:
            push_trace(
                client,
                trace,
                environment_id=environment_id,
                environment_revision_id=environment_revision_id,
                agent_id=agent_id,
                run_group_id=run_group or None,
            )
        except Exception:  # noqa: BLE001
            continue
    return created


def _benchmark_kwargs(obj: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    from plural.benchmarks.runner import Benchmark

    if isinstance(obj, Benchmark):
        if obj.report is None:
            raise InvalidRequestError("run the benchmark before creating or updating it")
        kwargs.setdefault(
            "environment_id",
            getattr(obj.env, "remote_id", None) or getattr(obj.env, "name", None),
        )
        kwargs.setdefault("name", obj.name or obj.env.name)
        kwargs.setdefault("description", obj.description)
        kwargs.setdefault("primary_metric", obj.primary_metric)
        kwargs.setdefault("traces", list(obj._traces))
        return kwargs
    return kwargs


def _report_slug(report: Any, *, name: str | None = None) -> str:
    payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report)
    return slugify(name or str(payload.get("environment") or "benchmark"), fallback="benchmark")


def create_object(client: Client, obj: Any, **kwargs: Any) -> JsonObject:
    """Create a hosted environment, trace, or benchmark.

    Agents are created with ``client.agents.create(...)``.

    Args:
        client: Authenticated Plural client.
        obj: Environment, Trace, Benchmark, or Report.
        **kwargs: Forwarded to the typed helper.

    Returns:
        Hosted record created by the studio API.
    """
    from plural.benchmarks.runner import Benchmark, Report
    from plural.environments.env import Environment
    from plural.tracing.schema import Trace

    if isinstance(obj, Environment):
        return create_environment(client, obj, **kwargs)
    if isinstance(obj, Trace):
        return push_trace(client, obj, **kwargs)
    if isinstance(obj, Report):
        return push_report(client, obj, **kwargs)
    if isinstance(obj, Benchmark):
        return push_report(client, obj.report, **_benchmark_kwargs(obj, kwargs))
    raise InvalidRequestError(
        "client.create accepts Environment, Trace, Benchmark, or Report; "
        "create agents with client.agents.create(...)"
    )


def update_object(client: Client, obj: Any, **kwargs: Any) -> JsonObject:
    """Update a hosted environment or benchmark by slug. Traces update by id.

    Args:
        client: Authenticated Plural client.
        obj: Environment, Trace, Benchmark, or Report.
        **kwargs: Forwarded to the typed helper.

    Returns:
        Hosted record updated by the studio API.
    """
    from plural.benchmarks.runner import Benchmark, Report
    from plural.environments.env import Environment
    from plural.tracing.schema import Trace

    if isinstance(obj, Environment):
        return update_environment(client, obj, **kwargs)
    if isinstance(obj, Trace):
        return push_trace(client, obj, **kwargs)
    if isinstance(obj, (Report, Benchmark)):
        report = obj.report if isinstance(obj, Benchmark) else obj
        if report is None:
            raise InvalidRequestError("run the benchmark before updating it")
        if isinstance(obj, Benchmark):
            fields = _benchmark_kwargs(obj, dict(kwargs))
        else:
            fields = dict(kwargs)
        slug = fields.pop("slug", None) or _report_slug(report, name=fields.get("name"))
        dumped = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report)
        body = {
            "notes": fields.get("notes", ""),
            "report": dumped,
        }
        if fields.get("name"):
            body["name"] = fields["name"]
        if fields.get("environment_id"):
            body["environment_id"] = fields["environment_id"]
        if fields.get("agent_id"):
            body["agent_id"] = fields["agent_id"]
        return Studio(client).benchmarks.update(slug, **body)
    raise InvalidRequestError(
        "client.update accepts Environment, Trace, Benchmark, or Report; "
        "update agents with client.agents.update(...)"
    )


def push_object(client: Client, obj: Any, **kwargs: Any) -> JsonObject:
    """Create or update a hosted environment, trace, or benchmark.

    Prefer :func:`create_object` or :func:`update_object` when the intent is
    explicit. Agents are not accepted.

    Args:
        client: Authenticated Plural client.
        obj: Environment, Trace, Benchmark, or Report.
        **kwargs: Forwarded to the typed helper.

    Returns:
        Hosted record created or updated by the studio API.
    """
    from plural.benchmarks.runner import Benchmark, Report
    from plural.environments.env import Environment
    from plural.tracing.schema import Trace

    if isinstance(obj, Environment):
        return push_environment(client, obj, **kwargs)
    if isinstance(obj, Trace):
        return push_trace(client, obj, **kwargs)
    if isinstance(obj, Report):
        slug = kwargs.get("slug") or _report_slug(obj, name=kwargs.get("name"))
        try:
            Studio(client).benchmarks.get(slug)
        except NotFoundError:
            return push_report(client, obj, **kwargs)
        return update_object(client, obj, **kwargs)
    if isinstance(obj, Benchmark):
        fields = _benchmark_kwargs(obj, dict(kwargs))
        slug = fields.get("slug") or slugify(
            fields.get("name") or obj.env.name, fallback="benchmark"
        )
        try:
            Studio(client).benchmarks.get(slug)
        except NotFoundError:
            return push_report(client, obj.report, **fields)
        return update_object(client, obj, **fields)
    raise InvalidRequestError(
        "client.push accepts Environment, Trace, Benchmark, or Report; "
        "create agents with client.agents.create(...)"
    )
