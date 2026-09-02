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
    ) -> RemoteAgent:
        """Create an agent.

        Args:
            name: Display name.
            model: Routed model id.
            description: Optional description.
            environment_id: Optional environment to bind.
            environment_revision_id: Optional pinned revision.

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
    ) -> JsonObject:
        """Create a benchmark.

        Args:
            name: Display name.
            notes: Optional notes.
            report: Optional scored report payload.
            environment_id: Optional environment to attach.
            environment_revision_id: Optional pinned revision.
            agent_id: Optional agent to attach.

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
                    "notes": notes,
                    "report": report or {},
                    "environment_id": environment_id,
                    "environment_revision_id": environment_revision_id,
                    "agent_id": agent_id,
                },
            ),
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
    ) -> JsonObject:
        """Ingest a trace.

        Args:
            trace: Trace payload.
            environment_id: Optional environment to attach.
            environment_revision_id: Optional pinned revision.
            agent_id: Optional agent to attach.
            run_group_id: Optional run grouping id.

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
                },
            ),
        )


class Studio:
    """Hosted studio client bound to a :class:`~plural.client.Client`."""

    def __init__(self, client: Client) -> None:
        self.client = client
        self.environments = EnvironmentsAPI(self)
        self.agents = AgentsAPI(self)
        self.benchmarks = BenchmarksAPI(self)
        self.traces = TracesAPI(self)

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
) -> JsonObject:
    """Store a benchmark report on the hosted project.

    Args:
        client: Authenticated Plural client.
        report: Local :class:`~plural.benchmarks.runner.Report`.
        name: Optional display name.
        notes: Optional notes.
        environment_id: Optional environment to attach.
        environment_revision_id: Optional pinned revision.
        agent_id: Optional agent to attach.

    Returns:
        Created benchmark detail.
    """
    payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report)
    env_name = payload.get("environment") or "benchmark"
    label = name or str(env_name)
    return Studio(client).benchmarks.create(
        name=label,
        notes=notes,
        report=payload,
        environment_id=environment_id,
        environment_revision_id=environment_revision_id,
        agent_id=agent_id,
    )


def _benchmark_kwargs(obj: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    from plural.benchmarks.runner import Benchmark

    if isinstance(obj, Benchmark):
        if obj.report is None:
            raise InvalidRequestError("run the benchmark before creating or updating it")
        kwargs.setdefault(
            "environment_id",
            getattr(obj.env, "remote_id", None) or getattr(obj.env, "name", None),
        )
        kwargs.setdefault("name", obj.env.name)
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
