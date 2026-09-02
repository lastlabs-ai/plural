"""Hosted studio resources: environments, agents, benchmarks, and traces.

Account API keys must pass ``project`` on :class:`~plural.client.Client`.
Project API keys already know the project.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

import httpx

from plural.errors import (
    AuthenticationError,
    ConfigurationError,
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

    def get(self, environment_id: str) -> JsonObject:
        """Fetch one environment.

        Args:
            environment_id: Hosted environment id.

        Returns:
            Environment detail.
        """
        return cast(JsonObject, self._studio.request("GET", f"/environments/{environment_id}"))

    def create(
        self,
        *,
        name: str,
        version: str = "0.1.0",
        description: str = "",
        instructions: str = "",
        tasks: JsonList | None = None,
    ) -> JsonObject:
        """Create an environment.

        Args:
            name: Display name.
            version: Starting version string.
            description: Optional description.
            instructions: System prompt / instructions.
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
                    "tasks": tasks or [],
                },
            ),
        )

    def update(self, environment_id: str, **fields: Any) -> JsonObject:
        """Patch an environment.

        Args:
            environment_id: Hosted environment id.
            **fields: Fields accepted by the studio PATCH route.

        Returns:
            Updated environment detail.
        """
        return cast(
            JsonObject,
            self._studio.request("PATCH", f"/environments/{environment_id}", json=fields),
        )

    def delete(self, environment_id: str) -> None:
        """Delete an environment.

        Args:
            environment_id: Hosted environment id.
        """
        self._studio.request("DELETE", f"/environments/{environment_id}")

    def push(
        self,
        env: Environment[Any, Any],
        *,
        environment_id: str | None = None,
        name: str | None = None,
        description: str = "",
    ) -> JsonObject:
        """Create or update ``env`` on the hosted project.

        Args:
            env: Local environment instance.
            environment_id: Existing remote id, if already known.
            name: Optional name override when creating.
            description: Optional description when creating.

        Returns:
            Created revision plus ``environment_id``.
        """
        return push_environment(
            self._studio.client,
            env,
            environment_id=environment_id,
            name=name,
            description=description,
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
        return self._studio.agents.invoke(self.id, prompt, **kwargs)


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

    def get(self, agent_id: str) -> RemoteAgent:
        """Fetch one agent.

        Args:
            agent_id: Hosted agent id.

        Returns:
            Agent handle.
        """
        return RemoteAgent(
            self._studio,
            cast(JsonObject, self._studio.request("GET", f"/agents/{agent_id}")),
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

    def update(self, agent_id: str, **fields: Any) -> RemoteAgent:
        """Patch an agent.

        Args:
            agent_id: Hosted agent id.
            **fields: Fields accepted by the studio PATCH route.

        Returns:
            Updated agent handle.
        """
        return RemoteAgent(
            self._studio,
            cast(JsonObject, self._studio.request("PATCH", f"/agents/{agent_id}", json=fields)),
        )

    def delete(self, agent_id: str) -> None:
        """Delete an agent.

        Args:
            agent_id: Hosted agent id.
        """
        self._studio.request("DELETE", f"/agents/{agent_id}")

    def invoke(
        self,
        agent_id: str,
        prompt: str | Sequence[Message | dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """Invoke an agent through the gateway.

        Args:
            agent_id: Hosted agent id.
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
            f"{client.base_url.rstrip('/')}/agents/{agent_id}/chat/completions",
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
            id=str(data.get("id") or agent_id),
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

    def get(self, benchmark_id: str) -> JsonObject:
        """Fetch one benchmark.

        Args:
            benchmark_id: Hosted benchmark id.

        Returns:
            Benchmark detail.
        """
        return cast(JsonObject, self._studio.request("GET", f"/benchmarks/{benchmark_id}"))

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

    def update(self, benchmark_id: str, **fields: Any) -> JsonObject:
        """Patch a benchmark.

        Args:
            benchmark_id: Hosted benchmark id.
            **fields: Fields accepted by the studio PATCH route.

        Returns:
            Updated benchmark detail.
        """
        return cast(
            JsonObject,
            self._studio.request("PATCH", f"/benchmarks/{benchmark_id}", json=fields),
        )

    def delete(self, benchmark_id: str) -> None:
        """Delete a benchmark.

        Args:
            benchmark_id: Hosted benchmark id.
        """
        self._studio.request("DELETE", f"/benchmarks/{benchmark_id}")


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
        Manifest with tools, scorers, skills, and hooks.
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
    scorers = [{"name": name, "weight": weight} for name, _fn, weight in env.scorers]
    return {"tools": tools, "scorers": scorers, "skills": [], "hooks": []}


def push_environment(
    client: Client,
    env: Environment[Any, Any],
    *,
    environment_id: str | None = None,
    name: str | None = None,
    description: str = "",
) -> JsonObject:
    """Create the environment if needed, then ingest a revision.

    Args:
        client: Authenticated Plural client.
        env: Local environment instance.
        environment_id: Existing remote id, if already known.
        name: Optional name override when creating.
        description: Optional description when creating.

    Returns:
        Created revision plus ``environment_id``.
    """
    studio = Studio(client)
    remote_id = environment_id or getattr(env, "remote_id", None)
    if not remote_id:
        created = studio.environments.create(
            name=name or env.name,
            version=env.version,
            description=description,
            instructions=env.system_prompt or "",
        )
        remote_id = created["id"]
        env.remote_id = remote_id
    from plural import __version__

    revision = studio.request(
        "POST",
        f"/environments/{remote_id}/revisions",
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
    env.remote_id = remote_id
    payload = revision if isinstance(revision, dict) else {}
    return {**payload, "environment_id": remote_id}


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
    env_version = payload.get("environment_version") or ""
    label = name or f"{env_name} {env_version}".strip()
    return Studio(client).benchmarks.create(
        name=label,
        notes=notes,
        report=payload,
        environment_id=environment_id,
        environment_revision_id=environment_revision_id,
        agent_id=agent_id,
    )


def push_object(client: Client, obj: Any, **kwargs: Any) -> JsonObject:
    """Dispatch ``client.push`` to the matching studio sync.

    Agents are not accepted. Create them with ``client.agents.create(...)``.

    Args:
        client: Authenticated Plural client.
        obj: Environment, Trace, Benchmark, or Report.
        **kwargs: Forwarded to the typed push helper.

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
        return push_report(client, obj, **kwargs)
    if isinstance(obj, Benchmark):
        if obj.report is None:
            raise InvalidRequestError("run the benchmark before pushing it")
        kwargs.setdefault("environment_id", getattr(obj.env, "remote_id", None))
        if not kwargs.get("name"):
            kwargs["name"] = f"{obj.env.name} {obj.env.version}".strip()
        return push_report(client, obj.report, **kwargs)
    raise InvalidRequestError(
        "client.push accepts Environment, Trace, Benchmark, or Report; "
        "create agents with client.agents.create(...)"
    )
