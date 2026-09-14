---
route: /docs/reference/api
title: "API reference"
order: 240
description: "Supported public Python API signatures from the current source."
audience: all
nav: true
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
    TimeoutError: If a provider cannot be reached.
    PluralError: If a transport error occurs while probing.
```

### plural.Client.create

```python
create(self, obj: 'Any', **kwargs: 'Any') -> 'dict[str, Any]'
```

Publish a canonical revision or ingest a Trace.

```text
Args:
    obj: Canonical Environment, Task, Verifier, Agent, Harness,
        Benchmark revision, or Trace.
    **kwargs: Required hosted revision references for graph edges.

Returns:
    The hosted record created by the studio API.
```

### plural.Client.update

```python
update(self, obj: 'Any', **kwargs: 'Any') -> 'dict[str, Any]'
```

Publish a new immutable canonical revision.

```text
Args:
    obj: Canonical revision or Trace.
    **kwargs: Required hosted revision references for graph edges.

Returns:
    The hosted record updated by the studio API.
```

### plural.Client.push

```python
push(self, obj: 'Any', **kwargs: 'Any') -> 'dict[str, Any]'
```

Publish a canonical revision, creating its parent by slug.

```text
Args:
    obj: Canonical revision or Trace.
    **kwargs: Required hosted revision references for graph edges.

Returns:
    The hosted record created or updated by the studio API.
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
```

## plural.types.Usage

Token usage for a completion.

```text
Attributes:
    prompt_tokens: Input token count.
    completion_tokens: Output token count.
    total_tokens: Sum of prompt and completion tokens.
    cost: Estimated USD cost when known.
```

### plural.types.Usage.from_counts

```python
from_counts(prompt: 'int', completion: 'int', cost: 'float | None' = None) -> 'Usage'
```

Build a :class:`Usage` from prompt/completion counts.

```text
Args:
    prompt: Prompt token count.
    completion: Completion token count.
    cost: Optional USD cost.

Returns:
    A populated :class:`Usage` instance.

Examples:
    >>> Usage.from_counts(10, 5).total_tokens
    15
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

## plural.Trace

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

### plural.Trace.add_llm

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

### plural.Trace.add_action

```python
add_action(self, name: 'str', arguments: 'dict[str, Any]', *, action_id: 'str | None' = None, tool_call_id: 'str | None' = None, source: 'ActionSource' = 'environment_native', observation: 'Any' = None, result: 'Any' = None, error: 'str | None' = None, latency_ms: 'float | None' = None) -> 'ActionStep'
```

Append an action step.

### plural.Trace.add_turn

```python
add_turn(self, *, observation: 'Any' = None, model_context: 'ChatRequest | dict[str, Any] | None' = None, model_output: 'ChatResponse | None' = None, parsed_action: 'list[ParsedAction] | None' = None, actions: 'list[ActionStep] | None' = None, reward_events: 'list[RewardEvent] | None' = None, reasoning: 'list[ReasoningBlock] | None' = None, turn: 'int | None' = None) -> 'Turn'
```

Append a turn step for one model turn.

### plural.Trace.transitions

```python
transitions(self, *, source: "Literal['outcome', 'events', 'both']" = 'outcome') -> 'list[Transition]'
```

Flatten this episode into Gymnasium-style transitions.

```text
Prefers :class:`Turn` steps. Falls back to grouping flat
``llm`` / ``action`` steps so production traces still export.

Args:
    source: Reward source, matching :meth:`turn_rewards`.

Returns:
    One :class:`Transition` per turn.
```

### plural.Trace.turns

```python
turns(self) -> 'list[Turn]'
```

Return turn steps in order.

### plural.Trace.credit

```python
credit(self, value: 'float', *, name: 'str' = 'late', reason: 'str | None' = None, turn_index: 'int | None' = None) -> 'RewardEvent | Outcome'
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
    The new :class:`RewardEvent` or the updated :class:`Outcome`.

Raises:
    IndexError: If ``turn_index`` is out of range.
```

### plural.Trace.turn_rewards

```python
turn_rewards(self, *, source: "Literal['outcome', 'events', 'both']" = 'outcome') -> 'list[float]'
```

Per-turn reward used as ``r_t`` before discounting.

### plural.Trace.returns

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
    >>> t = Trace(outcome=Outcome(reward=1.0))
    >>> t.add_turn(parsed_action=[ParsedAction(name="search")])
    >>> t.add_turn(parsed_action=[ParsedAction(name="answer")])
    >>> t.returns(gamma=0.9)
    [0.9, 1.0]
```

### plural.Trace.label

```python
label(self, *, scores: 'dict[str, float] | None' = None, reward: 'float | None' = None, labels: 'dict[str, Any] | None' = None, feedback: 'str | None' = None) -> 'Outcome'
```

Attach or update the outcome.

```text
Args:
    scores: Named Verifier outputs.
    reward: Scalar reward.
    labels: Discrete labels.
    feedback: Free-form feedback.

Returns:
    The updated :class:`Outcome`.
```

## plural.TraceContext

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

```python
plural.Job(source: 'Task | Benchmark', agents: 'Sequence[Agent]', *, mode: 'JobMode' = <JobMode.EVAL: 'eval'>, attempts: 'int' = 1, concurrency: 'int' = 1, per_runtime_concurrency: 'int' = 1, priority: 'int' = 0, retry: 'RetryPolicy | None' = None, provider: 'Any' = None, providers: 'Mapping[str, Any] | None' = None, registry: 'Any' = None, store: 'Any' = None, environ: 'Mapping[str, str] | None' = None, progress: 'Any' = None, project_policy: 'Any' = None, catalog: 'ModelCatalog | None' = None) -> 'None'
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

## plural.project.CatalogContext

Explicit factory for objects validated against an effective catalog.

```python
plural.project.CatalogContext(catalog: 'ModelCatalog | None' = None) -> 'None'
```

### plural.project.CatalogContext.from_file

```python
from_file(path: 'str | Path') -> 'CatalogContext'
```

Load project model entries from JSON or YAML.

```text
Returns:
    A context containing bundled models plus explicit project entries.
```

### plural.project.CatalogContext.agent

```python
agent(self, **fields: 'Any') -> 'Agent'
```

Create an Agent against this effective catalog.

```text
Returns:
    A validated Agent.
```

### plural.project.CatalogContext.agent_verifier

```python
agent_verifier(self, **fields: 'Any') -> 'AgentVerifier'
```

Create an AgentVerifier against this effective catalog.

```text
Returns:
    A validated AgentVerifier.
```

### plural.project.CatalogContext.resolver

```python
resolver(self, root: 'str | Path | None' = None) -> 'Resolver'
```

Create a resolver carrying this catalog.

```text
Returns:
    A public project resolver.
```

## plural.project.Resolver

Resolve Python object references and public YAML object graphs.

```python
plural.project.Resolver(*, root: 'str | Path | None' = None, catalog: 'ModelCatalog | None' = None) -> 'None'
```

### plural.project.Resolver.load

```python
load(self, reference: 'str | Path', *, expected: 'type[Any] | tuple[type[Any], ...] | None' = None) -> 'ProjectObject'
```

Load one YAML file or ``path.py:object`` reference.

```text
Returns:
    The resolved public SDK object.
```

### plural.project.Resolver.resolve

```python
resolve(self, value: 'Any', *, base: 'str | Path | None' = None) -> 'Any'
```

Resolve an inline object, reference, or already-created SDK object.

```text
Returns:
    The corresponding public SDK object.
```

### plural.project.Resolver.dumps

```python
dumps(self, value: 'ProjectObject', *, base: 'str | Path | None' = None) -> 'str'
```

Serialize one public SDK graph to deterministic YAML.

```text
Returns:
    YAML using public field names and defaults.
```

### plural.project.Resolver.dump

```python
dump(self, value: 'ProjectObject', path: 'str | Path') -> 'Path'
```

Write one public SDK graph as YAML.

```text
Returns:
    The written path.
```

## plural.project.dump

Serialize a public object graph to YAML.

```text
Returns:
    The written path.
```

```python
plural.project.dump(value: 'ProjectObject', path: 'str | Path') -> 'Path'
```

## plural.project.dumps

Serialize a public object graph to YAML text.

```text
Returns:
    The YAML text.
```

```python
plural.project.dumps(value: 'ProjectObject') -> 'str'
```

## plural.project.load

Load a public project object from YAML or Python.

```text
Returns:
    The resolved object.
```

```python
plural.project.load(reference: 'str | Path', *, catalog: 'ModelCatalog | None' = None, expected: 'type[Any] | tuple[type[Any], ...] | None' = None) -> 'ProjectObject'
```

## plural.project.public_schema

Return a JSON Schema containing only public authoring fields.

```text
Returns:
    A detached schema safe for generated public references.
```

```python
plural.project.public_schema(model: 'type[BaseModel]') -> 'dict[str, Any]'
```

## plural.JobStore

Crash-safe filesystem persistence for local execution.

```python
plural.JobStore(root: 'Path' = PosixPath('.plural/jobs')) -> 'None'
```

### plural.JobStore.job_path

```python
job_path(self, job_id: 'str') -> 'Path'
```

Return a validated job directory.

### plural.JobStore.initialize

```python
initialize(self, spec: 'JobSpec', plan: 'JobPlan') -> 'Path'
```

Create or validate a locked job directory.

### plural.JobStore.load_spec

```python
load_spec(self, job_id: 'str') -> 'JobSpec'
```

Load a persisted job config.

### plural.JobStore.load_lock

```python
load_lock(self, job_id: 'str') -> 'JobLock'
```

Load a persisted reproducibility lock.

### plural.JobStore.list_jobs

```python
list_jobs(self) -> 'tuple[dict[str, Any], ...]'
```

List stored jobs without accepting partial files as results.

### plural.JobStore.emit

```python
emit(self, job_id: 'str', event_type: 'str', status: 'str', *, trial_id: 'str | None' = None, execution_id: 'int | None' = None, message: 'str' = '', data: 'Mapping[str, Any] | None' = None, secret_values: 'Iterable[str]' = ()) -> 'ProgressEvent'
```

Append one monotonic, sanitized progress event.

### plural.JobStore.events

```python
events(self, job_id: 'str', *, after: 'int' = 0, follow: 'bool' = False, poll_interval: 'float' = 0.1) -> 'Iterable[ProgressEvent]'
```

Yield events after a sequence cursor, optionally following updates.

### plural.JobStore.request_cancel

```python
request_cancel(self, job_id: 'str') -> 'None'
```

Atomically create a cancellation marker.

### plural.JobStore.clear_cancel

```python
clear_cancel(self, job_id: 'str') -> 'None'
```

Clear a prior cancellation marker before explicit resume.

### plural.JobStore.cancel_requested

```python
cancel_requested(self, job_id: 'str') -> 'bool'
```

Return whether cancellation was requested.

### plural.JobStore.trial_path

```python
trial_path(self, trial: 'TrialSpec | str', job_id: 'str | None' = None) -> 'Path'
```

Return a validated trial directory.

### plural.JobStore.successful_result

```python
successful_result(self, trial: 'TrialSpec') -> 'TrialResult | None'
```

Return a successful persisted trial result, if present.

### plural.JobStore.next_execution_id

```python
next_execution_id(self, trial: 'TrialSpec') -> 'int'
```

Return the next monotonic execution ID for a trial.

### plural.JobStore.trial_results

```python
trial_results(self, job_id: 'str') -> 'tuple[TrialResult, ...]'
```

Load all complete trial results in lexical order.

### plural.JobStore.write_trial_execution

```python
write_trial_execution(self, trial: 'TrialSpec', execution_id: 'int', result: 'TrialResult', *, stdout: 'bytes' = b'', stderr: 'bytes' = b'', artifacts: 'Iterable[DownloadedFile]' = (), verifier_stdout: 'bytes' = b'', verifier_stderr: 'bytes' = b'') -> 'Path'
```

Append one immutable execution and update the selected result.

### plural.JobStore.write_job_result

```python
write_job_result(self, result: 'JobResult') -> 'Path'
```

Atomically publish the aggregate result.

### plural.JobStore.write_review

```python
write_review(self, trial: 'TrialSpec', verifier_name: 'str', submission: 'Mapping[str, Any]', result: 'TrialResult') -> 'Path'
```

Append one immutable human review and publish its resolved Trial result.

### plural.JobStore.read_job_result

```python
read_job_result(self, job_id: 'str') -> 'JobResult | None'
```

Load the aggregate result when complete.

### plural.JobStore.write_sync_state

```python
write_sync_state(self, job_id: 'str', state: 'Mapping[str, Any]') -> 'Path'
```

Persist replay-safe hosted upload metadata without credentials.

### plural.JobStore.read_sync_state

```python
read_sync_state(self, job_id: 'str') -> 'dict[str, Any] | None'
```

Read hosted upload metadata when a prior sync was registered.

## plural.Environment

A Task-bound world with a Gymnasium ``reset`` / ``step`` episode API.

```text
Compile typed declarations into one immutable execution view. A Task pins
one Environment version. The Job or Harness constructs this instance for
that Task, calls :meth:`reset`, then applies Agent moves with :meth:`step`.
``reset`` and ``step`` are not Agent-facing ``@action`` tools.
```

```python
plural.Environment(*, name: 'str | None' = None, version: 'str | None' = None, revision: 'str | None' = None, description: 'str | None' = None, overview: 'str | None' = None, readme: 'str | None' = None, resources: 'tuple[EnvironmentResource, ...]' = (), runtime: 'EnvironmentRuntime | None' = None, secrets: 'tuple[SecretReference, ...]' = (), guardrails: 'tuple[Guardrail, ...]' = (), harness_policy: 'HarnessPolicy | None' = None, limits: 'ExecutionLimits | None' = None, metadata: 'dict[str, Any] | None' = None, state: 'StateT | None' = None, observation: 'ObsT | None' = None, info: 'Any' = None, reset_command: 'tuple[str, ...] | None' = None) -> 'None'
```

### plural.Environment.observation_snapshot

```python
observation_snapshot(self) -> 'Any'
```

Return a detached, JSON-safe agent-visible observation.

### plural.Environment.state_snapshot

```python
state_snapshot(self) -> 'Any'
```

Return a detached, JSON-safe internal state snapshot.

### plural.Environment.view

```python
view(self) -> 'dict[str, Any]'
```

Return an optional Environment-owned render document.

```text
Returns:
    A JSON-safe view. Empty means Intel falls back to the observation.
```

### plural.Environment.persist

```python
persist(self, directory: 'str | Path' = '.') -> 'None'
```

Write ``state.json``, ``observation.json``, and ``view.json``.

### plural.Environment.package

```python
package(self, command: 'str | tuple[str, ...]', *, source: 'str | Path | None' = None) -> 'Environment[ObsT, StateT]'
```

Bind Python actions to a local source tree and command adapter.

```text
The adapter receives the action name as its final argument and JSON
parameters on standard input. It should persist state between calls in
its working directory. ``reset`` uses the same adapter.

Returns:
    This Environment, ready to place directly on a Task.
```

### plural.Environment.from_config

```python
from_config(**fields: 'Any') -> 'Environment[Any, Any]'
```

Restore a serialized public Environment configuration.

```text
This is primarily used by :mod:`plural.project`; users normally author
Python subclasses and call :meth:`package`.

Returns:
    An Environment backed by the validated serialized configuration.
```

### plural.Environment.reset

```python
reset(self, *, seed: 'int | None' = None, options: 'dict[str, Any] | None' = None) -> 'tuple[ObsT, dict[str, Any]]'
```

Start a new episode.

```text
Follows the Gymnasium reset contract: ``(observation, info)``. The Job
or Harness calls this after attaching the Environment to a Task. It is
not an Agent action and does not take a Task name. Subclasses override
this to load the bound Task's initial state. ``options`` is harness
configuration, not an Agent argument.

Returns:
    The initial observation and reset information.
```

### plural.Environment.step

```python
step(self, action: 'Any' = None, /, **kwargs: 'Any') -> 'tuple[ObsT, float, bool, bool, dict[str, Any]]'
```

Apply one Agent action.

```text
Follows the Gymnasium step contract: ``(observation, reward,
terminated, truncated, info)``. ``action`` is a mapping with
``name`` plus parameters, an action name plus kwargs, or kwargs
alone when the Environment has a single ``@action``.

Returns:
    Observation, reward, terminal flags, and step information.
```

### plural.Environment.terminated

```python
terminated(self) -> 'bool'
```

Return whether the episode reached a Task success or failure state.

### plural.Environment.truncated

```python
truncated(self) -> 'bool'
```

Return whether the episode ended on a budget or external stop.

### plural.Environment.reward

```python
reward(self, previous_state: 'Any', current_state: 'Any', action: 'Mapping[str, Any]', result: 'Any') -> 'float'
```

Return the step reward. Default is ``0``.

## plural.action

Mark an :class:`~plural.environments.env.Environment` method as a native action.

```text
Args:
    fn: Method to register (decorator usage).
    name: Optional explicit action name. Defaults to the method name.

Returns:
    The original method (decorator) or a decorator.
```

```python
plural.action(fn: 'Callable[..., Any] | None' = None, *, name: 'str | None' = None) -> 'Any'
```

## plural.rewarder

Declare a train-only state-transition rewarder.

```text
The callable must accept ``previous_state, current_state, action, result``.
It is compiled into manifest metadata; the Job engine invokes rewarders
only in train mode.

Returns:
    A decorated rewarder callable.
```

```python
plural.rewarder(fn: 'Callable[..., float] | None' = None, *, name: 'str | None' = None, weight: 'float' = 1, timeout_seconds: 'float' = 30) -> 'Any'
```

## plural.environments.types.Observation

What the agent can observe after an action.

```text
This is the agent-visible projection of :class:`State`, not the
Environment itself.

Subclass this with typed fields. The JSON Schema of the subclass is
the observation contract hosted with the environment. Implement
:meth:`render` when the prompt should not be a raw dump of the
fields.

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

Persistent environment state for the episode.

```text
Nested models on this class are durable internal structures. Mark secrets
and evaluator-only facts with :func:`hidden`; only Observation is visible
to the Agent.

Attributes:
    seed: Optional deterministic seed.
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

## plural.environments.types.hidden

Mark a :class:`State` field as hidden from the agent.

```text
The annotation is stored on the JSON Schema as ``x-plural-hidden`` so
studio can show a visibility column. Hidden fields still live on
``env.state``; they must not be copied into an :class:`Observation`.

Args:
    default: Field default, same as :func:`pydantic.Field`.
    **kwargs: Other :func:`pydantic.Field` arguments.

Returns:
    A Pydantic field with the hidden schema flag.
```

```python
plural.environments.types.hidden(default: 'Any' = Ellipsis, **kwargs: 'Any') -> 'Any'
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

## plural.environments.types.is_hidden_schema_field

Return whether a JSON Schema property is marked hidden.

```text
Args:
    spec: One property schema from ``model_json_schema``.

Returns:
    ``True`` when the field carries ``x-plural-hidden``.
```

```python
plural.environments.types.is_hidden_schema_field(spec: 'Any') -> 'bool'
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

An executable Agent interaction strategy.

## plural.SandboxProvider

Async lifecycle provider, separate from environment tool runtimes.

```python
plural.SandboxProvider()
```

### plural.SandboxProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare controls available in the current installation.

### plural.SandboxProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Fail before launch if any requested control is unavailable.

### plural.SandboxProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Return dependency, daemon, or credential health.

### plural.SandboxProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a fresh sandbox after successful preflight.

### plural.SandboxProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Upload validated files beneath a scoped workspace.

### plural.SandboxProvider.upload_bundle

```python
upload_bundle(self, handle: 'SandboxHandle', bundle: 'Path', *, root: 'str' = '/workspace') -> 'None'
```

Upload a local directory without following symlinks.

### plural.SandboxProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute argv with cwd, env, timeout, stdin, and captured logs.

### plural.SandboxProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download exact declared files.

### plural.SandboxProvider.download_artifacts

```python
download_artifacts(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download declared artifact files.

### plural.SandboxProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Force cancellation of active work.

### plural.SandboxProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Idempotently delete the sandbox and scoped data.

## plural.SandboxRequirements

Controls required for one sandbox before it may launch.

### plural.SandboxRequirements.required_capabilities

```python
required_capabilities(self) -> 'frozenset[Capability]'
```

Return the controls that must be enforceable.

## plural.ProviderRegistry

Resolve built-ins and installed provider plugins lazily.

```python
plural.ProviderRegistry() -> 'None'
```

### plural.ProviderRegistry.register

```python
register(self, provider: 'SandboxProvider', *, replace: 'bool' = False) -> 'None'
```

Register one concrete provider.

### plural.ProviderRegistry.get

```python
get(self, name: 'str') -> 'SandboxProvider'
```

Return a registered provider, loading plugins first.

### plural.ProviderRegistry.doctors

```python
doctors(self, *, include_unavailable: 'bool' = False) -> 'tuple[ProviderDoctor, ...]'
```

Return dynamic provider reports in stable name order.

## plural.LocalProvider

Run commands in temporary directories without isolation.

```text
This provider intentionally does not advertise network, resource, image, or
read-only-root enforcement. It is suitable only for explicitly trusted local
development workloads.
```

```python
plural.LocalProvider(*, base_dir: 'Path | None' = None) -> 'None'
```

### plural.LocalProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare local subprocess controls.

### plural.LocalProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Report local execution availability without implying isolation.

### plural.LocalProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a scoped temporary workspace.

### plural.LocalProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Copy files into the temporary workspace.

### plural.LocalProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Run an argv-only subprocess and kill it at timeout.

### plural.LocalProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Read exact declared regular files.

### plural.LocalProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Kill the active subprocess, if any.

### plural.LocalProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Kill active work and remove all scoped files.

## plural.DockerProvider

Create one locked-down Docker container per execution phase.

```python
plural.DockerProvider(*, executable: 'str' = 'docker', default_image: 'str' = 'python:3.12-slim') -> 'None'
```

### plural.DockerProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare Docker controls only when the daemon is reachable.

### plural.DockerProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Reject provider-specific image forms before launch.

### plural.DockerProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Detect the Docker CLI and daemon.

### plural.DockerProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create and start a hardened, scoped container.

### plural.DockerProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Stream exact files into the writable workspace mount.

### plural.DockerProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute argv and capture logs, enforcing a host-side timeout.

### plural.DockerProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Stream exact declared paths out and reject non-regular files.

### plural.DockerProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Kill the container to force all active processes to stop.

### plural.DockerProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Force-remove the container idempotently.

## plural.DaytonaProvider

Execute in Daytona while keeping its SDK an optional import.

```python
plural.DaytonaProvider(*, adapter: 'DaytonaClientAdapter | None' = None, environ: 'Mapping[str, str] | None' = None) -> 'None'
```

### plural.DaytonaProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare controls implemented by the current Daytona SDK.

### plural.DaytonaProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Reject Daytona controls whose SDK mapping is not enforceable.

### plural.DaytonaProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Detect SDK and credential presence without exposing values.

### plural.DaytonaProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a Daytona sandbox from image, snapshot, or defaults.

### plural.DaytonaProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Upload exact in-memory files.

### plural.DaytonaProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute through ``sandbox.process.exec``.

### plural.DaytonaProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download exact declared files.

### plural.DaytonaProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Delete the sandbox to force cancellation.

### plural.DaytonaProvider.destroy

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

## plural.ModelSpec

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
    provider: Derived provider slug (author segment of ``id``).
```

### plural.ModelSpec.ordered_endpoints

```python
ordered_endpoints(self) -> 'list[ModelEndpoint]'
```

Return endpoints with US hosts first (Fireworks, then Baseten).

```text
Returns:
    Ordered endpoints, or a single implicit author host when none are listed.
```

### plural.ModelSpec.host_providers

```python
host_providers(self) -> 'list[str]'
```

Return host slugs that can serve this model.

### plural.ModelSpec.pricing_for

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

## plural.estimate_cost

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
plural.estimate_cost(usage: 'Usage', spec: 'ModelSpec | None', *, provider: 'str | None' = None, region: 'str | None' = None) -> 'float | None'
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
```

```python
plural.catalog.sync.UpstreamEndpoint(provider: 'str | None', region: 'str', tier: 'str', upstream_id: 'str', prompt: 'float | None', completion: 'float | None', discount: 'float | None', tiers: 'tuple[UpstreamTier, ...]', tag: 'str') -> None
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
```

```python
plural.catalog.sync.UpstreamModel(id: 'str', name: 'str | None' = None, context_length: 'int | None' = None, prompt: 'float | None' = None, completion: 'float | None' = None, modality: 'str | None' = None, input_modalities: 'tuple[str, ...]' = ('text',), output_modalities: 'tuple[str, ...]' = ('text',), supported_parameters: 'tuple[str, ...]' = ()) -> None
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
plural.catalog.sync.load_catalog(path: 'Path' = PosixPath('/Users/taylor/Projects/plural/src/plural/catalog/data/models.json')) -> 'dict[str, Any]'
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
plural.catalog.sync.write_catalog(document: 'Mapping[str, Any]', path: 'Path' = PosixPath('/Users/taylor/Projects/plural/src/plural/catalog/data/models.json')) -> 'None'
```

## plural.TraceWriter

Background writer that applies redaction/sampling then sinks traces.

```text
Args:
    sink: Destination sink.
    redactor: Optional redactor applied before write.
    sampler: Optional sampler; defaults to keep-all.
    maxsize: Queue size before ``record`` blocks.
```

```python
plural.TraceWriter(sink: 'Sink', *, redactor: 'Redactor | None' = None, sampler: 'Sampler | None' = None, maxsize: 'int' = 1000) -> 'None'
```

### plural.TraceWriter.record

```python
record(self, trace: 'Trace') -> 'None'
```

Enqueue a trace for persistence.

```text
Args:
    trace: Trace to record.
```

### plural.TraceWriter.label

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

### plural.TraceWriter.flush

```python
flush(self) -> 'None'
```

Block until the queue is empty.

### plural.TraceWriter.close

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

## plural.Redactor

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
plural.Redactor(*, fields: 'set[str] | None' = None, patterns: 'list[str] | None' = None, replacement: 'str' = '[REDACTED]', callables: 'list[Callable[[Trace], Trace]] | None' = None, drop_content: 'bool' = False) -> 'None'
```

### plural.Redactor.apply

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
plural.providers.azure.AzureOpenAIProvider(api_key: 'str', *, endpoint: 'str | None' = None, deployments: 'dict[str, str] | None' = None, api_version: 'str | None' = None, use_bearer_auth: 'bool' = False, base_url: 'str | None' = None, region: 'str' = 'us', name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None) -> 'None'
```

## plural.providers.openai_compatible.BasetenProvider

Baseten Model APIs (OpenAI-compatible).

```python
plural.providers.openai_compatible.BasetenProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
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
plural.providers.openai_compatible.DeepSeekProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.FireworksProvider

Fireworks AI OpenAI-compatible API.

```python
plural.providers.openai_compatible.FireworksProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
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
plural.providers.openai_compatible.GroqProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.MetaProvider

Meta Model API (OpenAI-compatible).

```python
plural.providers.openai_compatible.MetaProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.MistralProvider

Mistral OpenAI-compatible API.

```python
plural.providers.openai_compatible.MistralProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.MoonshotProvider

Moonshot / Kimi lab API.

```python
plural.providers.openai_compatible.MoonshotProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
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
```

```python
plural.providers.openai_compatible.OpenAICompatible(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
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
plural.providers.openai_compatible.QwenProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.TogetherProvider

Together AI OpenAI-compatible API.

```python
plural.providers.openai_compatible.TogetherProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.XAIProvider

xAI OpenAI-compatible API.

```python
plural.providers.openai_compatible.XAIProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
```

## plural.providers.openai_compatible.ZhipuProvider

Zhipu / Z.ai lab API.

```python
plural.providers.openai_compatible.ZhipuProvider(api_key: 'str', *, base_url: 'str | None' = None, name: 'str | None' = None, timeout_s: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, organization: 'str | None' = None, strip_model_prefix: 'bool | None' = None) -> 'None'
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

## plural.errors.TimeoutError

Raised when a provider call exceeds the configured timeout.

```python
plural.errors.TimeoutError(message: 'str', *, provider: 'str | None' = None, status_code: 'int | None' = None, body: 'Any' = None, model: 'str | None' = None) -> 'None'
```

## plural.errors.is_retryable

Return whether ``error`` should be retried by the router.

```text
Args:
    error: The exception raised by a provider call.

Returns:
    ``True`` if the error is a known retryable plural error.

Examples:
    >>> is_retryable(TimeoutError("timed out"))
    True
    >>> is_retryable(AuthenticationError("bad key"))
    False
```

```python
plural.errors.is_retryable(error: 'BaseException') -> 'bool'
```
