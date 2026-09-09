"""High-level plural client.

``Client(api_key=...)`` talks to the hosted gateway. ``Client(providers={...})``
calls providers directly with your own keys. Same request types and same traces.

Examples:
    >>> from plural.client import Client
    >>> Client.__name__
    'Client'
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from plural.catalog.models import ModelCatalog
from plural.config import DEFAULT_SETTINGS
from plural.errors import ConfigurationError
from plural.providers.anthropic import AnthropicProvider
from plural.providers.azure import AzureOpenAIProvider
from plural.providers.base import Provider, map_transport_error
from plural.providers.bedrock import BedrockProvider
from plural.providers.google import GoogleProvider
from plural.providers.openai_compatible import (
    BasetenProvider,
    DeepSeekProvider,
    FireworksProvider,
    GroqProvider,
    MetaProvider,
    MistralProvider,
    MoonshotProvider,
    OpenAICompatible,
    OpenAIProvider,
    QwenProvider,
    TogetherProvider,
    XAIProvider,
    ZhipuProvider,
)
from plural.routing.policies import RoutingPolicy
from plural.routing.router import AttemptRecord, Router
from plural.tracing.redaction import Redactor, Sampler
from plural.tracing.schema import Attempt, Trace, TraceContext, new_trace_id
from plural.tracing.sinks import JSONLSink, Sink
from plural.tracing.writer import TraceWriter
from plural.types import ChatRequest, ChatResponse, Message, StreamChunk, Tool

_PROVIDER_CTORS: dict[str, type] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "groq": GroqProvider,
    "together": TogetherProvider,
    "fireworks": FireworksProvider,
    "baseten": BasetenProvider,
    "xai": XAIProvider,
    "deepseek": DeepSeekProvider,
    "mistral": MistralProvider,
    "meta": MetaProvider,
    "moonshot": MoonshotProvider,
    "qwen": QwenProvider,
    "zhipu": ZhipuProvider,
}

PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "baseten": "BASETEN_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "meta": "META_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "zhipu": "ZAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "bedrock": "AWS_BEARER_TOKEN_BEDROCK",
}


def _json_env(name: str) -> dict[str, str]:
    """Read a JSON object from the environment.

    Args:
        name: Environment variable holding a JSON object.

    Returns:
        The decoded mapping, empty when unset or malformed.
    """
    raw = os.environ.get(name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def build_azure(api_key: str) -> Provider:
    """Construct an Azure provider from environment configuration.

    Deployment names are chosen by whoever provisions the resource, so they cannot
    be derived from a model id and must be supplied.

    Args:
        api_key: Azure API key.

    Returns:
        A configured Azure provider.
    """
    return AzureOpenAIProvider(
        api_key,
        endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        deployments=_json_env("AZURE_OPENAI_DEPLOYMENTS"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION") or None,
        region=os.environ.get("AZURE_OPENAI_REGION") or "us",
    )


def build_bedrock(api_key: str | None) -> Provider:
    """Construct a Bedrock provider from environment configuration.

    Args:
        api_key: Bedrock API key, or ``None`` to sign with IAM credentials.

    Returns:
        A configured Bedrock provider.
    """
    return BedrockProvider(
        api_key,
        region=(
            os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        ),
        models=_json_env("BEDROCK_MODEL_IDS"),
        access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        session_token=os.environ.get("AWS_SESSION_TOKEN"),
    )


_PROVIDER_BUILDERS: dict[str, Any] = {
    "azure": build_azure,
    "bedrock": build_bedrock,
}


def build_provider(slug: str, api_key: str) -> Provider:
    """Build a provider adapter from a slug and key.

    Args:
        slug: Provider slug.
        api_key: Provider API key.

    Returns:
        A configured provider.

    Raises:
        ConfigurationError: If the slug has no adapter.
    """
    builder = _PROVIDER_BUILDERS.get(slug)
    if builder is not None:
        provider: Provider = builder(api_key)
        return provider
    ctor = _PROVIDER_CTORS.get(slug)
    if ctor is None:
        raise ConfigurationError(f"no adapter for provider '{slug}'", provider=slug)
    built: Provider = ctor(api_key)
    return built


class Client:
    """Unified client for routing, tracing, and (via other modules) environments.

    Args:
        api_key: Hosted plural gateway API key. Mutually exclusive with building
            providers solely from ``providers`` / env vars when you want direct mode.
        providers: Mapping of provider slug to API key string or Provider instance.
        base_url: Gateway base URL when using ``api_key``.
        catalog: Optional model catalog.
        policy: Optional routing policy.
        sink: Trace sink. Defaults to ``.plural/traces.jsonl``.
        redactor: Optional redactor applied before persistence.
        sampler: Optional sampler.
        capture_content: Whether to keep full prompt/response content in traces.
        max_retries: Retries per route.
        max_cost_usd: Optional per-request budget.
        default_headers: Extra headers for the gateway client.
        tags: Default tags applied to every trace.
        project: Project id required when ``api_key`` is account-scoped.
            Project-scoped keys already know the project. Also reads
            ``PLURAL_PROJECT``.

    Examples:
        Hosted gateway (reads ``PLURAL_API_KEY``)::

            client = Client()

        Bring-your-own upstream keys::

            client = Client(providers={"openai": "sk-..."})

        Account key (project required)::

            client = Client(api_key="plural_...", project="<project_id>")
            env = Environment(name="refund-support", version="0.1.0")
            client.create(env)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        providers: Mapping[str, str | Provider] | None = None,
        base_url: str | None = None,
        catalog: ModelCatalog | None = None,
        policy: RoutingPolicy | None = None,
        sink: Sink | None = None,
        redactor: Redactor | None = None,
        sampler: Sampler | None = None,
        capture_content: bool | None = None,
        max_retries: int = 2,
        max_cost_usd: float | None = None,
        default_headers: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
        trace_dir: str | Path | None = None,
        project: str | None = None,
    ) -> None:
        self.catalog = catalog or ModelCatalog()
        self.tags = tags or {}
        self.project = project or os.environ.get("PLURAL_PROJECT")
        self.capture_content = (
            DEFAULT_SETTINGS.capture_content if capture_content is None else capture_content
        )
        if api_key is None and providers is None:
            api_key = os.environ.get("PLURAL_API_KEY") or os.environ.get("ENROUTE_API_KEY")
        provider_map = self._build_providers(
            api_key=api_key,
            providers=providers,
            base_url=base_url,
            default_headers=default_headers,
        )
        if not provider_map:
            raise ConfigurationError(
                "no providers configured; pass api_key=... / PLURAL_API_KEY or providers={...}"
            )
        self._providers = provider_map
        self.api_key = api_key
        self.base_url = base_url or DEFAULT_SETTINGS.gateway_base_url
        from plural.studio import Studio

        self.studio = Studio(self)
        self.environments = self.studio.environments
        self.harnesses = self.studio.harnesses
        self.agents = self.studio.agents
        self.benchmarks = self.studio.benchmarks
        self.traces = self.studio.traces
        self.jobs = self.studio.jobs
        self.trials = self.studio.trials
        self.router = Router(
            provider_map,
            catalog=self.catalog,
            policy=policy,
            max_retries=max_retries,
            max_cost_usd=max_cost_usd,
        )
        if sink is None:
            directory = Path(trace_dir) if trace_dir else DEFAULT_SETTINGS.trace_dir
            sink = JSONLSink(directory / "traces.jsonl")
        if redactor is None and not self.capture_content:
            redactor = Redactor(drop_content=True)
        self.writer = TraceWriter(sink, redactor=redactor, sampler=sampler)

    def is_authenticated(self) -> bool:
        """Return whether configured credentials are accepted.

        Sends a lightweight authenticated request to each HTTP provider.
        In-process providers (no HTTP client) are treated as authenticated.

        Returns:
            ``True`` when every provider accepts the credentials or has no
            HTTP client to probe.

        Raises:
            TimeoutError: If a provider cannot be reached.
            PluralError: If a transport error occurs while probing.
        """
        return all(_provider_is_authenticated(provider) for provider in self._providers.values())

    def create(self, obj: Any, **kwargs: Any) -> dict[str, Any]:
        """Create a hosted environment, trace, or benchmark.

        Environments, agents, and benchmarks are addressed by project-unique
        slug. Creating a duplicate slug raises
        :class:`~plural.errors.ConflictError`. Traces are stored by
        ``trace_id``. Agents are created with :meth:`Client.agents.create`.

        Args:
            obj: An :class:`~plural.environments.env.Environment`,
                :class:`~plural.tracing.schema.Trace`,
                :class:`~plural.benchmarks.runner.Benchmark` (after ``run()``),
                or :class:`~plural.benchmarks.runner.Report`.
            **kwargs: Optional labels such as ``name``, ``notes``, or
                ``environment_id`` (slug or id).

        Returns:
            The hosted record created by the studio API.
        """
        from plural.studio import create_object

        return create_object(self, obj, **kwargs)

    def update(self, obj: Any, **kwargs: Any) -> dict[str, Any]:
        """Update a hosted environment or benchmark by slug.

        Traces update by ``trace_id``. Agents use :meth:`Client.agents.update`.

        Args:
            obj: An :class:`~plural.environments.env.Environment`,
                :class:`~plural.tracing.schema.Trace`,
                :class:`~plural.benchmarks.runner.Benchmark` (after ``run()``),
                or :class:`~plural.benchmarks.runner.Report`.
            **kwargs: Optional labels such as ``name``, ``notes``, or
                ``environment_id`` (slug or id).

        Returns:
            The hosted record updated by the studio API.
        """
        from plural.studio import update_object

        return update_object(self, obj, **kwargs)

    def push(self, obj: Any, **kwargs: Any) -> dict[str, Any]:
        """Create or update a local environment, trace, or benchmark.

        Prefer :meth:`create` or :meth:`update` when the intent is explicit.
        ``env.push(client)`` remains as an alias for this upsert.

        Args:
            obj: An :class:`~plural.environments.env.Environment`,
                :class:`~plural.tracing.schema.Trace`,
                :class:`~plural.benchmarks.runner.Benchmark` (after ``run()``),
                or :class:`~plural.benchmarks.runner.Report`.
            **kwargs: Optional labels such as ``name``, ``notes``, or
                ``environment_id`` (slug or id).

        Returns:
            The hosted record created or updated by the studio API.
        """
        from plural.studio import push_object

        return push_object(self, obj, **kwargs)

    def _build_providers(
        self,
        *,
        api_key: str | None,
        providers: Mapping[str, str | Provider] | None,
        base_url: str | None,
        default_headers: dict[str, str] | None,
    ) -> dict[str, Provider]:
        result: dict[str, Provider] = {}
        if api_key:
            result["plural"] = OpenAICompatible(
                api_key=api_key,
                base_url=base_url or DEFAULT_SETTINGS.gateway_base_url,
                name="plural",
                default_headers=default_headers,
                strip_model_prefix=False,
            )
        if providers:
            for name, value in providers.items():
                if not isinstance(value, str):
                    result[name] = value
                elif name not in _PROVIDER_CTORS and name not in _PROVIDER_BUILDERS:
                    if not base_url:
                        # Defaulting to the gateway URL here would send the key to
                        # the wrong host under a name that looks like a real vendor.
                        raise ConfigurationError(
                            f"no adapter for provider '{name}'; pass base_url to "
                            "treat it as an OpenAI-compatible endpoint",
                            provider=name,
                        )
                    result[name] = OpenAICompatible(api_key=value, base_url=base_url, name=name)
                else:
                    result[name] = build_provider(name, value)
        if not providers and not api_key:
            for slug, env_name in PROVIDER_ENV_KEYS.items():
                key = os.environ.get(env_name)
                if key:
                    result[slug] = build_provider(slug, key)
            # Bedrock also works from ambient IAM credentials with no key at all.
            if "bedrock" not in result and os.environ.get("AWS_ACCESS_KEY_ID"):
                result["bedrock"] = build_bedrock(None)
        return result

    def chat(
        self,
        *,
        model: str,
        messages: Sequence[Message | dict[str, Any]],
        models: list[str] | None = None,
        tools: Sequence[Tool | dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
        write_trace: bool = True,
        trace_context: TraceContext | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Create a chat completion.

        Args:
            model: Primary model id (``author/slug``).
            messages: Conversation messages.
            models: Optional fallback model chain.
            tools: Optional tools.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            metadata: Request metadata stored on the trace.
            tags: Extra trace tags.
            write_trace: Whether to persist this model-call trace.
            trace_context: Optional parent and episode lineage.
            **kwargs: Additional :class:`~plural.types.ChatRequest` fields.

        Returns:
            Normalized :class:`~plural.types.ChatResponse`.
        """
        request = self._make_request(
            model=model,
            messages=messages,
            models=models,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
            **kwargs,
        )
        trace = self._call_trace(request, tags=tags, trace_context=trace_context)
        try:
            response, attempts = self.router.chat(request)
            self._record_success(trace, request, response, attempts, write_trace=write_trace)
            response.raw = {
                **(response.raw or {}),
                "plural_trace_id": self._response_trace_id(trace, trace_context),
            }
            return response
        except Exception as exc:
            trace.add_llm(request=request, response=None, error=str(exc))
            if write_trace:
                self.writer.record(trace)
            raise

    async def achat(
        self,
        *,
        model: str,
        messages: Sequence[Message | dict[str, Any]],
        models: list[str] | None = None,
        tools: Sequence[Tool | dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
        write_trace: bool = True,
        trace_context: TraceContext | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Async chat completion.

        Args:
            model: Primary model id.
            messages: Conversation messages.
            models: Optional fallback chain.
            tools: Optional tools.
            temperature: Sampling temperature.
            max_tokens: Max tokens.
            metadata: Request metadata.
            tags: Extra trace tags.
            write_trace: Whether to persist this model-call trace.
            trace_context: Optional parent and episode lineage.
            **kwargs: Additional request fields.

        Returns:
            Normalized chat response.
        """
        request = self._make_request(
            model=model,
            messages=messages,
            models=models,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
            **kwargs,
        )
        trace = self._call_trace(request, tags=tags, trace_context=trace_context)
        try:
            response, attempts = await self.router.achat(request)
            self._record_success(trace, request, response, attempts, write_trace=write_trace)
            response.raw = {
                **(response.raw or {}),
                "plural_trace_id": self._response_trace_id(trace, trace_context),
            }
            return response
        except Exception as exc:
            trace.add_llm(request=request, response=None, error=str(exc))
            if write_trace:
                self.writer.record(trace)
            raise

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message | dict[str, Any]],
        models: list[str] | None = None,
        tags: dict[str, str] | None = None,
        write_trace: bool = True,
        trace_context: TraceContext | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """Stream a chat completion and record a trace on completion.

        Args:
            model: Primary model id.
            messages: Conversation messages.
            models: Optional fallback chain.
            tags: Extra trace tags.
            write_trace: Whether to persist this model-call trace.
            trace_context: Optional parent and episode lineage.
            **kwargs: Additional request fields.

        Yields:
            Stream chunks.
        """
        request = self._make_request(
            model=model, messages=messages, models=models, stream=True, **kwargs
        )
        trace = self._call_trace(request, tags=tags, trace_context=trace_context)
        response_trace_id = self._response_trace_id(trace, trace_context)

        def on_complete(response: ChatResponse, attempts: list[AttemptRecord]) -> None:
            self._record_success(
                trace,
                request,
                response,
                attempts,
                write_trace=write_trace,
            )

        for chunk in self.router.stream(request, on_complete=on_complete):
            yield chunk.model_copy(
                update={
                    "raw": {
                        **(chunk.raw or {}),
                        "plural_trace_id": response_trace_id,
                    }
                }
            )

    async def astream(
        self,
        *,
        model: str,
        messages: Sequence[Message | dict[str, Any]],
        models: list[str] | None = None,
        tags: dict[str, str] | None = None,
        write_trace: bool = True,
        trace_context: TraceContext | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Async streaming chat completion.

        Args:
            model: Primary model id.
            messages: Conversation messages.
            models: Optional fallback chain.
            tags: Extra trace tags.
            write_trace: Whether to persist this model-call trace.
            trace_context: Optional parent and episode lineage.
            **kwargs: Additional request fields.

        Yields:
            Stream chunks.
        """
        request = self._make_request(
            model=model, messages=messages, models=models, stream=True, **kwargs
        )
        trace = self._call_trace(request, tags=tags, trace_context=trace_context)
        response_trace_id = self._response_trace_id(trace, trace_context)

        def on_complete(response: ChatResponse, attempts: list[AttemptRecord]) -> None:
            self._record_success(
                trace,
                request,
                response,
                attempts,
                write_trace=write_trace,
            )

        async for chunk in self.router.astream(request, on_complete=on_complete):
            yield chunk.model_copy(
                update={
                    "raw": {
                        **(chunk.raw or {}),
                        "plural_trace_id": response_trace_id,
                    }
                }
            )

    def label(
        self,
        trace_id: str,
        *,
        scores: dict[str, float] | None = None,
        reward: float | None = None,
        labels: dict[str, Any] | None = None,
        feedback: str | None = None,
    ) -> None:
        """Attach a late outcome label to a trace.

        Args:
            trace_id: Trace id returned via ``response.raw['plural_trace_id']``.
            scores: Named scores.
            reward: Scalar reward.
            labels: Discrete labels.
            feedback: Free-form feedback.
        """
        self.writer.label(
            trace_id,
            scores=scores,
            reward=reward,
            labels=labels,
            feedback=feedback,
        )

    def flush(self) -> None:
        """Flush pending traces."""
        self.writer.flush()

    def close(self) -> None:
        """Flush traces and close providers."""
        self.writer.close()
        for provider in self._providers.values():
            provider.close()

    async def aclose(self) -> None:
        """Async close."""
        self.writer.close()
        for provider in self._providers.values():
            await provider.aclose()

    def __enter__(self) -> Client:
        """Enter context manager.

        Returns:
            This client instance.
        """
        return self

    def __exit__(self, *args: object) -> None:
        """Exit context manager and close resources."""
        self.close()

    def _make_request(
        self,
        *,
        model: str,
        messages: Sequence[Message | dict[str, Any]],
        models: list[str] | None = None,
        tools: Sequence[Tool | dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatRequest:
        parsed_messages = [
            m if isinstance(m, Message) else Message.model_validate(m) for m in messages
        ]
        parsed_tools = None
        if tools is not None:
            parsed_tools = [t if isinstance(t, Tool) else Tool.model_validate(t) for t in tools]
        return ChatRequest(
            model=model,
            messages=parsed_messages,
            models=models,
            tools=parsed_tools,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata or {},
            stream=stream,
            **kwargs,
        )

    def _record_success(
        self,
        trace: Trace,
        request: ChatRequest,
        response: ChatResponse,
        attempts: list[AttemptRecord],
        *,
        write_trace: bool = True,
    ) -> None:
        req_for_trace: ChatRequest | dict[str, Any]
        resp_for_trace: ChatResponse | None
        if self.capture_content:
            req_for_trace = request
            resp_for_trace = response
        else:
            req_for_trace = request.model_dump(exclude={"messages"})
            resp_for_trace = response.model_copy(
                update={
                    "choices": [
                        c.model_copy(
                            update={"message": c.message.model_copy(update={"content": None})}
                        )
                        for c in response.choices
                    ]
                }
            )
        trace.add_llm(
            request=req_for_trace,
            response=resp_for_trace,
            attempts=[Attempt(**a.to_dict()) for a in attempts],
        )
        if response.choices:
            trace.stop_reason = response.choices[0].finish_reason
        if write_trace:
            self.writer.record(trace)

    def _call_trace(
        self,
        request: ChatRequest,
        *,
        tags: dict[str, str] | None,
        trace_context: TraceContext | None,
    ) -> Trace:
        return Trace(
            trace_kind="llm_call" if trace_context is not None else "production",
            parent_trace_id=trace_context.parent_trace_id if trace_context else None,
            episode_trace_id=trace_context.episode_trace_id if trace_context else None,
            model=request.model,
            tags={**self.tags, **(tags or {})},
            metadata=dict(request.metadata),
        )

    @staticmethod
    def _response_trace_id(trace: Trace, trace_context: TraceContext | None) -> str:
        if trace_context is not None and trace_context.episode_trace_id:
            return trace_context.episode_trace_id
        return trace.trace_id


Plural = Client


def _provider_is_authenticated(provider: Provider) -> bool:
    """Probe one provider and report whether credentials were accepted.

    Args:
        provider: Configured provider adapter.

    Returns:
        ``True`` when the provider accepts the credentials or has no HTTP client.

    Raises:
        PluralError: If a transport error occurs while probing.
    """
    http = getattr(provider, "_client", None)
    if not isinstance(http, httpx.Client):
        return True
    name = getattr(provider, "name", "") or "unknown"
    path, headers = _auth_probe(provider, name)
    try:
        response = http.get(path, headers=headers)
    except Exception as exc:
        raise map_transport_error(exc, provider=name) from exc
    return response.status_code not in {401, 403}


def _auth_probe(provider: Provider, name: str) -> tuple[str, dict[str, str] | None]:
    """Return the path and optional headers for an auth probe.

    Args:
        provider: Configured provider adapter.
        name: Provider slug.

    Returns:
        A ``(path, headers)`` pair. ``headers`` is ``None`` when the provider
        client's default headers already carry credentials.
    """
    if name == "anthropic":
        return "/v1/models", None
    if name == "bedrock":
        path = "/foundation-models"
        signing = getattr(provider, "_signing", None)
        config = getattr(provider, "config", None)
        if signing:
            from plural.providers.bedrock import sigv4_headers

            access_key_id, secret_access_key, session_token = signing
            base_url = getattr(config, "base_url", "") if config is not None else ""
            return path, sigv4_headers(
                method="GET",
                url=f"{base_url}{path}",
                region=getattr(provider, "aws_region", "us-east-1"),
                payload=b"",
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                session_token=session_token,
            )
        api_key = getattr(config, "api_key", "") if config is not None else ""
        return path, {"Authorization": f"Bearer {api_key}"}
    return "/models", None


def start_trace(**kwargs: Any) -> Trace:
    """Create an empty trace for manual / environment use.

    Args:
        **kwargs: Fields forwarded to :class:`~plural.tracing.schema.Trace`.

    Returns:
        A new :class:`~plural.tracing.schema.Trace`.
    """
    if "trace_id" not in kwargs:
        kwargs["trace_id"] = new_trace_id()
    return Trace(**kwargs)
