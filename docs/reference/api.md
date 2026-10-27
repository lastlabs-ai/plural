---
route: /docs/reference/api
title: "API reference"
order: 240
description: "Supported public Python API signatures from the current source."
audience: all
nav: false
nav_group: Reference
---
# API reference

Start with [the support queue tutorial](../tutorials/support-queue.md) for complete working code. Use the [field catalog](fields.md) for definition fields, defaults, and constraints. This reference is generated from supported root APIs and public extension modules. Planner and executor implementation types such as `JobRunner`, `JobSpec`, and `TrialSpec` are intentionally omitted.

Model constructors are described by their field contracts rather than duplicating long generated signatures. Methods below are defined on the listed class; ordinary inherited Pydantic methods are not repeated.

`Client` provider adapters are the application inference API. Public `Job` native execution is a separate OpenAI-compatible chat-completions path.

## plural.Client

Unified client for routing, tracing, and (via other modules) environments.

```text
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
```

```python
plural.Client(*, api_key: 'str | None' = None, providers: 'Mapping[str, str | Provider] | None' = None, base_url: 'str | None' = None, catalog: 'ModelCatalog | None' = None, policy: 'RoutingPolicy | None' = None, sink: 'Sink | None' = None, redactor: 'Redactor | None' = None, sampler: 'Sampler | None' = None, capture_content: 'bool | None' = None, max_retries: 'int' = 2, max_cost_usd: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, tags: 'dict[str, str] | None' = None, trace_dir: 'str | Path | None' = None, project: 'str | None' = None) -> 'None'
```

### plural.Client.is_authenticated

```python
is_authenticated(self) -> 'bool'
```

Return whether configured credentials are accepted.

```text
Sends a lightweight authenticated request to each HTTP provider.
In-process providers (no HTTP client) are treated as authenticated.

Returns:
    ``True`` when every provider accepts the credentials or has no
    HTTP client to probe.

Raises:
    PluralTimeoutError: If a provider cannot be reached.
    PluralError: If a transport error occurs while probing.
```

### plural.Client.push

```python
push(self, obj: 'Any', **kwargs: 'Any') -> 'dict[str, Any]'
```

Push one immutable revision, creating its parent by slug.

```text
The revision is usable as soon as it is saved and stays private to
the project. Pushing identical content again returns the same
revision. To push a project directory with its dependencies, use
``plural <kind> push`` or :func:`plural.project.sync.push`.

Args:
    obj: Environment, Task, Verifier, Agent, Harness, Benchmark, or Trace.
    **kwargs: Hosted revision ids for graph edges, such as a Task's
        ``environment_revision_id`` and ``verifier_revision_ids``.

Returns:
    The hosted revision record.
```

### plural.Client.chat

```python
chat(self, *, model: 'str', messages: 'Sequence[Message | dict[str, Any]]', models: 'list[str] | None' = None, tools: 'Sequence[Tool | dict[str, Any]] | None' = None, temperature: 'float | None' = None, max_tokens: 'int | None' = None, metadata: 'dict[str, Any] | None' = None, tags: 'dict[str, str] | None' = None, write_trace: 'bool' = True, trace_context: 'TraceContext | None' = None, **kwargs: 'Any') -> 'ChatResponse'
```

Create a chat completion.

```text
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
```

### plural.Client.achat

```python
achat(self, *, model: 'str', messages: 'Sequence[Message | dict[str, Any]]', models: 'list[str] | None' = None, tools: 'Sequence[Tool | dict[str, Any]] | None' = None, temperature: 'float | None' = None, max_tokens: 'int | None' = None, metadata: 'dict[str, Any] | None' = None, tags: 'dict[str, str] | None' = None, write_trace: 'bool' = True, trace_context: 'TraceContext | None' = None, **kwargs: 'Any') -> 'ChatResponse'
```

Async chat completion.

```text
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
```

### plural.Client.stream

```python
stream(self, *, model: 'str', messages: 'Sequence[Message | dict[str, Any]]', models: 'list[str] | None' = None, tags: 'dict[str, str] | None' = None, write_trace: 'bool' = True, trace_context: 'TraceContext | None' = None, **kwargs: 'Any') -> 'Iterator[StreamChunk]'
```

Stream a chat completion and record a trace on completion.

```text
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
```

### plural.Client.astream

```python
astream(self, *, model: 'str', messages: 'Sequence[Message | dict[str, Any]]', models: 'list[str] | None' = None, tags: 'dict[str, str] | None' = None, write_trace: 'bool' = True, trace_context: 'TraceContext | None' = None, **kwargs: 'Any') -> 'AsyncIterator[StreamChunk]'
```

Async streaming chat completion.

```text
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
```

### plural.Client.label

```python
label(self, trace_id: 'str', *, scores: 'dict[str, float] | None' = None, reward: 'float | None' = None, labels: 'dict[str, Any] | None' = None, feedback: 'str | None' = None) -> 'None'
```

Attach a late outcome label to a trace.

```text
Args:
    trace_id: Trace id returned via ``response.raw['plural_trace_id']``.
    scores: Named scores.
    reward: Scalar reward.
    labels: Discrete labels.
    feedback: Free-form feedback.
```

### plural.Client.flush

```python
flush(self) -> 'None'
```

Flush pending traces.

### plural.Client.close

```python
close(self) -> 'None'
```

Flush traces and close providers.

### plural.Client.aclose

```python
aclose(self) -> 'None'
```

Async close.

## plural.types.AudioContent

An audio content part.

```text
Attributes:
    type: Discriminator; always ``"input_audio"``.
    data: Base64-encoded audio bytes.
    format: Audio format such as ``"wav"`` or ``"mp3"``.
```

## plural.types.ChatRequest

A normalized chat completion request.

```text
Attributes:
    model: Primary model id in ``author/slug`` form.
    messages: Conversation messages.
    models: Optional fallback model chain (tried in order after ``model``).
    temperature: Sampling temperature.
    top_p: Nucleus sampling parameter.
    max_tokens: Maximum tokens to generate.
    stop: Stop sequence(s).
    tools: Tools available to the model.
    tool_choice: Tool selection strategy or a forced tool.
    response_format: Structured output request.
    stream: Whether to stream the response.
    seed: Deterministic seed when supported.
    user: End-user identifier for abuse detection / analytics.
    provider: Provider routing preferences.
    metadata: Arbitrary request metadata propagated into traces.
    extra: Provider-specific passthrough fields.

Examples:
    >>> ChatRequest(
    ...     model="anthropic/claude-sonnet-4",
    ...     messages=[Message(role="user", content="Hi")],
    ... ).temperature is None
    True
```

## plural.types.ChatResponse

A normalized chat completion response.

```text
Attributes:
    id: Provider-assigned completion id.
    model: Model that produced the response (may differ from the request).
    choices: Completion choices.
    usage: Token usage and optional cost.
    provider: Provider slug that served the request.
    region: Region of the host that served it. The same provider charges
        different rates per region, so billing needs both.
    created: Unix timestamp when the completion was created.
    raw: Original provider payload for debugging.
    latency_ms: End-to-end latency in milliseconds.
    attempts: Number of attempts (including retries/fallbacks) used.

Examples:
    >>> resp = ChatResponse(
    ...     id="chatcmpl-1",
    ...     model="openai/gpt-4o-mini",
    ...     choices=[Choice(message=Message(role="assistant", content="Hi"))],
    ... )
    >>> resp.text
    'Hi'
```

## plural.types.Choice

A single completion choice.

```text
Attributes:
    index: Choice index.
    message: The assistant message.
    finish_reason: Why generation stopped.
```

## plural.types.FinishReason

Why generation stopped.

```python
plural.types.FinishReason(*values)
```

## plural.types.FunctionCall

A function invocation requested by the model.

```text
Attributes:
    name: Function name to call.
    arguments: JSON-encoded argument object as a string.
```

## plural.types.FunctionDefinition

JSON-schema function definition for tool calling.

```text
Attributes:
    name: Function name exposed to the model.
    description: Human-readable description of the function.
    parameters: JSON Schema object describing the parameters.
    strict: Whether to request strict schema adherence when supported.
```

## plural.types.ImageContent

An image content part (URL or base64 data URL).

```text
Attributes:
    type: Discriminator; always ``"image_url"``.
    url: HTTP(S) URL or ``data:`` URL for the image.
    detail: Optional detail hint for vision models.
```

## plural.types.Message

A single chat message.

```text
Attributes:
    role: Message role.
    content: Text content, a list of content parts, or ``None`` when the
        message only carries tool calls.
    name: Optional participant name.
    tool_calls: Tool calls requested by the assistant, if any.
    tool_call_id: Id of the tool call this message responds to (tool role).
    reasoning: Reasoning ("thinking") text the model produced before its
        answer. Separate from ``content`` because callers usually render it
        differently, and some hosts bill it as output tokens.
    reasoning_signature: Host-issued attestation for ``reasoning``.
        Anthropic and Bedrock reject a thinking block replayed without it,
        so it has to survive a round trip.

Examples:
    >>> Message(role="user", content="Hello").role
    'user'
```

## plural.types.ProviderPreferences

OpenRouter-compatible provider routing preferences.

```text
Attributes:
    order: Provider slugs to try in order.
    allow_fallbacks: Whether to allow backup providers.
    require_parameters: Only use providers that support all request params.
    data_collection: Whether to allow providers that may store data.
    only: Allow-list of provider slugs.
    ignore: Deny-list of provider slugs.
    sort: Sort key such as ``"price"``, ``"latency"``, or ``"throughput"``.
    max_price: Maximum price constraints for prompt/completion tokens.
```

## plural.types.ResponseFormat

Structured output / response format request.

```text
Attributes:
    type: Format type such as ``"text"``, ``"json_object"``, or ``"json_schema"``.
    json_schema: Schema payload when ``type`` is ``"json_schema"``.
```

## plural.types.Role

Chat message role.

```python
plural.types.Role(*values)
```

## plural.types.StreamChunk

A single streaming chunk.

```text
Attributes:
    id: Completion id.
    model: Model id.
    delta: Incremental content.
    finish_reason: Present on the final chunk when known.
    usage: Usage, typically only on the final chunk.
    provider: Provider slug.
    region: Region of the host serving the stream.
    raw: Original provider chunk payload.
```

### plural.types.StreamChunk.to_openai

```python
to_openai(self) -> 'dict[str, Any]'
```

Serialize this chunk as an OpenAI Chat Completions SSE object.

```text
Every adapter yields :class:`StreamChunk`. Hosted gateways and HTTP
clients that speak the OpenAI wire format must call this rather than
forwarding :attr:`raw`, which is the provider-native event and is not
a stable client contract.

Returns:
    A ``chat.completion.chunk`` object. ``usage`` is present only when
    the host reported it, typically on the last chunk.
```

## plural.types.StreamDelta

A partial delta within a stream chunk.

```text
Attributes:
    role: Role, typically present only on the first delta.
    content: Incremental text content.
    reasoning: Incremental reasoning ("thinking") text. Thinking models emit
        this for seconds before any ``content`` appears, so a client that
        ignores it looks frozen.
    reasoning_started: ``True`` when a thinking block opens. Some hosts
        encrypt the tokens and send empty ``thinking_delta`` events; this
        flag is how a UI learns the model is thinking anyway.
    reasoning_finished: ``True`` when that thinking block closes.
    reasoning_signature: Incremental attestation for the reasoning block.
    tool_calls: Incremental tool call fragments, in OpenAI's streaming shape
        (``index``, ``id``, ``function.name``, ``function.arguments``).
```

## plural.types.TextContent

A text content part.

```text
Attributes:
    type: Discriminator; always ``"text"``.
    text: The text content.
```

## plural.types.Tool

A tool the model may call.

```text
Attributes:
    type: Tool type; currently only ``"function"``.
    function: The function definition.

Examples:
    >>> tool = Tool(
    ...     function=FunctionDefinition(
    ...         name="lookup_order",
    ...         description="Look up an order by id",
    ...         parameters={
    ...             "type": "object",
    ...             "properties": {"order_id": {"type": "string"}},
    ...             "required": ["order_id"],
    ...         },
    ...     )
    ... )
    >>> tool.function.name
    'lookup_order'
```

## plural.types.ToolCall

A tool call in an assistant message.

```text
Attributes:
    id: Provider-assigned call id used to correlate tool responses.
    type: Tool type; currently only ``"function"``.
    function: The function call payload.
    extra_content: Opaque provider data that must be sent back with the
        call on the next turn, keyed by provider, such as Gemini's
        ``{"google": {"thought_signature": ...}}``. Gemini rejects a replayed
        function call without its signature.
```

## plural.types.Usage

Token usage for a completion.

```text
Attributes:
    prompt_tokens: Input token count.
    completion_tokens: Output token count. Includes reasoning tokens when the
        provider bills them as output.
    total_tokens: Sum of prompt and completion tokens.
    cost: Estimated USD cost when known.
    reasoning_tokens: How many completion tokens were reasoning, when the
        provider reports the split. ``None`` means unreported, not zero.
    cache_read_tokens: How many prompt tokens were served from the host's
        prompt cache. Always a subset of ``prompt_tokens``.
    cache_write_tokens: How many prompt tokens were written to the host's
        prompt cache. Always a subset of ``prompt_tokens``.
    cache_write_long_tokens: How many of ``cache_write_tokens`` were written
        with a long-lived cache (Anthropic's one-hour TTL), which bills higher.
```

### plural.types.Usage.from_counts

```python
from_counts(prompt: 'int', completion: 'int', cost: 'float | None' = None, *, reasoning_tokens: 'int | None' = None, cache_read_tokens: 'int' = 0, cache_write_tokens: 'int' = 0, cache_write_long_tokens: 'int' = 0) -> 'Usage'
```

Build a :class:`Usage` from prompt/completion counts.

```text
Args:
    prompt: Prompt token count, including any cached tokens.
    completion: Completion token count.
    cost: Optional USD cost.
    reasoning_tokens: Reasoning tokens included in ``completion``, when reported.
    cache_read_tokens: Prompt tokens read from the host's cache.
    cache_write_tokens: Prompt tokens written to the host's cache.
    cache_write_long_tokens: Cache writes with a long-lived TTL.

Returns:
    A populated :class:`Usage` instance.

Examples:
    >>> Usage.from_counts(10, 5).total_tokens
    15
```

## plural.types.cached_prompt_tokens_of

Cache reads and writes a host reported inside its prompt count.

```text
OpenAI Chat Completions and the OpenAI-compatible hosts report
``prompt_tokens_details.cached_tokens``, the Responses API
``input_tokens_details.cached_tokens``, DeepSeek ``prompt_cache_hit_tokens``,
Moonshot a top-level ``cached_tokens``, and Gemini ``cachedContentTokenCount``.
All of them count those tokens inside the prompt total. Hosts that relay
Anthropic report writes as ``prompt_tokens_details.cache_write_tokens``.

Args:
    raw: A provider usage object.

Returns:
    A (cache read, cache write) pair of token counts, zero when unreported.

Examples:
    >>> cached_prompt_tokens_of({"prompt_tokens_details": {"cached_tokens": 64}})
    (64, 0)
```

```python
plural.types.cached_prompt_tokens_of(raw: 'Mapping[str, Any] | None') -> 'tuple[int, int]'
```

## plural.types.reasoning_tokens_of

The reasoning-token count a provider reported.

```text
OpenAI Chat Completions uses ``completion_tokens_details.reasoning_tokens`` and
the Responses API uses ``output_tokens_details.reasoning_tokens``. Gemini reports
``thoughtsTokenCount``. A host may also send ``reasoning_tokens`` directly.

Args:
    raw: A provider usage object.

Returns:
    The count, or ``None`` when the provider reported none.
```

```python
plural.types.reasoning_tokens_of(raw: 'Mapping[str, Any] | None') -> 'int | None'
```

## plural.types.text_content

Extract plain text from a message.

```text
Args:
    message: The message to extract text from.

Returns:
    Concatenated text content, or an empty string.
```

```python
plural.types.text_content(message: 'Message') -> 'str'
```

## plural.tracing.Trace

A complete record of an LLM interaction or environment rollout.

```text
Production traffic and environment rollouts emit the same shape so that
datasets, benchmarks, and a future autorouter can consume either source.

Attributes:
    trace_id: Opaque unique id.
    environment: Environment name when produced by a rollout.
    environment_version: Environment version string.
    environment_fingerprint: Hash of the Environment revision.
    task_id: Task identity for this Trial.
    model: Policy / model id used for this episode.
    initial_state: Explicitly safe Environment snapshot at reset.
    steps: Ordered steps (decisions, LLM calls, tool calls, events).
    final_state: Explicitly safe Environment snapshot at episode close.
    outcome: Optional labeled outcome. ``outcome.reward`` is the return.
    metrics: Episode aggregates (turns, cost, latency, tool counts).
    terminated: Natural end (``env.done()``).
    truncated: Cut off by ``max_turns``.
    tags: Free-form tags for filtering.
    metadata: Arbitrary metadata.
    created_at: Creation timestamp (UTC).
    schema_version: Trace schema version for stability.

Examples:
    >>> t = Trace(trace_id="t1", tags={"env": "prod"})
    >>> t.schema_version
    '3.0.0'
```

### plural.tracing.Trace.add_llm

```python
add_llm(self, *, request: 'ChatRequest | dict[str, Any] | None', response: 'ChatResponse | None', attempts: 'list[Attempt] | None' = None, error: 'str | None' = None) -> 'LLMCall'
```

Append an LLM call step.

```text
Args:
    request: Chat request.
    response: Chat response if successful.
    attempts: Attempt records.
    error: Error message if failed.

Returns:
    The appended :class:`LLMCall`.
```

### plural.tracing.Trace.add_action

```python
add_action(self, name: 'str', arguments: 'dict[str, Any]', *, action_id: 'str | None' = None, tool_call_id: 'str | None' = None, source: 'ActionSource' = 'environment_native', observation: 'Any' = None, result: 'Any' = None, error: 'str | None' = None, latency_ms: 'float | None' = None) -> 'ActionStep'
```

Append an action step.

### plural.tracing.Trace.add_turn

```python
add_turn(self, *, observation: 'Any' = None, model_context: 'ChatRequest | dict[str, Any] | None' = None, model_output: 'ChatResponse | None' = None, parsed_action: 'list[ParsedAction] | None' = None, actions: 'list[ActionStep] | None' = None, reward_events: 'list[RewardEvent] | None' = None, reasoning: 'list[ReasoningBlock] | None' = None, turn: 'int | None' = None) -> 'Turn'
```

Append a turn step for one model turn.

### plural.tracing.Trace.transitions

```python
transitions(self, *, source: "Literal['outcome', 'events', 'both']" = 'outcome') -> 'list[Transition]'
```

Flatten this episode into step-by-step transitions.

```text
Prefers :class:`Turn` steps. Falls back to grouping flat
``llm`` / ``action`` steps so production traces still export.

Args:
    source: Reward source, matching :meth:`turn_rewards`.

Returns:
    One :class:`Transition` per turn.
```

### plural.tracing.Trace.turns

```python
turns(self) -> 'list[Turn]'
```

Return turn steps in order.

### plural.tracing.Trace.credit

```python
credit(self, value: 'float', *, name: 'str' = 'late', reason: 'str | None' = None, turn_index: 'int | None' = None) -> 'RewardEvent | TraceOutcome'
```

Inject reward after the fact — episode-wide or onto one turn.

```text
Use this when the signal arrives late (likes, a human review, a
downstream KPI). Credit assignment across earlier actions is
:meth:`returns`, not the environment's job.

Args:
    value: Reward to add.
    name: Reward source (``"likes"``, ``"review"``, …).
    reason: Optional human-readable reason.
    turn_index: Which turn to attribute to. ``None`` updates
        ``outcome.reward`` (and ``outcome.scores[name]``). Negative
        indices count from the end.

Returns:
    The new :class:`RewardEvent` or the updated :class:`TraceOutcome`.

Raises:
    IndexError: If ``turn_index`` is out of range.
```

### plural.tracing.Trace.turn_rewards

```python
turn_rewards(self, *, source: "Literal['outcome', 'events', 'both']" = 'outcome') -> 'list[float]'
```

Per-turn reward used as ``r_t`` before discounting.

### plural.tracing.Trace.returns

```python
returns(self, gamma: 'float' = 1.0, *, source: "Literal['outcome', 'events', 'both']" = 'outcome') -> 'list[float]'
```

Discounted return ``G_t = r_t + γ G_{t+1}`` for each decision.

```text
This is how a trainer gives the *research* action credit for a later
post's likes: the environment does not rewrite history; the trainer
walks the episode backward.

Args:
    gamma: Discount factor in ``[0, 1]``.
    source: See :meth:`turn_rewards`.

Returns:
    One return per turn, same order as :meth:`turns`.

Examples:
    >>> t = Trace(outcome=TraceOutcome(reward=1.0))
    >>> t.add_turn(parsed_action=[ParsedAction(name="search")])
    >>> t.add_turn(parsed_action=[ParsedAction(name="answer")])
    >>> t.returns(gamma=0.9)
    [0.9, 1.0]
```

### plural.tracing.Trace.label

```python
label(self, *, scores: 'dict[str, float] | None' = None, reward: 'float | None' = None, labels: 'dict[str, Any] | None' = None, feedback: 'str | None' = None) -> 'TraceOutcome'
```

Attach or update the outcome.

```text
Args:
    scores: Named Verifier outputs.
    reward: Scalar reward.
    labels: Discrete labels.
    feedback: Free-form feedback.

Returns:
    The updated :class:`TraceOutcome`.
```

## plural.tracing.TraceContext

Lineage supplied by a caller when creating a child trace.

## plural.tracing.resources.trace_json_schema

Load the canonical trace JSON Schema from the installed package.

```text
Returns:
    The JSON Schema as a mutable dictionary.

Raises:
    ValueError: If the packaged resource is not a JSON object.
```

```python
plural.tracing.resources.trace_json_schema() -> 'dict[str, Any]'
```

## plural.Job

Simple public runner for a Task or Benchmark and catalog-backed Agents.

```text
``credentials`` gives each Agent's credential values by Agent name, such as
``{"sales-bot": {"SALESFORCE_TOKEN": token}}``. A credential an Agent
declares and is not given here is read from the exported variable of the
same name.

For a Task whose Environment has a party, ``party`` lists the Agents that
share each episode, in seat order; list one Agent more than once for
self-play. Left out, every Agent in ``agents`` plays, once each.

``episode_server`` says where the Job serves an external Agent's episodes;
by default it listens on a free loopback port.
```

```python
plural.Job(source: 'Task | Benchmark', agents: 'Sequence[Agent]', *, party: 'Sequence[Agent] | None' = None, mode: 'JobMode' = <JobMode.EVAL: 'eval'>, attempts: 'int' = 1, concurrency: "int | Literal['auto']" = 1, per_runtime_concurrency: 'int | None' = None, priority: 'int' = 0, retry: 'RetryPolicy | None' = None, provider: 'Any' = None, providers: 'Mapping[str, Any] | None' = None, registry: 'Any' = None, store: 'Any' = None, environ: 'Mapping[str, str] | None' = None, resource_resolvers: 'Mapping[str, Any] | None' = None, progress: 'Any' = None, project_policy: 'Any' = None, catalog: 'ModelCatalog | None' = None, client: 'Any' = None, api_key: 'str | None' = None, credentials: 'Mapping[str, Mapping[str, str]] | None' = None, episode_server: 'Any' = None) -> 'None'
```

### plural.Job.run_async

```python
run_async(self, *, resume: 'bool' = False) -> 'JobResult'
```

Execute this Job without blocking the caller's event loop.

```text
Returns:
    The collected Trial outcomes.
```

### plural.Job.run

```python
run(self, *, resume: 'bool' = False) -> 'JobResult'
```

Execute synchronously when no event loop is already running.

```text
Returns:
    The collected Trial outcomes.
```

## plural.Benchmark

A semantic version that pins an ordered set of Tasks.

```text
Each version is a release. Beyond its Tasks it may declare categories,
scoring rules, and evaluation tracks; see :class:`BenchmarkRelease`.
``title`` is only the display name in the hosted project.
```

### plural.Benchmark.diff

```python
diff(self, other: 'Benchmark') -> 'BenchmarkDiff'
```

Return the structured pin and configuration changes from this version.

### plural.Benchmark.dependency_graph

```python
dependency_graph(self) -> 'dict[str, Any]'
```

Export the complete pinned graph in deterministic dependency order.

```text
Returns:
    Benchmark metadata and all pinned Task dependencies.
```

### plural.Benchmark.export

```python
export(self) -> 'dict[str, Any]'
```

Return the deterministic complete dependency graph.

## plural.project.resources.LocalResource

One validated local resource and the SDK object it defines.

```python
plural.project.resources.LocalResource(ref: 'ResourceRef', directory: 'Path', value: 'Any', dependencies: 'tuple[ResourceRef, ...]') -> None
```

## plural.project.manifests.LockEntry

One resolved resource: its local identity and, once pushed, its revision.

## plural.project.manifests.LockFile

``plural.lock``: resolved dependency revisions and content hashes.

```text
Hosted identifiers belong to ``project_id``. Entries recorded for another
hosted project are never used as dependency pins.
```

## plural.project.layout.Project

A project directory and its identity.

```python
plural.project.layout.Project(root: 'Path', manifest: 'ProjectManifest') -> None
```

### plural.project.layout.Project.find

```python
find(start: 'Path | None' = None) -> 'Project'
```

Load the project containing ``start`` (default: the working directory).

```text
Returns:
    The project.

Raises:
    ProjectError: When no enclosing directory holds ``project.yaml``.
```

### plural.project.layout.Project.at

```python
at(root: 'Path') -> 'Project'
```

Load the project whose ``project.yaml`` is directly in ``root``.

```text
Returns:
    The project.

Raises:
    ProjectError: When ``project.yaml`` is missing or invalid.
```

### plural.project.layout.Project.resource_dir

```python
resource_dir(self, ref: 'ResourceRef') -> 'Path'
```

Directory that holds one resource.

```text
Returns:
    The resource directory, whether or not it exists.

Raises:
    ValueError: When the name is not one folder name, such as one a
        hosted record supplied with ``/`` or ``..``.
```

### plural.project.layout.Project.manifest_path

```python
manifest_path(self, ref: 'ResourceRef') -> 'Path'
```

Canonical manifest path for one resource.

```text
Returns:
    The manifest path, whether or not it exists.
```

### plural.project.layout.Project.has

```python
has(self, ref: 'ResourceRef') -> 'bool'
```

Whether the resource directory exists locally.

```text
Returns:
    ``True`` when the directory exists.
```

### plural.project.layout.Project.names

```python
names(self, kind: 'ResourceKind') -> 'list[str]'
```

Local resource names of one kind, sorted.

```text
Returns:
    The names.
```

### plural.project.layout.Project.resource_at

```python
resource_at(self, path: 'Path') -> 'ResourceRef | None'
```

The resource whose directory contains ``path``, if any.

```text
Returns:
    The resource, or ``None`` outside any resource directory.
```

### plural.project.layout.Project.read_lock

```python
read_lock(self) -> 'LockFile'
```

Return ``plural.lock``, or an empty lock when none exists yet.

```text
Raises:
    ProjectError: When the lock exists but is invalid.
```

### plural.project.layout.Project.write_lock

```python
write_lock(self, lock: 'LockFile') -> 'None'
```

Write ``plural.lock`` with resources in a stable order.

### plural.project.layout.Project.read_binding

```python
read_binding(self) -> 'ProjectBinding | None'
```

Return the hosted project this checkout is bound to, if any.

```text
Raises:
    ProjectError: When the binding file is unreadable.
```

### plural.project.layout.Project.write_binding

```python
write_binding(self, binding: 'ProjectBinding') -> 'None'
```

Bind this checkout to a hosted project.

## plural.project.manifests.ProjectBinding

``.plural/project.json``: the hosted project this checkout pushes to.

## plural.project.layout.ProjectError

A project, resource, or command precondition that the user must fix.

```text
``problems`` lists every independent issue so one run reports all of them.
```

```python
plural.project.layout.ProjectError(message: 'str', problems: 'list[str] | None' = None) -> 'None'
```

## plural.project.manifests.ProjectManifest

``project.yaml``: project identity and the layout version it follows.

## plural.project.layout.ResourceKind

One resource kind: its CLI noun, directory, manifest, and hosted collection.

```python
plural.project.layout.ResourceKind(name: 'str', cli: 'str', directory: 'str', manifest: 'str', label: 'str') -> None
```

## plural.project.layout.ResourceRef

A resource named within one project, such as ``task/refund``.

```python
plural.project.layout.ResourceRef(kind: 'str', name: 'str') -> None
```

### plural.project.layout.ResourceRef.parse

```python
parse(value: 'str') -> 'ResourceRef'
```

Parse ``kind/name``.

```text
Returns:
    The reference.
```

## plural.project.resources.Workspace

Resolve resources by name inside one project, caching each load.

```python
plural.project.resources.Workspace(project: 'Project', *, catalog: 'ModelCatalog | None' = None) -> 'None'
```

### plural.project.resources.Workspace.load

```python
load(self, ref: 'ResourceRef') -> 'LocalResource'
```

Load and fully validate one resource and its dependencies.

```text
Returns:
    The validated resource.

Raises:
    ProjectError: Listing every problem found.
```

### plural.project.resources.Workspace.get

```python
get(self, kind: 'str', name: 'str') -> 'Any'
```

Load a resource by kind and name, the way the CLI addresses it.

```text
``kind`` is a kind name or its CLI noun, so ``workspace.get("env",
"support-queue")`` is the object ``plural env show support-queue``
describes.

Args:
    kind: ``environment``/``env``, ``task``, ``verifier``, ``harness``,
        ``agent``, or ``benchmark``.
    name: The resource's directory name.

Returns:
    The validated SDK object, such as a ``Task`` or ``Benchmark``.

Raises:
    ProjectError: When the resource is missing or invalid.

Examples:
    >>> from plural.project import Project, Workspace
    >>> workspace = Workspace(Project.find())  # doctest: +SKIP
    >>> benchmark = workspace.get("benchmark", "support-triage")  # doctest: +SKIP
```

### plural.project.resources.Workspace.unfinished

```python
unfinished(self, roots: 'Iterable[ResourceRef]') -> 'list[str]'
```

Every ``PLURAL-TODO`` marker left in ``roots`` and what they depend on.

```text
A resource with markers still loads and runs locally; it cannot be
pushed, released, or recorded until they are gone.

Returns:
    One ``path:line: note`` entry per marker, dependencies first.
```

### plural.project.resources.Workspace.dependencies

```python
dependencies(self, ref: 'ResourceRef') -> 'tuple[ResourceRef, ...]'
```

Direct dependencies declared in a manifest, without loading code.

```text
Returns:
    The declared dependencies.

Raises:
    ProjectError: When the manifest cannot be read.
```

### plural.project.resources.Workspace.dependency_order

```python
dependency_order(self, roots: 'Iterable[ResourceRef]') -> 'list[ResourceRef]'
```

Return ``roots`` and everything they depend on, dependencies first.

```text
Unresolved references and cycles are reported before any code is
imported or anything is uploaded.

Raises:
    ProjectError: Listing unresolved references or the first cycle.
```

## plural.project.layout.check_name

Validate a project or resource name.

```text
A valid name is already a hosted slug, so a local directory and its hosted
resource are the same string on every filesystem.

Returns:
    The name, unchanged.

Raises:
    ProjectError: When the name cannot be used as a directory and slug.
```

```python
plural.project.layout.check_name(name: 'str', what: 'str') -> 'str'
```

## plural.project.layout.find_project_root

Return the nearest directory at or above ``start`` holding ``project.yaml``.

```python
plural.project.layout.find_project_root(start: 'Path | None' = None) -> 'Path | None'
```

## plural.project.schemas.manifest_schemas

Schemas for every file a project author writes by hand.

```text
Returns:
    Schemas keyed by file name, such as ``task.yaml``.
```

```python
plural.project.schemas.manifest_schemas() -> 'dict[str, dict[str, Any]]'
```

## plural.project.schemas.public_schema

Return a JSON Schema containing only public authoring fields.

```text
Returns:
    A detached schema safe for generated public references.
```

```python
plural.project.schemas.public_schema(model: 'type[BaseModel]') -> 'dict[str, Any]'
```

## plural.project.layout.resource_kind

Return a kind by its name (``environment``) or CLI noun (``env``).

```text
Raises:
    ValueError: When the name is not a resource kind.
```

```python
plural.project.layout.resource_kind(name: 'str') -> 'ResourceKind'
```

## plural.execution.JobStore

Crash-safe filesystem persistence for local execution.

```python
plural.execution.JobStore(root: 'Path' = PosixPath('<default>'), *, on_event: 'Callable[[ProgressEvent], None] | None' = None) -> 'None'
```

### plural.execution.JobStore.job_path

```python
job_path(self, job_id: 'str') -> 'Path'
```

Return a validated job directory.

### plural.execution.JobStore.initialize

```python
initialize(self, spec: 'JobSpec', plan: 'JobPlan') -> 'Path'
```

Create or validate a locked job directory.

### plural.execution.JobStore.load_spec

```python
load_spec(self, job_id: 'str') -> 'JobSpec'
```

Load a persisted job config.

### plural.execution.JobStore.load_lock

```python
load_lock(self, job_id: 'str') -> 'JobLock'
```

Load a persisted reproducibility lock.

### plural.execution.JobStore.list_jobs

```python
list_jobs(self) -> 'tuple[dict[str, Any], ...]'
```

List stored jobs without accepting partial files as results.

### plural.execution.JobStore.emit

```python
emit(self, job_id: 'str', event_type: 'str', status: 'str', *, trial_id: 'str | None' = None, execution_id: 'int | None' = None, message: 'str' = '', data: 'Mapping[str, Any] | None' = None, secret_values: 'Iterable[str]' = ()) -> 'ProgressEvent'
```

Append one monotonic, sanitized progress event.

### plural.execution.JobStore.events

```python
events(self, job_id: 'str', *, after: 'int' = 0, follow: 'bool' = False, poll_interval: 'float' = 0.1) -> 'Iterable[ProgressEvent]'
```

Yield events after a sequence cursor, optionally following updates.

### plural.execution.JobStore.request_cancel

```python
request_cancel(self, job_id: 'str') -> 'None'
```

Atomically create a cancellation marker.

### plural.execution.JobStore.clear_cancel

```python
clear_cancel(self, job_id: 'str') -> 'None'
```

Clear a prior cancellation marker before explicit resume.

### plural.execution.JobStore.cancel_requested

```python
cancel_requested(self, job_id: 'str') -> 'bool'
```

Return whether cancellation was requested.

### plural.execution.JobStore.trial_path

```python
trial_path(self, trial: 'TrialSpec | str', job_id: 'str | None' = None) -> 'Path'
```

Return a validated trial directory.

### plural.execution.JobStore.successful_result

```python
successful_result(self, trial: 'TrialSpec') -> 'TrialResult | None'
```

Return a successful persisted trial result, if present.

### plural.execution.JobStore.next_execution_id

```python
next_execution_id(self, trial: 'TrialSpec') -> 'int'
```

Return the next monotonic execution ID for a trial.

### plural.execution.JobStore.trial_results

```python
trial_results(self, job_id: 'str') -> 'tuple[TrialResult, ...]'
```

Load all complete trial results in lexical order.

### plural.execution.JobStore.write_trial_execution

```python
write_trial_execution(self, trial: 'TrialSpec', execution_id: 'int', result: 'TrialResult', *, stdout: 'bytes' = b'', stderr: 'bytes' = b'', artifacts: 'Iterable[DownloadedFile]' = (), verifier_stdout: 'bytes' = b'', verifier_stderr: 'bytes' = b'') -> 'Path'
```

Append one immutable execution and update the selected result.

### plural.execution.JobStore.write_job_result

```python
write_job_result(self, result: 'JobResult') -> 'Path'
```

Atomically publish the aggregate result.

### plural.execution.JobStore.write_review

```python
write_review(self, trial: 'TrialSpec', verifier_name: 'str', submission: 'Mapping[str, Any]', result: 'TrialResult') -> 'Path'
```

Append one immutable human review and publish its resolved Trial result.

### plural.execution.JobStore.read_job_result

```python
read_job_result(self, job_id: 'str') -> 'JobResult | None'
```

Load the aggregate result when complete.

### plural.execution.JobStore.write_sync_state

```python
write_sync_state(self, job_id: 'str', state: 'Mapping[str, Any]') -> 'Path'
```

Persist replay-safe hosted upload metadata without credentials.

### plural.execution.JobStore.read_sync_state

```python
read_sync_state(self, job_id: 'str') -> 'dict[str, Any] | None'
```

Read hosted upload metadata when a prior sync was registered.

## plural.Environment

Apps the Agent acts in, with one Runtime, policy, and set of limits.

```text
An Environment owns the episode: ``reset`` and ``step``, the table of
actions every App offers, and the rule that the Agent only ever sees an
action's observation. Most Environments need no subclass::

    environment = Environment(apps=[Wordle()], runtime=Runtime.docker())

Subclass it only when Apps affect one another. Override :meth:`on_step`
to react after any App's action, or :meth:`terminated` to end the episode
from the state of several Apps.
```

```python
plural.Environment(*, apps: 'Iterable[App[Any]]' = (), runtime: 'EnvironmentRuntime | Mapping[str, Any] | None' = None, name: 'str | None' = None, version: 'str | None' = None, description: 'str | None' = None, overview: 'str | None' = None, readme: 'str | None' = None, resources: 'Iterable[EnvironmentResource]' = (), guardrails: 'Iterable[Guardrail]' = (), harness_policy: 'HarnessPolicy | None' = None, limits: 'ExecutionLimits | None' = None, party: 'Party | int | Mapping[str, int] | None' = None, metadata: 'dict[str, Any] | None' = None, source: 'str | Path | None' = None) -> 'None'
```

### plural.Environment.on_step

```python
on_step(self, call: 'ActionCall', result: 'Any', apps: 'Mapping[str, Any]') -> 'None'
```

React after any App's action, for effects that span Apps.

```text
``apps`` maps each App's name to a handle with ``call(action, **args)``,
``snapshot()``, and ``state``. An effect here is not an Agent action and
is not shown to the Agent. Apps never call each other directly.

Rewards are not given here: they depend on the Task, so they come from
the ``reward`` hook of a Task's Verifier.
```

### plural.Environment.terminated

```python
terminated(self) -> 'bool'
```

Return whether the episode is over. Default: any App says it is.

### plural.Environment.truncated

```python
truncated(self) -> 'bool'
```

Return whether the episode was cut short. Default: any App says so.

### plural.Environment.reset

```python
reset(self, *, initial_state: 'Mapping[str, Any] | None' = None, info: 'Any' = None, seed: 'int | None' = None, verifiers: 'Sequence[Any]' = ()) -> 'tuple[Any, dict[str, Any]]'
```

Start an episode in this process.

```text
``initial_state`` maps each App's name to its starting state; with one
App it may be that App's state directly. ``verifiers`` gives each
:meth:`step` its reward: Verifiers with a ``reward`` hook, or functions
of one :class:`~plural.Step`.

Returns:
    The opening observation and reset information.
```

### plural.Environment.step

```python
step(self, action: 'str | Mapping[str, Any] | None' = None, /, **kwargs: 'Any') -> 'tuple[Any, float, bool, bool, dict[str, Any]]'
```

Apply one Agent action in this process.

```text
``action`` is an exposed action name with keyword arguments, or a
mapping with ``name`` and the arguments. With exactly one action the
name may be omitted.

Returns:
    Observation, reward, terminated, truncated, and step information.
```

### plural.Environment.snapshot

```python
snapshot(self) -> 'dict[str, Any]'
```

Return each App's state, as a Verifier receives it after the episode.

### plural.Environment.close

```python
close(self) -> 'None'
```

End the in-process episode and release every App's connections.

## plural.action

Mark an :class:`~plural.apps.App` method as an action the Agent can take.

```text
Args:
    fn: Method to register (decorator usage).
    name: Optional explicit action name. Defaults to the method name.
    read_only: The action never changes state. Verifiers may call only
        read-only actions after the episode.
    timeout_seconds: How long one call may run.

Returns:
    The original method (decorator) or a decorator.
```

```python
plural.action(fn: 'Callable[..., Any] | None' = None, *, name: 'str | None' = None, read_only: 'bool' = False, timeout_seconds: 'float' = 30) -> 'Any'
```

## plural.DeterministicVerifier

Code that verifies an episode: it scores the end, rewards actions, or both.

```text
``check`` scores the finished episode; that score is what Tasks and
Benchmarks rank on. It is a function of the :class:`Episode`, a
``{"python": "verify.py:check"}`` reference, or a command argv.

``reward`` rewards each action while the episode runs. It is a function of
one :class:`Step`, or a ``{"python": "verify.py:reward"}`` reference, and
runs in the Runtime beside the Apps, so it can read every App. What it
returns goes to the Trial's reward ledger. Rewards reach the score only
when ``check`` is :func:`total_reward`.

``hindsight`` credits the finished trajectory as a whole: a function of a
:class:`~plural.rewards.HindsightTrial` that returns
:class:`~plural.rewards.Credit` values, or a ``{"python":
"verify.py:efficiency"}`` reference. It runs after the score, and can also
run later on stored Trials with ``plural verifier apply``.
```

### plural.DeterministicVerifier.bind_source

```python
bind_source(self, digest: 'str', directory: 'Path | None' = None) -> 'None'
```

Fingerprint callable hooks by the package that ships them.

### plural.DeterministicVerifier.bind_source_digest

```python
bind_source_digest(self, digest: 'str') -> 'None'
```

Fingerprint callable hooks by the package that ships them.

### plural.DeterministicVerifier.invoke

```python
invoke(self, episode: 'Episode') -> 'VerifierOutput'
```

Run ``check`` in-process on the finished Episode.

```text
Returns:
    A validated VerifierOutput.
```

### plural.DeterministicVerifier.model_post_init

```python
model_post_init(self: 'BaseModel', context: 'Any', /) -> 'None'
```

This function is meant to behave like a BaseModel method to initialize private attributes.

```text
It takes context as an argument since that's what pydantic-core passes when calling it.

Args:
    self: The BaseModel instance.
    context: The context.
```

## plural.Step

One action the Agent took, as a Verifier's ``reward`` hook sees it.

```text
``observation`` is what the Agent saw back; ``error`` is set instead when
the action rejected its input. ``previous_state`` and ``current_state``
are the acting App's snapshots around the action, or ``None`` when it does
not snapshot on each step. ``apps`` reads any App, by name: ``state`` for
a Python App, ``snapshot()``, and ``query(action, **arguments)`` for a
read-only action. Nothing here reaches the Agent.

When several Agents share the episode, ``seat`` is the one that acted and
``seats`` lists them all. A number a ``reward`` hook returns credits the
acting seat; a mapping of seat to number credits each seat named, as in a
zero-sum game.
```

```python
plural.Step(task: 'StepTask', turn: 'int', app: 'str', action: 'str', arguments: 'Mapping[str, Any]', observation: 'Any' = None, error: 'str | None' = None, previous_state: 'Any' = None, current_state: 'Any' = None, apps: 'Mapping[str, Any]' = <factory>, seat: 'str | None' = None, seats: 'tuple[str, ...]' = ()) -> None
```

## plural.environments.types.Observation

What the agent can observe after an action.

```text
This is the only Environment surface sent to the Agent. Internal State is
never copied here automatically.

Subclass this with typed fields. The JSON Schema of the subclass is the
observation contract hosted with the environment. Implement :meth:`render`
when the prompt should not be a raw dump of the fields.

Attributes:
    text: Default rendered view. Structured subclasses may ignore this.
    metadata: Extra visible fields that do not need a typed attribute.
```

### plural.environments.types.Observation.render

```python
render(self) -> 'str'
```

Return the string the policy sees in the conversation.

```text
Returns:
    ``text``, or a subclass-specific prompt string.
```

## plural.environments.types.State

Persistent internal Environment state for the episode.

```text
State is never sent to the Agent. Only :class:`Observation` is visible.
Verifiers receive the final State on :class:`~plural.verifiers.Episode`.

Mark a field with :func:`initial` when a Task should supply it. Unmarked
fields are episode progress and cannot be set as ``initial_state``.

Attributes:
    seed: Optional deterministic seed a Task may set.
    metadata: Extra internal fields that do not need a typed attribute.
```

## plural.environments.types.as_text

Render an observation or fallback value as conversation text.

```text
Args:
    value: Observation, string, or dumpable object.

Returns:
    Text for a user message.
```

```python
plural.environments.types.as_text(value: 'Any') -> 'str'
```

## plural.environments.types.initial

Mark a State field as a value a Task may set before the episode starts.

```text
Episode progress, such as whether the case is solved or which guesses have
been made, stays a normal field. The Environment owns those values.
``State.seed`` is settable. ``State.metadata`` is not.

Constraints are requirements on the value a Task saves. For example,
``min_length=5``, ``max_length=5``, and ``pattern=r"^[a-z]{5}$"`` require
a five-letter word. They are stored on the field's JSON Schema.

Args:
    default: Value used when the Task leaves the field blank.
    default_factory: Factory used when the default is mutable.
    description: Shown next to the field when a Task sets initial state.
    **constraints: Limits such as ``min_length``, ``max_length``,
        ``pattern``, ``minimum``, ``maximum``, or ``enum``.

Returns:
    A Pydantic field whose JSON Schema includes ``x-plural-initial``.
```

```python
plural.environments.types.initial(default: 'Any' = Ellipsis, *, default_factory: 'Any' = None, description: 'str | None' = None, **constraints: 'Any') -> 'Any'
```

## plural.environments.types.is_empty_observation

Return whether ``value`` has nothing for the policy to read.

```text
Args:
    value: Observation or fallback payload.

Returns:
    ``True`` when there is no rendered text.
```

```python
plural.environments.types.is_empty_observation(value: 'Any') -> 'bool'
```

## plural.environments.types.serialize_observation

Dump an observation onto a decision (dict if it is a model).

```text
Args:
    value: Observation or other payload.

Returns:
    A JSON-ready value for ``Turn.observation``.
```

```python
plural.environments.types.serialize_observation(value: 'Any') -> 'Any'
```

## plural.Harness

Base class for an Agent interaction loop.

```text
Subclasses implement :meth:`run`. Plural discovers and hashes the Python
class directory, invokes ``run`` in the Environment Runtime, and emits the
standard result, trajectory, and log artifacts.
```

### plural.Harness.model_post_init

```python
model_post_init(self, context: 'Any', /) -> 'None'
```

Bind the subclass source immediately after validation.

### plural.Harness.run

```python
run(self, task: 'HarnessTask', agent: 'HarnessAgent', environment: 'HarnessEnvironment') -> 'HarnessResult | str | dict[str, Any] | Any'
```

Run one Agent against one Task and Environment.

## plural.external.config.AgentConfig

The whole of ``plural-agent.yaml``.

### plural.external.config.AgentConfig.load

```python
load(path: 'str | Path | None' = None, *, environ: 'Mapping[str, str] | None' = None) -> 'AgentConfig'
```

Read the config, then apply ``PLURAL_TRACE_*`` overrides.

```text
Args:
    path: The file. Defaults to ``PLURAL_AGENT_CONFIG``, then
        ``plural-agent.yaml`` in the working directory.
    environ: Environment to read; defaults to ``os.environ``.

Returns:
    The config.

Raises:
    ConfigurationError: When the file is missing or invalid.
```

### plural.external.config.AgentConfig.with_environment

```python
with_environment(self, environ: 'Mapping[str, str]') -> 'AgentConfig'
```

Apply ``PLURAL_TRACE_*`` and ``PLURAL_AGENT_VERSION`` overrides.

```text
Returns:
    A copy with the overrides applied.

Raises:
    ConfigurationError: When an override has the wrong form.
```

### plural.external.config.AgentConfig.studio

```python
studio(self, environ: 'Mapping[str, str] | None' = None) -> 'Studio'
```

The Plural API, with the key in ``plural.api_key``.

```text
Returns:
    The client.

Raises:
    ConfigurationError: When that environment variable is not set.
```

## plural.external.config.Capture

Which optional fields a trace holds. Turn off what must never leave the service.

## plural.external.client.Episode

One episode, as the agent works it.

```text
Every call goes to the Job that started it, with the episode's own token.
Pass ``verify`` (a CA bundle path, or ``False`` for a self-signed test
certificate) when the Job serves HTTPS with a private certificate.
```

```python
plural.external.client.Episode(start: 'EpisodeStart', *, verify: 'str | bool' = True, timeout: 'float' = 120.0) -> 'None'
```

### plural.external.client.Episode.tools

```python
tools(self) -> 'list[dict[str, Any]]'
```

Describe the actions for a model.

```text
Returns:
    The actions as OpenAI-compatible tools.
```

### plural.external.client.Episode.act

```python
act(self, action: 'str', /, **arguments: 'Any') -> 'Any'
```

Take one action.

```text
Returns:
    Its observation.
```

### plural.external.client.Episode.read

```python
read(self, path: 'str') -> 'bytes'
```

Read one of :attr:`files`.

```text
Returns:
    Its bytes.
```

### plural.external.client.Episode.trace

```python
trace(self, trajectory: 'Mapping[str, Any]') -> 'None'
```

Report the agent's own trace, as an ATIF document.

```text
The Trial keeps it as self-reported, next to the actions the Job saw.
```

### plural.external.client.Episode.finish

```python
finish(self, response: 'Any') -> 'None'
```

End the episode with the agent's final answer. It can be sent once.

## plural.external.protocol.EpisodeAction

One action the agent may take, as a tool.

## plural.external.client.EpisodeError

The Job refused a request, such as an action after the episode ended.

```python
plural.external.client.EpisodeError
```

## plural.external.protocol.EpisodeStart

The signed request that starts one episode.

## plural.external.protocol.EpisodeTask

What the agent is asked to do.

## plural.external.config.FlushPolicy

When a run's trace is written.

```text
``end`` writes it once, when the run finishes. ``interval`` also writes it
every ``interval_seconds`` while the run is going, and ``steps`` every
``every_steps`` steps, so a long run can be watched live. Each write
replaces the last until the run finishes.
```

### plural.external.config.FlushPolicy.parse

```python
parse(value: 'FlushPolicy | str | Mapping[str, Any]') -> 'FlushPolicy'
```

Read a policy from ``end``, ``interval:5``, ``steps:10``, or a mapping.

```text
Returns:
    The policy.

Raises:
    ConfigurationError: When the value names no policy.
```

## plural.external.client.Ping

A signed check, from ``plural agent test``, that the agent is reachable.

## plural.external.tracing.Run

One traced run of the agent. Use it as a context manager.

```text
Record what happens with :meth:`user`, :meth:`llm`, :meth:`tool`, and
:meth:`message`, then :meth:`finish` with the answer. Leaving the ``with``
block finishes the run if you did not, as failed when it raised.
```

```python
plural.external.tracing.Run(tracer: 'Tracer', sink: '_Sink | None', *, trace_id: 'str', kind: "Literal['episode', 'production']", flush: 'FlushPolicy', capture: 'Capture', tags: 'Mapping[str, str] | None' = None, metadata: 'Mapping[str, Any] | None' = None, episode: 'Episode | None' = None) -> 'None'
```

### plural.external.tracing.Run.system

```python
system(self, text: 'str') -> 'None'
```

Record the system prompt.

### plural.external.tracing.Run.user

```python
user(self, text: 'str') -> 'None'
```

Record a message to the agent, such as the request it is working on.

### plural.external.tracing.Run.message

```python
message(self, text: 'str') -> 'None'
```

Record something the agent said without a model call.

### plural.external.tracing.Run.llm

```python
llm(self, *, model: 'str | None' = None, messages: 'Sequence[Mapping[str, Any]]' = (), output: 'str | None' = None, tool_calls: 'Sequence[ToolCall | Mapping[str, Any]]' = (), reasoning: 'str | None' = None, usage: 'Mapping[str, Any] | None' = None, latency_ms: 'float | None' = None, error: 'str | None' = None, started_at: 'datetime | None' = None) -> 'None'
```

Record one model call.

```text
Args:
    model: The model that answered.
    messages: What it was sent, in the OpenAI chat format.
    output: The text it returned.
    tool_calls: The tool calls it asked for.
    reasoning: Its reasoning, when it reported any.
    usage: ``prompt_tokens``, ``completion_tokens``, ``cached_tokens``,
        and ``cost_usd``, any of which may be missing.
    latency_ms: How long the call took.
    error: Why it failed, when it did.
    started_at: When it started; defaults to now.
```

### plural.external.tracing.Run.tool

```python
tool(self, name: 'str', arguments: 'Mapping[str, Any] | None' = None, result: 'Any' = None, *, call_id: 'str | None' = None, error: 'str | None' = None, latency_ms: 'float | None' = None, started_at: 'datetime | None' = None) -> 'None'
```

Record one tool call and what it returned.

```text
``call_id`` ties it to the model call that asked for it; without one it
is matched to the latest unanswered call of the same tool.
```

### plural.external.tracing.Run.metadata

```python
metadata(self, **values: 'Any') -> 'None'
```

Attach values to the trace, such as a customer or request id.

### plural.external.tracing.Run.finish

```python
finish(self, answer: 'Any' = None) -> 'None'
```

End the run with the agent's answer, and write its trace.

```text
In a Job this also ends the episode, so call it once, last.
```

### plural.external.tracing.Run.fail

```python
fail(self, error: 'str') -> 'None'
```

End the run as failed. In a Job the episode ends with no answer.

### plural.external.tracing.Run.snapshot

```python
snapshot(self) -> 'tuple[list[_Record], dict[str, Any]]'
```

Read the run so far.

```text
Returns:
    Its records in time order, and its metadata.
```

### plural.external.tracing.Run.atif

```python
atif(self) -> 'dict[str, Any]'
```

Render the trace as a Job keeps it.

```text
Returns:
    The ATIF document.
```

### plural.external.tracing.Run.trace

```python
trace(self) -> 'dict[str, Any]'
```

Render the trace as the Traces page keeps it.

```text
Returns:
    The Plural ``Trace`` payload.
```

## plural.external.protocol.SignatureError

A request whose signature, timestamp, or id does not check out.

```python
plural.external.protocol.SignatureError
```

## plural.external.tracing.ToolCall

A tool call a model asked for.

```python
plural.external.tracing.ToolCall(id: 'str', name: 'str', arguments: 'Mapping[str, Any]' = <factory>) -> None
```

## plural.external.tracing.Tracer

Traces an agent's runs, as ``plural-agent.yaml`` says.

```text
Args:
    config: The agent and tracing config.
    environ: Where the API key and overrides are read; defaults to
        ``os.environ``.
    studio: The Plural API client, for tests. Built from the API key when
        omitted.

Raises:
    ConfigurationError: When production tracing is on and the API key's
        environment variable is not set.
```

```python
plural.external.tracing.Tracer(config: 'AgentConfig', *, environ: 'Mapping[str, str] | None' = None, studio: 'Any' = None) -> 'None'
```

### plural.external.tracing.Tracer.from_config

```python
from_config(path: 'str | None' = None, *, environ: 'Mapping[str, str] | None' = None) -> 'Tracer'
```

A tracer for ``plural-agent.yaml``, or the file ``PLURAL_AGENT_CONFIG`` names.

```text
Returns:
    The tracer.
```

### plural.external.tracing.Tracer.for_agent

```python
for_agent(name: 'str', version: 'str', *, model: 'str' = '', environ: 'Mapping[str, str] | None' = None) -> 'Tracer'
```

A tracer with default settings and no config file.

```text
Returns:
    The tracer.
```

### plural.external.tracing.Tracer.run

```python
run(self, *, input: 'str | None' = None, trace_id: 'str | None' = None, flush: 'FlushPolicy | str | Mapping[str, Any] | None' = None, capture: 'Capture | Mapping[str, bool] | None' = None, tags: 'Mapping[str, str] | None' = None, metadata: 'Mapping[str, Any] | None' = None) -> 'Run'
```

Start a run. Inside a traced episode it is that episode's run.

```text
Args:
    input: The request the agent is working on, recorded as a user message.
    trace_id: The trace's id; a new one when omitted.
    flush: When to write the trace, overriding the config for this run.
    capture: Which optional fields to keep, overriding the config.
    tags: Labels for this run, added to the config's.
    metadata: Values to attach to the trace.

Returns:
    The run; use it as a context manager.
```

### plural.external.tracing.Tracer.episode

```python
episode(self, episode: 'Episode', *, flush: 'FlushPolicy | str | Mapping[str, Any] | None' = None, capture: 'Capture | Mapping[str, bool] | None' = None) -> 'Run'
```

The run for one episode of a Plural Job. Its trace goes to that Job.

```text
The Task's instructions are recorded as the first user message, and
:meth:`Run.finish` also finishes the episode.

Returns:
    The run; use it as a context manager.
```

### plural.external.tracing.Tracer.flush

```python
flush(self, timeout: 'float' = 10.0) -> 'bool'
```

Wait until every pending trace is written.

```text
Returns:
    Whether everything was written within ``timeout`` seconds.
```

## plural.external.tracing.current_run

The run being traced in this context.

```text
Returns:
    The run, or ``None`` outside one.
```

```python
plural.external.tracing.current_run() -> 'Run | None'
```

## plural.external.protocol.new_signing_key

Make a fresh signing key.

```text
Returns:
    32 random bytes, as ``whsec_`` and base64.
```

```python
plural.external.protocol.new_signing_key() -> 'str'
```

## plural.external.client.ping

Send an agent service a signed ping, as a Job checks it before an episode.

```text
Args:
    url: The service's episode URL.
    key: The signing key.
    ca_bundle: A PEM CA file for a private certificate.
    timeout: Seconds to wait.

Returns:
    The status the service answered with.

Raises:
    httpx.HTTPError: When the service could not be reached.
```

```python
plural.external.client.ping(url: 'str', key: 'str', *, ca_bundle: 'str | None' = None, timeout: 'float' = 15) -> 'int'
```

## plural.external.tracing.set_tracer

Use ``value`` wherever no tracer is passed, such as in adapters.

```python
plural.external.tracing.set_tracer(value: 'Tracer | None') -> 'None'
```

## plural.external.protocol.sign

Standard Webhooks headers for ``body``.

```text
Returns:
    ``webhook-id``, ``webhook-timestamp``, and ``webhook-signature``.
```

```python
plural.external.protocol.sign(key: 'bytes', body: 'bytes', *, message_id: 'str', timestamp: 'int | None' = None) -> 'dict[str, str]'
```

## plural.external.protocol.signing_key

The key bytes of a ``whsec_``-prefixed base64 secret, or of a raw one.

```text
Returns:
    The bytes to sign with.

Raises:
    ValueError: When the key is shorter than 32 bytes.
```

```python
plural.external.protocol.signing_key(value: 'str') -> 'bytes'
```

## plural.external.tracing.tracer

The process's tracer: the one :func:`set_tracer` gave, or one for ``plural-agent.yaml``.

```text
Returns:
    The tracer.
```

```python
plural.external.tracing.tracer() -> 'Tracer'
```

## plural.external.protocol.verify

Check a signed request and remember its id.

```text
Returns:
    The request's ``webhook-id``.

Raises:
    SignatureError: When a header is missing, the timestamp is more than
        five minutes off, the id was already seen, or no signature matches.
```

```python
plural.external.protocol.verify(key: 'bytes', body: 'bytes', headers: 'Mapping[str, str]', *, now: 'float | None' = None, seen: '_Seen | None' = <configured default>) -> 'str'
```

## plural.external.client.verify_request

Check that a request came from your Plural Job, and parse it.

```text
Args:
    body: The request's raw bytes, before any JSON parsing.
    headers: Its headers.
    key: The shared signing key. Defaults to ``PLURAL_SIGNING_KEY``.

Returns:
    The episode to start, or a ping to answer with any 2xx.

Raises:
    SignatureError: When the request is not signed with the key, is more
        than five minutes old, was received before, or is not one Plural sends.
```

```python
plural.external.client.verify_request(body: 'bytes', headers: 'Mapping[str, str]', *, key: 'str | None' = None) -> 'EpisodeStart | Ping'
```

## plural.sandbox.SandboxProvider

Async lifecycle provider, separate from environment tool runtimes.

```python
plural.sandbox.SandboxProvider()
```

### plural.sandbox.SandboxProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare controls available in the current installation.

### plural.sandbox.SandboxProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Fail before launch if any requested control is unavailable.

### plural.sandbox.SandboxProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Return dependency, daemon, or credential health.

### plural.sandbox.SandboxProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a fresh sandbox after successful preflight.

### plural.sandbox.SandboxProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Upload validated files beneath a scoped workspace.

### plural.sandbox.SandboxProvider.upload_bundle

```python
upload_bundle(self, handle: 'SandboxHandle', bundle: 'Path', *, root: 'str' = '/workspace') -> 'None'
```

Upload a local directory without following symlinks.

### plural.sandbox.SandboxProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute argv with cwd, env, timeout, stdin, and captured logs.

### plural.sandbox.SandboxProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download exact declared files.

### plural.sandbox.SandboxProvider.download_artifacts

```python
download_artifacts(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace', user: 'str | None' = None) -> 'tuple[DownloadedFile, ...]'
```

Download files a Harness declared, which ``user`` wrote, as regular files only.

### plural.sandbox.SandboxProvider.stop_user_processes

```python
stop_user_processes(self, handle: 'SandboxHandle', users: 'Sequence[str | None]') -> 'None'
```

Kill every process the Harnesses' users still run, once their run has ended.

```text
``None`` names the sandbox's default user. A provider that cannot do
this safely does nothing; the App host refuses actions after the Job's
``finish`` either way.
```

### plural.sandbox.SandboxProvider.isolate_apps

```python
isolate_apps(self, handle: 'SandboxHandle') -> 'AppIsolation'
```

Prepare a separate OS user for the App host, when this sandbox can.

```text
Returns:
    The users to run the App host and the Harness as; no ``app_user``
    when the sandbox cannot separate them.
```

### plural.sandbox.SandboxProvider.open_workspace

```python
open_workspace(self, handle: 'SandboxHandle', isolation: 'AppIsolation', paths: 'Sequence[str]') -> 'None'
```

Let ``isolation.agent_user`` write the Harness's folders, once staging is done.

### plural.sandbox.SandboxProvider.isolate_seats

```python
isolate_seats(self, handle: 'SandboxHandle', seats: 'Sequence[str]') -> 'dict[str, str]'
```

Prepare one OS user for each seat's Harness, when this sandbox can.

```text
Each must differ from the App host's user and from every other seat's,
and must not be able to become another user, so one seat's Harness
cannot read another's files or process.

Returns:
    Seat to user, or empty when the sandbox cannot separate them.
```

### plural.sandbox.SandboxProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Force cancellation of active work.

### plural.sandbox.SandboxProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Idempotently delete the sandbox and scoped data.

## plural.sandbox.SandboxRequirements

Controls required for one sandbox before it may launch.

### plural.sandbox.SandboxRequirements.required_capabilities

```python
required_capabilities(self) -> 'frozenset[SandboxCapability]'
```

Return the controls that must be enforceable.

## plural.sandbox.ProviderRegistry

Resolve built-ins and installed provider plugins lazily.

```python
plural.sandbox.ProviderRegistry() -> 'None'
```

### plural.sandbox.ProviderRegistry.register

```python
register(self, provider: 'SandboxProvider', *, replace: 'bool' = False) -> 'None'
```

Register one concrete provider.

### plural.sandbox.ProviderRegistry.get

```python
get(self, name: 'str') -> 'SandboxProvider'
```

Return a registered provider, loading plugins first.

### plural.sandbox.ProviderRegistry.doctors

```python
doctors(self, *, include_unavailable: 'bool' = False) -> 'tuple[ProviderDoctor, ...]'
```

Return dynamic provider reports in stable name order.

## plural.sandbox.LocalProvider

Run commands in temporary directories without isolation.

```text
This provider intentionally does not advertise network, resource, image, or
read-only-root enforcement. It is suitable only for explicitly trusted local
development workloads.
```

```python
plural.sandbox.LocalProvider(*, base_dir: 'Path | None' = None) -> 'None'
```

### plural.sandbox.LocalProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare local subprocess controls.

### plural.sandbox.LocalProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Report local execution availability without implying isolation.

### plural.sandbox.LocalProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a scoped temporary workspace.

### plural.sandbox.LocalProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Copy files into the temporary workspace.

### plural.sandbox.LocalProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Run an argv-only subprocess and kill it at timeout.

### plural.sandbox.LocalProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Read exact declared regular files.

### plural.sandbox.LocalProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Kill the active subprocess, if any.

### plural.sandbox.LocalProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Kill active work and remove all scoped files.

## plural.sandbox.DockerProvider

Create one locked-down Docker container per execution phase.

```python
plural.sandbox.DockerProvider(*, executable: 'str' = 'docker', default_image: 'str' = 'python:3.12-slim') -> 'None'
```

### plural.sandbox.DockerProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare Docker controls only when the daemon is reachable.

### plural.sandbox.DockerProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Reject provider-specific image forms before launch.

### plural.sandbox.DockerProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Detect the Docker CLI and daemon.

### plural.sandbox.DockerProvider.extend_image

```python
extend_image(self, requirements: 'SandboxRequirements', context: 'Path', key: 'str') -> 'SandboxRequirements'
```

Layer a build context onto the requirements' image, once per base and key.

```text
The context's Dockerfile receives the base image as the ``BASE`` build
argument. The result is tagged by base identity and ``key``, so later
Trials and Jobs reuse it instead of building again.

Returns:
    The requirements, pointing at the extended image.
```

### plural.sandbox.DockerProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create and start a hardened, scoped container.

### plural.sandbox.DockerProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Stream exact files into the writable workspace mount.

### plural.sandbox.DockerProvider.isolate_apps

```python
isolate_apps(self, handle: 'SandboxHandle') -> 'AppIsolation'
```

Run the App host as its own unprivileged user.

```text
The container runs everything else as ``65532``, with every capability
dropped, so the Harness cannot read the App host's ``0700`` folder or
its process.

Returns:
    The App host's user, and the default user for the Harness.
```

### plural.sandbox.DockerProvider.isolate_seats

```python
isolate_seats(self, handle: 'SandboxHandle', seats: 'Sequence[str]') -> 'dict[str, str]'
```

Run each seat's Harness as its own unprivileged user.

```text
Every capability is dropped, so no seat's user can read another's
``0700`` folder or process, or the App host's.

Returns:
    Seat to a numeric user, ``65400`` for the first.
```

### plural.sandbox.DockerProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute argv and capture logs, enforcing a host-side timeout.

### plural.sandbox.DockerProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Stream exact declared paths out and reject non-regular files.

### plural.sandbox.DockerProvider.download_artifacts

```python
download_artifacts(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace', user: 'str | None' = None) -> 'tuple[DownloadedFile, ...]'
```

Read a Harness's files as the user that wrote them, which owns its folder.

```text
No capability is kept, so only a seat's own user can enter its ``0700`` folder.
```

### plural.sandbox.DockerProvider.stop_user_processes

```python
stop_user_processes(self, handle: 'SandboxHandle', users: 'Sequence[str | None]') -> 'None'
```

Kill what each Harness user left running, as that user, since no capability is kept.

```text
``None`` is the container's default user, whose ``sleep`` keeps it alive
as PID 1 and is spared.
```

### plural.sandbox.DockerProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Kill the container to force all active processes to stop.

### plural.sandbox.DockerProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Force-remove the container idempotently.

## plural.sandbox.DaytonaProvider

Execute in Daytona while keeping its SDK an optional import.

```python
plural.sandbox.DaytonaProvider(*, adapter: 'DaytonaClientAdapter | None' = None, environ: 'Mapping[str, str] | None' = None) -> 'None'
```

### plural.sandbox.DaytonaProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare controls implemented by the current Daytona SDK.

### plural.sandbox.DaytonaProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Reject Daytona controls whose SDK mapping is not enforceable.

### plural.sandbox.DaytonaProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Detect SDK and credential presence without exposing values.

### plural.sandbox.DaytonaProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a Daytona sandbox from image, snapshot, or defaults.

### plural.sandbox.DaytonaProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Upload exact in-memory files.

### plural.sandbox.DaytonaProvider.isolate_apps

```python
isolate_apps(self, handle: 'SandboxHandle') -> 'AppIsolation'
```

Create an App host user and an unprivileged Harness user.

```text
Daytona's default user can ``sudo``, so a Harness running as it could
read anything. Here the Harness runs as ``plural-agent``, which cannot,
and the App host as ``plural-apps``.

Returns:
    Both users, or no ``app_user`` when the image has no passwordless
    ``sudo`` or ``useradd``.
```

### plural.sandbox.DaytonaProvider.isolate_seats

```python
isolate_seats(self, handle: 'SandboxHandle', seats: 'Sequence[str]') -> 'dict[str, str]'
```

Create one unprivileged user for each seat's Harness.

```text
Returns:
    Seat to user, or empty when the image has no passwordless ``sudo``
    or ``useradd``.
```

### plural.sandbox.DaytonaProvider.open_workspace

```python
open_workspace(self, handle: 'SandboxHandle', isolation: 'AppIsolation', paths: 'Sequence[str]') -> 'None'
```

Let the Harness user write the staged folders, which the default user owns.

```text
Raises:
    SandboxError: When the folders cannot be opened to it.
```

### plural.sandbox.DaytonaProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute through ``sandbox.process.exec``.

```text
A ``user`` other than ``root`` runs through ``sudo -n -E -u``, which
fails rather than falling back to the default user.
```

### plural.sandbox.DaytonaProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download exact declared files.

### plural.sandbox.DaytonaProvider.download_artifacts

```python
download_artifacts(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace', user: 'str | None' = None) -> 'tuple[DownloadedFile, ...]'
```

Download Harness-declared files, refusing any that is not a regular file inside ``root``.

```text
Daytona's file API reads as the sandbox's default user, which can read
the App host's folder, so a symlink or a path that resolves outside
``root`` is refused first, as the Harness's ``user`` when given, and
the resolved file is what is read.

Raises:
    FileNotFoundError: When a declared path is not a regular file inside ``root``.
```

### plural.sandbox.DaytonaProvider.stop_user_processes

```python
stop_user_processes(self, handle: 'SandboxHandle', users: 'Sequence[str | None]') -> 'None'
```

Kill, as root, what the Harnesses' own users left running.

```text
The default user is skipped: it is the one Daytona runs its own tools as.
```

### plural.sandbox.DaytonaProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Delete the sandbox to force cancellation.

### plural.sandbox.DaytonaProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Idempotently delete the remote sandbox.

## plural.routing.policies.Explicit

Use the request's model (and optional ``models`` fallbacks) as-is.

```text
Multi-host models expand to US endpoints first, then the lab host.

Examples:
    >>> from plural.catalog import ModelCatalog
    >>> from plural.types import ChatRequest, Message
    >>> policy = Explicit()
    >>> req = ChatRequest(
    ...     model="openai/gpt-5.6-luna", messages=[Message(role="user", content="x")]
    ... )
    >>> policy.select(req, [req.model], ModelCatalog())[0].model
    'openai/gpt-5.6-luna'
```

```python
plural.routing.policies.Explicit()
```

### plural.routing.policies.Explicit.select

```python
select(self, request: 'ChatRequest', candidates: 'list[str]', catalog: 'ModelCatalog') -> 'list[ModelRoute]'
```

Return routes in candidate order, expanding multi-host models.

```text
Args:
    request: The chat request.
    candidates: Candidate model ids.
    catalog: Model catalog.

Returns:
    Ordered routes.
```

## plural.routing.policies.Fallback

Alias for :class:`Explicit` emphasizing fallback-chain semantics.

```python
plural.routing.policies.Fallback()
```

## plural.routing.policies.LeastCost

Prefer cheaper models among candidates after the primary.

```text
The primary model remains first; remaining candidates are sorted by
estimated prompt+completion price (using equal token weights). Each
model then expands to its host endpoints (US first).
```

```python
plural.routing.policies.LeastCost()
```

### plural.routing.policies.LeastCost.select

```python
select(self, request: 'ChatRequest', candidates: 'list[str]', catalog: 'ModelCatalog') -> 'list[ModelRoute]'
```

Return the primary route first, then cheapest fallbacks.

```text
Args:
    request: The chat request.
    candidates: Candidate model ids.
    catalog: Model catalog.

Returns:
    Ordered routes.
```

## plural.routing.policies.LowestLatency

Prefer providers historically associated with low latency.

```text
Uses a static heuristic table for v1; a learned policy can replace this
later via the same :class:`RoutingPolicy` protocol.
```

```python
plural.routing.policies.LowestLatency()
```

### plural.routing.policies.LowestLatency.select

```python
select(self, request: 'ChatRequest', candidates: 'list[str]', catalog: 'ModelCatalog') -> 'list[ModelRoute]'
```

Return routes ordered by heuristic provider latency rank.

```text
Args:
    request: The chat request.
    candidates: Candidate model ids.
    catalog: Model catalog.

Returns:
    Ordered routes.
```

## plural.routing.policies.ModelRoute

A single candidate route selected by a policy.

```text
Attributes:
    model: Model id in ``author/slug`` form.
    provider: Host slug that should serve the request.
    region: Host region. Carried through so billing can charge the region's
        own rate rather than whichever one happens to be listed first.
    upstream_id: Model id the host expects, when different from ``model``.
    priority: Lower values are tried first.
```

## plural.routing.policies.RoutingPolicy

Select an ordered list of model routes for a request.

```python
plural.routing.policies.RoutingPolicy(*args, **kwargs)
```

### plural.routing.policies.RoutingPolicy.select

```python
select(self, request: 'ChatRequest', candidates: 'list[str]', catalog: 'ModelCatalog') -> 'list[ModelRoute]'
```

Return ordered routes to try.

```text
Args:
    request: The chat request.
    candidates: Candidate model ids (primary + fallbacks).
    catalog: Model catalog used for cost/latency metadata.

Returns:
    Ordered list of :class:`ModelRoute` values.
```

## plural.routing.policies.expand_models

Expand each candidate model into its host routes, keeping model order.

```text
Returns:
    Every host route for the candidates, ordered by model then endpoint priority.
```

```python
plural.routing.policies.expand_models(model_ids: 'list[str]', catalog: 'ModelCatalog') -> 'list[ModelRoute]'
```

## plural.routing.policies.routes_for_model

Expand a catalog model into host routes (US hosts first).

```text
Args:
    model_id: Canonical ``author/slug`` id.
    catalog: Model catalog.
    priority_base: Starting priority for this model's endpoints.

Returns:
    Ordered host routes for the model.
```

```python
plural.routing.policies.routes_for_model(model_id: 'str', catalog: 'ModelCatalog', *, priority_base: 'int' = 0) -> 'list[ModelRoute]'
```

## plural.environments.export.hf.to_huggingface_records

Convert a dataset to a list of HF-friendly dictionaries.

```text
Args:
    dataset: Source dataset.

Returns:
    List of flat-ish records suitable for ``datasets.Dataset.from_list``.
```

```python
plural.environments.export.hf.to_huggingface_records(dataset: 'TraceDataset') -> 'list[dict[str, Any]]'
```

## plural.environments.export.verifiers.to_verifiers_trace

Convert an plural trace to a simplified verifiers-compatible dict.

```text
Prefers :class:`~plural.tracing.schema.Turn` steps (observation,
actions, observations). Falls back to flat ``llm`` / ``action`` steps.

Args:
    trace: Source trace.

Returns:
    A dictionary with ``messages``, ``reward``, ``task``, and ``extra``.
```

```python
plural.environments.export.verifiers.to_verifiers_trace(trace: 'Trace') -> 'dict[str, Any]'
```

## plural.ModelCatalog

In-memory model catalog loaded from a bundled JSON snapshot.

```text
Args:
    path: Optional path to a catalog JSON file. Defaults to the bundled snapshot.

Examples:
    >>> catalog = ModelCatalog()
    >>> len(catalog.models()) > 0
    True
```

```python
plural.ModelCatalog(path: 'str | Path | None' = None, *, entries: 'Iterable[ModelSpec | Mapping[str, Any]]' = (), include_bundled: 'bool' = True) -> 'None'
```

### plural.ModelCatalog.add

```python
add(self, *entries: 'ModelSpec | Mapping[str, Any]') -> 'ModelCatalog'
```

Add explicit project entries and return this effective catalog.

```text
Project entries replace bundled entries with the same stable model ID.
The catalog is intentionally passed explicitly; no process-global
registration is performed.

Returns:
    This catalog, for convenient construction.
```

### plural.ModelCatalog.with_entries

```python
with_entries(self, *entries: 'ModelSpec | Mapping[str, Any]') -> 'ModelCatalog'
```

Return an independent catalog extended with project entries.

```text
Returns:
    A copy containing the effective bundled and project entries.
```

### plural.ModelCatalog.load_bundled

```python
load_bundled(self) -> 'None'
```

Load the package-bundled catalog snapshot.

### plural.ModelCatalog.load_path

```python
load_path(self, path: 'Path') -> 'None'
```

Load a catalog from a filesystem path.

```text
Args:
    path: Path to a JSON catalog file.
```

### plural.ModelCatalog.models

```python
models(self) -> 'list[ModelSpec]'
```

Return all model specs.

```text
Returns:
    A list of :class:`ModelSpec` entries.
```

### plural.ModelCatalog.ids

```python
ids(self) -> 'list[str]'
```

Return registered model IDs in catalog order.

### plural.ModelCatalog.suggest

```python
suggest(self, model_id: 'str', *, limit: 'int' = 5) -> 'list[str]'
```

Return nearby catalog IDs for an unknown model.

```text
Args:
    model_id: The ID the caller tried to use.
    limit: Maximum suggestions.

Returns:
    Close catalog IDs, or a short prefix of the catalog.
```

### plural.ModelCatalog.get

```python
get(self, model_id: 'str') -> 'ModelSpec | None'
```

Look up a model by id.

```text
Args:
    model_id: Model id in ``author/slug`` form.

Returns:
    The matching :class:`ModelSpec`, or ``None``.
```

### plural.ModelCatalog.require

```python
require(self, model_id: 'str') -> 'ModelSpec'
```

Look up a model by id or raise.

```text
Args:
    model_id: Model id in ``author/slug`` form.

Returns:
    The matching :class:`ModelSpec`.

Raises:
    NotFoundError: If the model is not in the catalog.
```

### plural.ModelCatalog.refresh_from_openrouter

```python
refresh_from_openrouter(self, url: 'str' = 'https://openrouter.ai/api/v1/models') -> 'int'
```

Refresh the in-memory catalog from OpenRouter's public models API.

```text
Args:
    url: Models endpoint URL.

Returns:
    Number of models loaded.

Note:
    This performs a network request and is intended for maintainer
    tooling, not runtime hot paths.
```

### plural.ModelCatalog.write_snapshot

```python
write_snapshot(self, path: 'Path') -> 'None'
```

Write the current catalog to a JSON snapshot file.

```text
Args:
    path: Destination path.
```

## plural.catalog.ModelSpec

A catalog entry for a model.

```text
Attributes:
    id: Model id in ``author/slug`` form.
    name: Human-readable display name.
    context_length: Maximum context window in tokens.
    pricing: Default per-token pricing (US-first host, then first endpoint).
    architecture: Modality metadata.
    supported_parameters: Request parameters the model accepts.
    endpoints: Inference hosts. Empty means the author is the only host.
    description: What the model is for, shown on its model card.
    created: Release date, ``YYYY-MM-DD``.
    knowledge_cutoff: Training data cutoff, ``YYYY-MM`` or ``YYYY-MM-DD``.
    max_output_tokens: Largest completion the model produces.
    open_weights: Whether the weights are published.
    license: License of published weights, such as ``apache-2.0``.
    links: Named reference URLs, such as ``homepage`` or ``model_card``.
    provider: Derived provider slug (author segment of ``id``).
```

### plural.catalog.ModelSpec.ordered_endpoints

```python
ordered_endpoints(self) -> 'list[ModelEndpoint]'
```

Return endpoints with US hosts first (Fireworks, then Baseten).

```text
Returns:
    Ordered endpoints, or a single implicit author host when none are listed.
```

### plural.catalog.ModelSpec.host_providers

```python
host_providers(self) -> 'list[str]'
```

Return host slugs that can serve this model.

### plural.catalog.ModelSpec.pricing_for

```python
pricing_for(self, provider: 'str | None' = None, region: 'str | None' = None) -> 'ModelPricing | None'
```

Return pricing for a host, or the default US-first price.

```text
Region matters because the same provider charges different rates in
different regions: Azure EU lists above Azure US for identical models.
When a region is given it must match, so a miss falls back to the default
rather than billing a cheaper region's rate for a pricier one.

Args:
    provider: Host slug. ``None`` uses the default endpoint.
    region: Host region. ``None`` matches the first endpoint for the provider.

Returns:
    Per-token pricing, or ``None``.
```

## plural.catalog.estimate_cost

Estimate USD cost for a usage record against a model spec.

```text
Args:
    usage: Token usage.
    spec: Model catalog entry, or ``None``.
    provider: Optional host slug; bills at that host's pass-through price.
    region: Optional host region, for providers whose rates vary by region.

Returns:
    Estimated USD cost, or ``None`` if pricing is unavailable.

Examples:
    >>> from plural.types import Usage
    >>> spec = ModelSpec(
    ...     id="openai/gpt-5.6-luna",
    ...     pricing=ModelPricing(prompt=0.0000002, completion=0.0000012),
    ... )
    >>> round(estimate_cost(Usage.from_counts(1_000_000, 0), spec) or 0, 2)
    0.2
```

```python
plural.catalog.estimate_cost(usage: 'Usage', spec: 'ModelSpec | None', *, provider: 'str | None' = None, region: 'str | None' = None) -> 'float | None'
```

## plural.catalog.sync.CatalogDiff

What the sync found relative to the bundled catalog.

```text
Attributes:
    candidates: Upstream models we could carry but do not. Reported only; the
        catalog is curated, so adding one is an explicit choice.
    removed: Catalog ids the upstream reference no longer lists.
    repriced: Rates that moved upstream.
    unpriced: Catalog ids with no usable price, which stay hidden.
    unconfirmed: Catalog ids no configured provider currently lists.
    providers_checked: Provider slugs whose listings were fetched.
    discounted: Model ids where upstream is running a promotion. Recorded so a
        reviewer can see we deliberately kept the list price.
    retiered: Prompt-length rates that differ from the catalog's.
    new_hosts: Hosts upstream offers for models we carry but we do not list.
```

```python
plural.catalog.sync.CatalogDiff(candidates: 'list[UpstreamModel]' = <factory>, removed: 'list[str]' = <factory>, repriced: 'list[PriceChange]' = <factory>, unpriced: 'list[str]' = <factory>, unconfirmed: 'list[str]' = <factory>, providers_checked: 'list[str]' = <factory>, discounted: 'list[str]' = <factory>, retiered: 'list[TierChange]' = <factory>, new_hosts: 'list[tuple[str, str]]' = <factory>) -> None
```

## plural.catalog.sync.PriceChange

A per-token price that moved upstream.

```text
Attributes:
    id: Model id.
    field_name: Which rate changed (``prompt`` or ``completion``).
    old: Price currently in the catalog.
    new: Undiscounted list price reported upstream.
    provider: Host the rate belongs to, or ``None`` for the model default.
    region: Host region, or ``None`` for the model default.
```

```python
plural.catalog.sync.PriceChange(id: 'str', field_name: 'str', old: 'float | None', new: 'float | None', provider: 'str | None' = None, region: 'str | None' = None) -> None
```

## plural.catalog.sync.TierChange

Prompt-length rates that differ from what the catalog records.

```text
Attributes:
    id: Model id.
    tiers: Tiers reported upstream, at list prices.
    provider: Host the tiers belong to, or ``None`` for the model default.
    region: Host region, or ``None`` for the model default.
```

```python
plural.catalog.sync.TierChange(id: 'str', tiers: 'tuple[UpstreamTier, ...]', provider: 'str | None' = None, region: 'str | None' = None) -> None
```

### plural.catalog.sync.TierChange.describe

```python
describe(self) -> 'str'
```

Summarize the thresholds and rates for a review body.

```text
Returns:
    A human-readable description, or a note that tiers were dropped.
```

## plural.catalog.sync.UpstreamEndpoint

A single inference host as OpenRouter describes it.

```text
Attributes:
    provider: Catalog provider slug, or ``None`` when the tag is unmapped.
    region: Coarse region key.
    tier: Service tier. Only ``standard`` is used for catalog pricing.
    upstream_id: Model id the host expects.
    prompt: Undiscounted USD per prompt token.
    completion: Undiscounted USD per completion token.
    discount: Promotional fraction OpenRouter applied, if any.
    tiers: Prompt-length rates, ordered by threshold.
    tag: Raw upstream tag, kept for reporting unmapped hosts.
    cache_read: Undiscounted USD per prompt token read from the cache.
    cache_write: Undiscounted USD per prompt token written to the cache.
```

```python
plural.catalog.sync.UpstreamEndpoint(provider: 'str | None', region: 'str', tier: 'str', upstream_id: 'str', prompt: 'float | None', completion: 'float | None', discount: 'float | None', tiers: 'tuple[UpstreamTier, ...]', tag: 'str', cache_read: 'float | None' = None, cache_write: 'float | None' = None) -> None
```

## plural.catalog.sync.UpstreamModel

A model as described by the upstream reference catalog.

```text
Attributes:
    id: Canonical ``author/slug`` id.
    name: Display name.
    context_length: Context window in tokens.
    prompt: USD per prompt token, or ``None`` when unknown.
    completion: USD per completion token, or ``None`` when unknown.
    modality: High-level modality string.
    input_modalities: Accepted input modalities.
    output_modalities: Produced output modalities.
    supported_parameters: Request parameters the model accepts.
    description: Upstream description, a starting point for the model card.
    created: Upstream release date, ``YYYY-MM-DD``.
    max_output_tokens: Largest completion upstream reports.
```

```python
plural.catalog.sync.UpstreamModel(id: 'str', name: 'str | None' = None, context_length: 'int | None' = None, prompt: 'float | None' = None, completion: 'float | None' = None, modality: 'str | None' = None, input_modalities: 'tuple[str, ...]' = ('text',), output_modalities: 'tuple[str, ...]' = ('text',), supported_parameters: 'tuple[str, ...]' = (), description: 'str | None' = None, created: 'str | None' = None, max_output_tokens: 'int | None' = None) -> None
```

## plural.catalog.sync.UpstreamTier

A long-prompt rate that supersedes the base rate.

```text
Attributes:
    min_prompt_tokens: Prompt size at which the rate takes over.
    prompt: Undiscounted USD per prompt token.
    completion: Undiscounted USD per completion token.
```

```python
plural.catalog.sync.UpstreamTier(min_prompt_tokens: 'int', prompt: 'float', completion: 'float') -> None
```

## plural.catalog.sync.apply_diff

Produce an updated catalog document.

```text
Price drift is applied automatically because a stale rate bills the wrong
amount on every request. Additions and removals are deliberate: the catalog
is curated, and dropping a model breaks callers.

Args:
    current: Decoded ``models.json``.
    upstream: Upstream models keyed by id.
    changes: Differences from :func:`diff_catalog`.
    add: Model ids to bring into the catalog.
    add_hosts: Provider slugs whose regional endpoints should be added to
        every carried model that upstream offers them for.
    endpoints_by_model: Per-model host records, required by ``add_hosts``.
    now: Timestamp to stamp the document with.

Returns:
    A new catalog document ready to write.
```

```python
plural.catalog.sync.apply_diff(current: 'Mapping[str, Any]', upstream: 'Mapping[str, UpstreamModel]', changes: 'CatalogDiff', *, add: 'Iterable[str]' = (), add_hosts: 'Iterable[str]' = (), endpoints_by_model: 'Mapping[str, list[UpstreamEndpoint]] | None' = None, now: 'datetime | None' = None) -> 'dict[str, Any]'
```

## plural.catalog.sync.collect_served_slugs

Gather the slugs every configured provider reports.

```text
Args:
    client: HTTP client to use.
    env: Environment mapping to read keys from. Defaults to ``os.environ``.

Returns:
    A pair of (normalized slugs, provider slugs that answered).
```

```python
plural.catalog.sync.collect_served_slugs(client: 'httpx.Client', env: 'Mapping[str, str] | None' = None) -> 'tuple[set[str], list[str]]'
```

## plural.catalog.sync.diff_catalog

Compare the bundled catalog against upstream.

```text
Args:
    current: Decoded ``models.json``.
    upstream: Upstream models keyed by id.
    served: Normalized slugs configured providers report. Empty means
        availability could not be confirmed, so nothing is filtered on it.
    providers_checked: Provider slugs that answered.
    endpoints_by_model: Per-model host records. Models absent from this
        mapping are skipped for repricing rather than assumed unchanged, so a
        failed lookup never looks like a price drop.

Returns:
    The differences a human needs to review.
```

```python
plural.catalog.sync.diff_catalog(current: 'Mapping[str, Any]', upstream: 'Mapping[str, UpstreamModel]', served: 'set[str]', *, providers_checked: 'Iterable[str]' = (), endpoints_by_model: 'Mapping[str, list[UpstreamEndpoint]] | None' = None) -> 'CatalogDiff'
```

## plural.catalog.sync.fetch_endpoints

Fetch the hosts OpenRouter lists for one model.

```text
Args:
    client: HTTP client to use.
    model_id: Canonical ``author/slug`` id.

Returns:
    Host records, empty when the model is unknown upstream.
```

```python
plural.catalog.sync.fetch_endpoints(client: 'httpx.Client', model_id: 'str') -> 'list[UpstreamEndpoint]'
```

## plural.catalog.sync.fetch_openrouter

Fetch the public OpenRouter catalog.

```text
Args:
    client: HTTP client to use.

Returns:
    Upstream models keyed by canonical id.
```

```python
plural.catalog.sync.fetch_openrouter(client: 'httpx.Client') -> 'dict[str, UpstreamModel]'
```

## plural.catalog.sync.fetch_provider_models

List the model slugs a provider currently serves.

```text
Args:
    client: HTTP client to use.
    slug: Provider slug.
    api_key: Provider API key.

Returns:
    Normalized slugs the provider reports, empty when the call fails.
```

```python
plural.catalog.sync.fetch_provider_models(client: 'httpx.Client', slug: 'str', api_key: 'str') -> 'set[str]'
```

## plural.catalog.sync.is_region

Decide whether an endpoint tag qualifier names a region.

```text
Args:
    qualifier: A segment after the provider in an endpoint tag.

Returns:
    ``True`` when the segment looks like a region rather than a variant.

Examples:
    >>> is_region("us-east-1"), is_region("global"), is_region("fp8")
    (True, True, False)
```

```python
plural.catalog.sync.is_region(qualifier: 'str') -> 'bool'
```

## plural.catalog.sync.load_catalog

Read the bundled catalog document.

```text
Args:
    path: Location of ``models.json``.

Returns:
    The decoded document.
```

```python
plural.catalog.sync.load_catalog(path: 'Path' = PosixPath('<default>')) -> 'dict[str, Any]'
```

## plural.catalog.sync.main

Run the catalog sync.

```text
Args:
    argv: Command-line arguments.

Returns:
    Process exit code. ``1`` under ``--check`` when the catalog is stale.
```

```python
plural.catalog.sync.main(argv: 'list[str] | None' = None) -> 'int'
```

## plural.catalog.sync.normalize_model_id

Reduce a vendor model id to a comparable slug.

```text
Vendors name the same weights differently: Fireworks serves
``accounts/fireworks/models/llama-v3p1-70b`` where OpenRouter says
``meta/llama-3.1-70b``. Comparing bare trailing slugs catches most pairs.

Args:
    model_id: Provider or catalog model id.

Returns:
    A lowercase slug with author and account path segments removed.

Examples:
    >>> normalize_model_id("accounts/fireworks/models/Llama-3.1-70B")
    'llama-3.1-70b'
    >>> normalize_model_id("openai/gpt-4o-mini")
    'gpt-4o-mini'
```

```python
plural.catalog.sync.normalize_model_id(model_id: 'str') -> 'str'
```

## plural.catalog.sync.order_spec_keys

Put catalog entry keys in a stable order.

```text
A price added to an entry that had none would otherwise land at the end,
which makes the review diff harder to read than it needs to be.

Args:
    spec: A single catalog entry.

Returns:
    The same entry with known keys first, in canonical order.

Examples:
    >>> list(order_spec_keys({"endpoints": [], "id": "a/b"}))
    ['id', 'endpoints']
```

```python
plural.catalog.sync.order_spec_keys(spec: 'Mapping[str, Any]') -> 'dict[str, Any]'
```

## plural.catalog.sync.parse_endpoint_tag

Split an OpenRouter endpoint tag into provider, region, and service tier.

```text
A qualifier that is neither a known service tier nor region-shaped is a
deployment variant: quantizations such as ``fp8`` and ``fp4``, or program
names such as ``claude-on-aws``. Those are returned as the tier so they are
excluded from pricing, since a 4-bit deployment is not the same product as
the full-precision model and must not set its rate.

Args:
    tag: Endpoint tag such as ``azure/eu`` or ``openai/flex``.

Returns:
    A triple of (provider slug or ``None`` when unmapped, region, tier).

Examples:
    >>> parse_endpoint_tag("amazon-bedrock/us-east-1")
    ('bedrock', 'us', 'standard')
    >>> parse_endpoint_tag("openai/flex")
    ('openai', 'us', 'flex')
    >>> parse_endpoint_tag("baseten/fp4")
    ('baseten', 'us', 'fp4')
```

```python
plural.catalog.sync.parse_endpoint_tag(tag: 'str') -> 'tuple[str | None, str, str]'
```

## plural.catalog.sync.parse_endpoints

Convert an OpenRouter ``/endpoints`` payload into host records.

```text
Args:
    payload: Decoded ``/api/v1/models/{id}/endpoints`` response.

Returns:
    Every host described upstream, with list rather than promotional prices.
```

```python
plural.catalog.sync.parse_endpoints(payload: 'Mapping[str, Any]') -> 'list[UpstreamEndpoint]'
```

## plural.catalog.sync.parse_openrouter

Convert an OpenRouter models payload into upstream records.

```text
Args:
    payload: Decoded ``/api/v1/models`` response.

Returns:
    Upstream models keyed by canonical id.
```

```python
plural.catalog.sync.parse_openrouter(payload: 'Mapping[str, Any]') -> 'dict[str, UpstreamModel]'
```

## plural.catalog.sync.parse_tiers

Read prompt-length rates from an endpoint's pricing block.

```text
A tier is only usable if both rates are present, since billing one side at the
long-prompt rate and the other at the base rate matches neither.

Args:
    pricing: The endpoint's ``pricing`` mapping.
    discount: Promotional fraction to divide back out.

Returns:
    Tiers ordered by threshold.
```

```python
plural.catalog.sync.parse_tiers(pricing: 'Mapping[str, Any]', discount: 'float | None') -> 'tuple[UpstreamTier, ...]'
```

## plural.catalog.sync.render_report

Render the diff as markdown for a pull request body.

```text
Args:
    changes: Differences from :func:`diff_catalog`.

Returns:
    A markdown summary.
```

```python
plural.catalog.sync.render_report(changes: 'CatalogDiff') -> 'str'
```

## plural.catalog.sync.standard_endpoints

Index priced standard-tier hosts by provider and region.

```text
Args:
    endpoints: Host records for one model.

Returns:
    Mapping of (provider, region) to endpoint, cheapest kept on collision.
```

```python
plural.catalog.sync.standard_endpoints(endpoints: 'Iterable[UpstreamEndpoint]') -> 'dict[tuple[str, str], UpstreamEndpoint]'
```

## plural.catalog.sync.write_catalog

Write the catalog document back to disk.

```text
Args:
    document: Catalog document to serialize.
    path: Location of ``models.json``.
```

```python
plural.catalog.sync.write_catalog(document: 'Mapping[str, Any]', path: 'Path' = PosixPath('<default>')) -> 'None'
```

## plural.catalog.edit.ArchitectureDocument

Modalities, as stored.

## plural.catalog.edit.EditError

A command that cannot be applied.

```python
plural.catalog.edit.EditError
```

## plural.catalog.edit.EndpointDocument

One host that serves the model, at its own price.

## plural.catalog.edit.Issue

A validation finding.

## plural.catalog.edit.ModelCardDocument

One ``models.json`` entry: everything a model card shows.

```text
Unknown keys are rejected so a misspelled field fails validation instead of
silently never reaching the card.
```

## plural.catalog.edit.PricingDocument

Per-token prices in USD, as stored. Strings keep exact decimals.

## plural.catalog.edit.TierDocument

A prompt-length price tier as stored.

## plural.catalog.edit.build_parser

The command-line interface.

```text
Returns:
    The argument parser.
```

```python
plural.catalog.edit.build_parser() -> 'argparse.ArgumentParser'
```

## plural.catalog.edit.complete_sentences

Drop a trailing fragment from a description the upstream list cut short.

```text
Returns:
    The text ending at its last complete sentence.

Examples:
    >>> complete_sentences("Fast model. Good at code, and...")
    'Fast model.'
    >>> complete_sentences("Fast model.")
    'Fast model.'
```

```python
plural.catalog.edit.complete_sentences(text: 'str') -> 'str'
```

## plural.catalog.edit.main

Run one command and print its JSON result.

```text
Returns:
    ``0`` on success, ``1`` when the command failed or validation did.
```

```python
plural.catalog.edit.main(argv: 'list[str] | None' = None) -> 'int'
```

## plural.catalog.edit.match_upstream

Find a catalog model in the upstream list, which names some authors differently.

```text
OpenRouter lists ``x-ai/grok-4.3`` where the catalog says ``xai/grok-4.3``, and
writes versions with dots where a lab uses dashes. An exact id wins, then an
``alias``, then a unique match on the version-insensitive slug.

Returns:
    The upstream record, or ``None`` when there is no unambiguous match.

Examples:
    >>> match_upstream("xai/grok-4.3", {"x-ai/grok-4.3": 1})
    1
    >>> match_upstream("anthropic/claude-haiku-4-5", {"anthropic/claude-haiku-4.5": 2})
    2
    >>> match_upstream("a/x", {"b/x": 1, "c/x": 2}) is None
    True
```

```python
plural.catalog.edit.match_upstream(model_id: 'str', upstream: 'Mapping[str, Any]', alias: 'str | None' = None) -> 'Any'
```

## plural.catalog.edit.parse_rate

Parse a price written per token or per million tokens.

```text
Args:
    raw: ``0.000003``, ``3e-6``, or ``3/M``.

Returns:
    The per-token price as a plain decimal string.

Raises:
    ValueError: If the value is not a non-negative number.

Examples:
    >>> parse_rate("3/M")
    '0.000003'
    >>> parse_rate("0.0000025")
    '0.0000025'
    >>> parse_rate("0.15/m")
    '0.00000015'
```

```python
plural.catalog.edit.parse_rate(raw: 'str') -> 'str'
```

## plural.catalog.edit.parse_value

Decode a ``key=value`` right-hand side for the field it targets.

```text
Prices accept ``/M``; list fields accept ``a,b,c``; anything else is read as
JSON when it parses and as a string otherwise.

Returns:
    The value to store.

Examples:
    >>> parse_value("pricing.prompt", "3/M")
    '0.000003'
    >>> parse_value("supported_parameters", "tools,temperature")
    ['tools', 'temperature']
    >>> parse_value("context_length", "200000")
    200000
    >>> parse_value("description", "A small model")
    'A small model'
```

```python
plural.catalog.edit.parse_value(path: 'str', raw: 'str') -> 'Any'
```

## plural.catalog.edit.run

Execute one parsed command against the catalog at ``args.path``.

```text
Returns:
    The JSON result to print.

Raises:
    EditError: When the command cannot be applied or would leave the
        catalog invalid.
```

```python
plural.catalog.edit.run(args: 'argparse.Namespace') -> 'dict[str, Any]'
```

## plural.catalog.edit.template

A complete, valid-shaped entry to fill in for a new model.

```text
Returns:
    An entry with placeholder values for every card field.
```

```python
plural.catalog.edit.template(model_id: 'str') -> 'dict[str, Any]'
```

## plural.catalog.edit.validate_document

Validate a whole catalog document.

```text
Args:
    document: Decoded ``models.json``.

Returns:
    Every issue across every entry.
```

```python
plural.catalog.edit.validate_document(document: 'Mapping[str, Any]') -> 'list[Issue]'
```

## plural.catalog.edit.validate_entry

Check one parsed entry beyond its shape.

```text
Args:
    card: A parsed catalog entry.

Returns:
    Errors, which block a write, and warnings, which ``--strict`` promotes.
```

```python
plural.catalog.edit.validate_entry(card: 'ModelCardDocument') -> 'list[Issue]'
```

## plural.tracing.TraceWriter

Background writer that applies redaction/sampling then sinks traces.

```text
Args:
    sink: Destination sink.
    redactor: Optional redactor applied before write.
    sampler: Optional sampler; defaults to keep-all.
    maxsize: Queue size before ``record`` blocks.
```

```python
plural.tracing.TraceWriter(sink: 'Sink', *, redactor: 'Redactor | None' = None, sampler: 'Sampler | None' = None, maxsize: 'int' = 1000) -> 'None'
```

### plural.tracing.TraceWriter.record

```python
record(self, trace: 'Trace') -> 'None'
```

Enqueue a trace for persistence.

```text
Args:
    trace: Trace to record.
```

### plural.tracing.TraceWriter.label

```python
label(self, trace_id: 'str', *, scores: 'dict[str, float] | None' = None, reward: 'float | None' = None, labels: 'dict[str, Any] | None' = None, feedback: 'str | None' = None) -> 'None'
```

Attach a late label to a trace id.

```text
If the trace has not been written yet, the label is merged on record.
If a SQLite sink is used and the trace already exists, it is updated.

Args:
    trace_id: Trace id to label.
    scores: Named scores.
    reward: Scalar reward.
    labels: Discrete labels.
    feedback: Free-form feedback.
```

### plural.tracing.TraceWriter.flush

```python
flush(self) -> 'None'
```

Block until the queue is empty.

### plural.tracing.TraceWriter.close

```python
close(self) -> 'None'
```

Flush, stop the worker, and close the sink.

## plural.tracing.sinks.JSONLSink

Append traces as JSON lines to a file.

```text
Args:
    path: Destination ``.jsonl`` path.
```

```python
plural.tracing.sinks.JSONLSink(path: 'str | Path') -> 'None'
```

### plural.tracing.sinks.JSONLSink.write

```python
write(self, trace: 'Trace') -> 'None'
```

Append one JSON line.

```text
Args:
    trace: Trace to persist.
```

### plural.tracing.sinks.JSONLSink.read_all

```python
read_all(self) -> 'list[Trace]'
```

Read all traces from the file.

```text
Returns:
    List of traces in file order.
```

### plural.tracing.sinks.JSONLSink.close

```python
close(self) -> 'None'
```

Close the file handle.

## plural.tracing.sinks.MultiSink

Fan out writes to multiple sinks.

```text
Args:
    sinks: Child sinks.
```

```python
plural.tracing.sinks.MultiSink(sinks: 'list[Sink]') -> 'None'
```

### plural.tracing.sinks.MultiSink.write

```python
write(self, trace: 'Trace') -> 'None'
```

Write to every child sink.

```text
Args:
    trace: Trace to persist.
```

### plural.tracing.sinks.MultiSink.close

```python
close(self) -> 'None'
```

Close every child sink.

## plural.tracing.sinks.OTelSink

Export traces as OpenTelemetry GenAI-style spans.

```text
The plural :class:`~plural.tracing.schema.Trace` remains canonical. This
sink is an exporter onto the still-Development ``gen_ai.*`` conventions.

Args:
    tracer_name: Tracer instrumentation name.

Note:
    Requires the ``plural[otel]`` extra.
```

```python
plural.tracing.sinks.OTelSink(tracer_name: 'str' = 'plural') -> 'None'
```

### plural.tracing.sinks.OTelSink.write

```python
write(self, trace: 'Trace') -> 'None'
```

Emit one span per LLM step plus a parent span for the trace.

```text
Args:
    trace: Trace to export.
```

### plural.tracing.sinks.OTelSink.close

```python
close(self) -> 'None'
```

No-op; tracer provider lifecycle is owned by the host app.

## plural.tracing.sinks.SQLiteSink

Persist traces in a SQLite database for querying.

```text
Args:
    path: Destination ``.sqlite`` path.
```

```python
plural.tracing.sinks.SQLiteSink(path: 'str | Path') -> 'None'
```

### plural.tracing.sinks.SQLiteSink.write

```python
write(self, trace: 'Trace') -> 'None'
```

Upsert a trace by ``trace_id``.

```text
Args:
    trace: Trace to persist.
```

### plural.tracing.sinks.SQLiteSink.get

```python
get(self, trace_id: 'str') -> 'Trace | None'
```

Fetch a trace by id.

```text
Args:
    trace_id: Trace id.

Returns:
    The trace, or ``None``.
```

### plural.tracing.sinks.SQLiteSink.query

```python
query(self, *, environment: 'str | None' = None, tag: 'str | None' = None, limit: 'int' = 100) -> 'list[Trace]'
```

Query traces with simple filters.

```text
Args:
    environment: Optional environment name filter.
    tag: Optional tag key that must be present.
    limit: Maximum rows.

Returns:
    Matching traces, newest first.
```

### plural.tracing.sinks.SQLiteSink.close

```python
close(self) -> 'None'
```

Close the database connection.

## plural.tracing.sinks.Sink

Destination for persisted traces.

```python
plural.tracing.sinks.Sink(*args, **kwargs)
```

### plural.tracing.sinks.Sink.write

```python
write(self, trace: 'Trace') -> 'None'
```

Persist a single trace.

### plural.tracing.sinks.Sink.close

```python
close(self) -> 'None'
```

Flush and release resources.

## plural.tracing.sinks.traces_from_jsonl

Load traces from a JSONL file without opening a writable sink.

```text
Args:
    path: Path to a JSONL file.

Returns:
    Parsed traces.
```

```python
plural.tracing.sinks.traces_from_jsonl(path: 'str | Path') -> 'list[Trace]'
```

## plural.tracing.Redactor

Redact sensitive fields and patterns from traces.

```text
Args:
    fields: Dot-paths to replace with ``[REDACTED]`` (e.g. ``metadata.email``).
    patterns: Regex patterns applied to all string values.
    replacement: Replacement string for matches.
    callables: Custom callables ``(trace) -> trace`` applied last.
    drop_content: If ``True``, strip message content from LLM request/response.
```

```python
plural.tracing.Redactor(*, fields: 'set[str] | None' = None, patterns: 'list[str] | None' = None, replacement: 'str' = '[REDACTED]', callables: 'list[Callable[[Trace], Trace]] | None' = None, drop_content: 'bool' = False) -> 'None'
```

### plural.tracing.Redactor.apply

```python
apply(self, trace: 'Trace') -> 'Trace'
```

Return a redacted copy of ``trace``.

```text
Args:
    trace: The original trace.

Returns:
    A redacted deep copy.
```

## plural.providers.anthropic.AnthropicProvider

Adapter for Anthropic's Messages API.

```text
Args:
    api_key: Anthropic API key.
    base_url: API base URL.
    timeout_s: Request timeout in seconds.
    default_headers: Extra headers.
    anthropic_version: Value for the ``anthropic-version`` header.
```

```python
plural.providers.anthropic.AnthropicProvider(api_key: 'str', *, base_url: 'str | None' = None, timeout_s: 'float' = 60.0, default_headers: 'dict[str, str] | None' = None, anthropic_version: 'str' = '2023-06-01') -> 'None'
```

### plural.providers.anthropic.AnthropicProvider.chat

```python
chat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Execute a non-streaming Messages API call.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.anthropic.AnthropicProvider.stream

```python
stream(self, request: 'ChatRequest') -> 'Iterator[StreamChunk]'
```

Execute a streaming Messages API call.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.anthropic.AnthropicProvider.achat

```python
achat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Async non-streaming Messages API call.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.anthropic.AnthropicProvider.astream

```python
astream(self, request: 'ChatRequest') -> 'AsyncIterator[StreamChunk]'
```

Async streaming Messages API call.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.anthropic.AnthropicProvider.close

```python
close(self) -> 'None'
```

Close the sync HTTP client.

### plural.providers.anthropic.AnthropicProvider.aclose

```python
aclose(self) -> 'None'
```

Close the async HTTP client.

## plural.providers.azure.AzureOpenAIProvider

Azure OpenAI via the v1 chat completions route.

```text
Args:
    api_key: Azure API key, or an Entra ID token when ``use_bearer_auth`` is set.
    endpoint: Resource endpoint, such as ``https://acme.openai.azure.com``.
    deployments: Maps model ids to deployment names. Both the full
        ``author/slug`` and the bare slug are accepted as keys.
    api_version: Optional explicit version, for opting into ``preview``.
    use_bearer_auth: Send the credential as a bearer token for Entra ID.
    base_url: Overrides ``endpoint`` entirely.
    region: Serving region, recorded so billing can charge that region's rate.
    name: Provider slug.
    timeout_s: Request timeout in seconds.
    default_headers: Extra headers.
    http_transport: Transport for synchronous requests.
    async_http_transport: Transport for asynchronous requests.

Raises:
    ConfigurationError: If neither ``endpoint`` nor ``base_url`` is given.

Examples:
    >>> provider = AzureOpenAIProvider(
    ...     "key",
    ...     endpoint="https://acme.openai.azure.com",
    ...     deployments={"openai/gpt-5.6-sol": "sol-prod"},
    ... )
    >>> provider._model_id("openai/gpt-5.6-sol")
    'sol-prod'
    >>> provider.close()
```

```python
plural.providers.azure.AzureOpenAIProvider(api_key: 'str', *, endpoint: 'str | None' = None, deployments: 'dict[str, str] | None' = None, api_version: 'str | None' = None, use_bearer_auth: 'bool' = False, base_url: 'str | None' = None, region: 'str' = 'us', name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.BasetenProvider

Baseten Model APIs (OpenAI-compatible).

```python
plural.providers.openai_compatible.BasetenProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.bedrock.BedrockProvider

Amazon Bedrock via the Converse and ConverseStream APIs.

```text
Args:
    api_key: Bedrock API key sent as a bearer token. Omit when using IAM.
    region: AWS region such as ``us-east-1``. Exposed as the coarse catalog
        region via ``region``, since pricing varies by continent not by zone.
    models: Maps catalog model ids to Bedrock model ids. Both the full
        ``author/slug`` and the bare slug are accepted as keys.
    access_key_id: AWS access key id, to sign with SigV4 instead.
    secret_access_key: AWS secret access key.
    session_token: Session token for temporary credentials.
    base_url: Overrides the regional endpoint.
    name: Provider slug.
    timeout_s: Request timeout in seconds.
    default_headers: Extra headers.

Raises:
    ConfigurationError: If no usable credentials are supplied.

Examples:
    >>> provider = BedrockProvider("key", region="us-east-1")
    >>> provider.name, provider.aws_region, provider.region
    ('bedrock', 'us-east-1', 'us')
    >>> provider.close()
```

```python
plural.providers.bedrock.BedrockProvider(api_key: 'str | None' = None, *, region: 'str' = 'us-east-1', models: 'dict[str, str] | None' = None, access_key_id: 'str | None' = None, secret_access_key: 'str | None' = None, session_token: 'str | None' = None, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None) -> 'None'
```

### plural.providers.bedrock.BedrockProvider.chat

```python
chat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Execute a non-streaming Converse call.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.bedrock.BedrockProvider.stream

```python
stream(self, request: 'ChatRequest') -> 'Iterator[StreamChunk]'
```

Execute a streaming Converse call.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.bedrock.BedrockProvider.achat

```python
achat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Async non-streaming Converse call.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.bedrock.BedrockProvider.astream

```python
astream(self, request: 'ChatRequest') -> 'AsyncIterator[StreamChunk]'
```

Async streaming Converse call.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.bedrock.BedrockProvider.close

```python
close(self) -> 'None'
```

Close the sync HTTP client.

### plural.providers.bedrock.BedrockProvider.aclose

```python
aclose(self) -> 'None'
```

Close the async HTTP client.

## plural.providers.openai_compatible.DeepSeekProvider

DeepSeek OpenAI-compatible API.

```python
plural.providers.openai_compatible.DeepSeekProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.FireworksProvider

Fireworks AI OpenAI-compatible API.

```python
plural.providers.openai_compatible.FireworksProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.google.GoogleProvider

Adapter for Google Gemini's generateContent API.

```text
Args:
    api_key: Google AI Studio API key.
    base_url: API base URL.
    timeout_s: Request timeout in seconds.
    default_headers: Extra headers.
    include_thoughts: Whether to ask Gemini for its thought summaries.
        Gemini reasons whether or not they are requested, and withholds them
        unless asked, which makes a thinking model look like a stalled one.
```

```python
plural.providers.google.GoogleProvider(api_key: 'str', *, base_url: 'str | None' = None, timeout_s: 'float' = 60.0, default_headers: 'dict[str, str] | None' = None, include_thoughts: 'bool' = True) -> 'None'
```

### plural.providers.google.GoogleProvider.chat

```python
chat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Execute a non-streaming generateContent call.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.google.GoogleProvider.stream

```python
stream(self, request: 'ChatRequest') -> 'Iterator[StreamChunk]'
```

Execute a streaming generateContent call.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.google.GoogleProvider.achat

```python
achat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Async non-streaming generateContent call.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.google.GoogleProvider.astream

```python
astream(self, request: 'ChatRequest') -> 'AsyncIterator[StreamChunk]'
```

Async streaming generateContent call.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.google.GoogleProvider.close

```python
close(self) -> 'None'
```

Close the sync HTTP client.

### plural.providers.google.GoogleProvider.aclose

```python
aclose(self) -> 'None'
```

Close the async HTTP client.

## plural.providers.openai_compatible.GroqProvider

Groq OpenAI-compatible API.

```python
plural.providers.openai_compatible.GroqProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.MetaProvider

Meta Model API (OpenAI-compatible).

```python
plural.providers.openai_compatible.MetaProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.MistralProvider

Mistral OpenAI-compatible API.

```python
plural.providers.openai_compatible.MistralProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.MoonshotProvider

Moonshot / Kimi lab API.

```python
plural.providers.openai_compatible.MoonshotProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.OpenAICompatible

Base adapter for OpenAI Chat Completions-compatible APIs.

```text
Args:
    api_key: Provider API key.
    base_url: API base URL.
    name: Provider slug used in traces and errors.
    timeout_s: Request timeout in seconds.
    default_headers: Extra headers.
    organization: Optional OpenAI organization header.
    strip_model_prefix: Whether to strip ``author/`` from model ids.
    http_transport: Transport for synchronous requests, such as one that
        refuses private addresses. ``None`` uses httpx's default.
    async_http_transport: Transport for asynchronous requests.
```

```python
plural.providers.openai_compatible.OpenAICompatible(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

### plural.providers.openai_compatible.OpenAICompatible.chat

```python
chat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Execute a non-streaming chat completion.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.openai_compatible.OpenAICompatible.stream

```python
stream(self, request: 'ChatRequest') -> 'Iterator[StreamChunk]'
```

Execute a streaming chat completion.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.openai_compatible.OpenAICompatible.achat

```python
achat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Async non-streaming chat completion.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.openai_compatible.OpenAICompatible.astream

```python
astream(self, request: 'ChatRequest') -> 'AsyncIterator[StreamChunk]'
```

Async streaming chat completion.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.openai_compatible.OpenAICompatible.close

```python
close(self) -> 'None'
```

Close the sync HTTP client.

### plural.providers.openai_compatible.OpenAICompatible.aclose

```python
aclose(self) -> 'None'
```

Close the async HTTP client.

## plural.providers.openai_compatible.OpenAIProvider

Official OpenAI API, over whichever of its two endpoints fits the request.

```text
OpenAI serves the same models through two incompatible wire formats, and
``/responses`` is now the larger one: ``/chat/completions`` rejects function
tools for every current model and never reports reasoning. So requests go to
:class:`~plural.providers.openai_responses.OpenAIResponsesProvider` by
default. The one thing it cannot do is ``stop`` and ``seed``, which it
rejects as unknown, so a request using either and needing nothing
Responses-only stays on chat completions instead. Every request therefore
lands on the endpoint that can serve all of it.

Args:
    api_key: OpenAI API key.
    transport: ``"auto"`` picks per request as described above. ``"chat"``
        and ``"responses"`` pin one endpoint, which is what to reach for when
        fronting a proxy that speaks only one of them.
    **kwargs: Forwarded to :class:`OpenAICompatible`.

Examples:
    >>> from plural.types import Message
    >>> provider = OpenAIProvider("sk-test")
    >>> hello = [Message(role="user", content="hi")]
    >>> provider._delegate(ChatRequest(model="openai/gpt-5.6", messages=hello)) is not None
    True
```

```python
plural.providers.openai_compatible.OpenAIProvider(api_key: 'str', *, transport: "Literal['auto', 'chat', 'responses']" = 'auto', **kwargs: 'Any') -> 'None'
```

### plural.providers.openai_compatible.OpenAIProvider.chat

```python
chat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Execute a non-streaming chat completion on the fitting endpoint.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.openai_compatible.OpenAIProvider.achat

```python
achat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Async variant of :meth:`chat`.

```text
Args:
    request: Normalized chat request.

Returns:
    Normalized chat response.
```

### plural.providers.openai_compatible.OpenAIProvider.stream

```python
stream(self, request: 'ChatRequest') -> 'Iterator[StreamChunk]'
```

Stream a chat completion from the fitting endpoint.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.openai_compatible.OpenAIProvider.astream

```python
astream(self, request: 'ChatRequest') -> 'AsyncIterator[StreamChunk]'
```

Async variant of :meth:`stream`.

```text
Args:
    request: Normalized chat request.

Yields:
    Normalized stream chunks.
```

### plural.providers.openai_compatible.OpenAIProvider.close

```python
close(self) -> 'None'
```

Close both endpoints' HTTP clients.

### plural.providers.openai_compatible.OpenAIProvider.aclose

```python
aclose(self) -> 'None'
```

Close both endpoints' async HTTP clients.

## plural.providers.openai_responses.OpenAIResponsesProvider

OpenAI Responses API, normalized to the Chat Completions shape.

```text
Args:
    api_key: OpenAI API key.
    reasoning_summaries: Whether to ask for streamed reasoning summaries.
        On by default, because a thinking model that emits nothing for ten
        seconds is indistinguishable from a hung connection.
    store: Whether to let OpenAI retain the response. Off by default to
        match Chat Completions, which retains nothing.
    **kwargs: Forwarded to :class:`OpenAICompatible`.

Examples:
    >>> provider = OpenAIResponsesProvider("sk-test")
    >>> provider.endpoint_path
    '/responses'
```

```python
plural.providers.openai_responses.OpenAIResponsesProvider(api_key: 'str', *, reasoning_summaries: 'bool' = True, store: 'bool' = False, **kwargs: 'Any') -> 'None'
```

### plural.providers.openai_responses.OpenAIResponsesProvider.serves_exactly

```python
serves_exactly(request: 'ChatRequest') -> 'bool'
```

Whether this endpoint can honour every part of a request.

```text
Args:
    request: Normalized chat request.

Returns:
    ``False`` when something would have to be dropped or adjusted, which
    is what tells the OpenAI dispatcher to prefer Chat Completions.

Examples:
    >>> from plural.types import Message
    >>> hello = [Message(role="user", content="hi")]
    >>> req = ChatRequest(model="openai/gpt-5.6", messages=hello, seed=7)
    >>> OpenAIResponsesProvider.serves_exactly(req)
    False
```

## plural.providers.base.Provider

Protocol implemented by all provider adapters.

```text
Adapters must provide sync and async chat/stream methods that accept
normalized :class:`~plural.types.ChatRequest` objects and return
normalized responses.
```

```python
plural.providers.base.Provider(*args, **kwargs)
```

### plural.providers.base.Provider.chat

```python
chat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Execute a non-streaming chat completion.

### plural.providers.base.Provider.stream

```python
stream(self, request: 'ChatRequest') -> 'Iterator[StreamChunk]'
```

Execute a streaming chat completion.

### plural.providers.base.Provider.achat

```python
achat(self, request: 'ChatRequest') -> 'ChatResponse'
```

Async non-streaming chat completion.

### plural.providers.base.Provider.astream

```python
astream(self, request: 'ChatRequest') -> 'AsyncIterator[StreamChunk]'
```

Async streaming chat completion.

```text
Implementations are typically ``async def`` generators whose return
type is :class:`~typing.AsyncIterator`.
```

### plural.providers.base.Provider.close

```python
close(self) -> 'None'
```

Close underlying HTTP resources.

### plural.providers.base.Provider.aclose

```python
aclose(self) -> 'None'
```

Close underlying async HTTP resources.

## plural.providers.base.ProviderConfig

Configuration for a provider adapter.

```text
Attributes:
    api_key: Provider API key.
    base_url: API base URL including version prefix when required.
    timeout_s: Request timeout in seconds.
    default_headers: Extra headers sent with every request.
    organization: Optional organization id (OpenAI-style).
```

## plural.providers.openai_compatible.QwenProvider

Qwen via DashScope compatible-mode.

```python
plural.providers.openai_compatible.QwenProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.TogetherProvider

Together AI OpenAI-compatible API.

```python
plural.providers.openai_compatible.TogetherProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.XAIProvider

xAI OpenAI-compatible API.

```python
plural.providers.openai_compatible.XAIProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.providers.openai_compatible.ZhipuProvider

Zhipu / Z.ai lab API.

```python
plural.providers.openai_compatible.ZhipuProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None, http_transport: 'httpx.BaseTransport | None' = None, async_http_transport: 'httpx.AsyncBaseTransport | None' = None) -> 'None'
```

## plural.errors.AuthenticationError

Raised when credentials are missing or rejected (typically HTTP 401/403).

```python
plural.errors.AuthenticationError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.BudgetExceededError

Raised when a request would exceed a configured cost or token budget.

```python
plural.errors.BudgetExceededError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.ConfigurationError

Raised when plural is misconfigured (missing keys, unknown models, etc.).

```python
plural.errors.ConfigurationError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.ConflictError

Raised when a unique slug or name already exists (typically HTTP 409).

```python
plural.errors.ConflictError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.ContentFilterError

Raised when a provider refuses the request due to a content filter.

```python
plural.errors.ContentFilterError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.ContextLengthError

Raised when the request exceeds the model's context window.

```python
plural.errors.ContextLengthError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.InvalidRequestError

Raised when the request is malformed or uses unsupported parameters.

```python
plural.errors.InvalidRequestError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.NotFoundError

Raised when a requested resource (model, trace, dataset) cannot be found.

```python
plural.errors.NotFoundError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.PluralError

Base class for all plural errors.

```text
Args:
    message: Human-readable description of the failure.
    provider: Provider slug associated with the failure, if any.
    status_code: HTTP status code, if the failure came from an HTTP response.
    body: Raw response body or structured error payload, if available.
    model: Model id that was being called, if known.
```

```python
plural.errors.PluralError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.PluralTimeoutError

Raised when a provider call exceeds the configured timeout.

```text
Formerly ``plural.TimeoutError``, which shadowed Python's built-in.
```

```python
plural.errors.PluralTimeoutError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.ProviderUnavailable

Raised when a provider is down or returns a transient 5xx error.

```python
plural.errors.ProviderUnavailable(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.RateLimitError

Raised when a provider rate-limits the request (typically HTTP 429).

```python
plural.errors.RateLimitError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.is_retryable

Return whether ``error`` should be retried by the router.

```text
Args:
    error: The exception raised by a provider call.

Returns:
    ``True`` if the error is a known retryable plural error.

Examples:
    >>> is_retryable(PluralTimeoutError("timed out"))
    True
    >>> is_retryable(AuthenticationError("bad key"))
    False
```

```python
plural.errors.is_retryable(error: 'BaseException') -> 'bool'
```
