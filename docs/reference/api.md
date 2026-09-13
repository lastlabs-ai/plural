---
route: /docs/reference/api
title: "API reference"
order: 240
description: "Python API signatures and documentation from the current source."
audience: all
nav: false
---
# API reference

Start with [the project walkthrough](../tutorials/first-project.md) for complete working code. Use the [field catalog](fields.md) for definition fields, defaults, and constraints. This reference is generated from the current package and is identical on both documentation surfaces.

Model constructors are described by their field contracts rather than duplicating long generated signatures. Methods below are defined on the listed class; ordinary inherited Pydantic methods are not repeated.

## plural.client.Client

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
plural.client.Client(*, api_key: 'str | None' = None, providers: 'Mapping[str, str | Provider] | None' = None, base_url: 'str | None' = None, catalog: 'ModelCatalog | None' = None, policy: 'RoutingPolicy | None' = None, sink: 'Sink | None' = None, redactor: 'Redactor | None' = None, sampler: 'Sampler | None' = None, capture_content: 'bool | None' = None, max_retries: 'int' = 2, max_cost_usd: 'float | None' = None, default_headers: 'dict[str, str] | None' = None, tags: 'dict[str, str] | None' = None, trace_dir: 'str | Path | None' = None, project: 'str | None' = None) -> 'None'
```

### plural.client.Client.is_authenticated

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

### plural.client.Client.create

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

### plural.client.Client.update

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

### plural.client.Client.push

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

### plural.client.Client.chat

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

### plural.client.Client.achat

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

### plural.client.Client.stream

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

### plural.client.Client.astream

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

### plural.client.Client.label

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

### plural.client.Client.flush

```python
flush(self) -> 'None'
```

Flush pending traces.

### plural.client.Client.close

```python
close(self) -> 'None'
```

Flush traces and close providers.

### plural.client.Client.aclose

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

## plural.tracing.schema.Trace

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

### plural.tracing.schema.Trace.add_llm

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

### plural.tracing.schema.Trace.add_action

```python
add_action(self, name: 'str', arguments: 'dict[str, Any]', *, action_id: 'str | None' = None, tool_call_id: 'str | None' = None, source: 'ActionSource' = 'environment_native', observation: 'Any' = None, result: 'Any' = None, error: 'str | None' = None, latency_ms: 'float | None' = None) -> 'ActionStep'
```

Append an action step.

### plural.tracing.schema.Trace.add_turn

```python
add_turn(self, *, observation: 'Any' = None, model_context: 'ChatRequest | dict[str, Any] | None' = None, model_output: 'ChatResponse | None' = None, parsed_action: 'list[ParsedAction] | None' = None, actions: 'list[ActionStep] | None' = None, reward_events: 'list[RewardEvent] | None' = None, reasoning: 'list[ReasoningBlock] | None' = None, turn: 'int | None' = None) -> 'Turn'
```

Append a turn step for one model turn.

### plural.tracing.schema.Trace.transitions

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

### plural.tracing.schema.Trace.turns

```python
turns(self) -> 'list[Turn]'
```

Return turn steps in order.

### plural.tracing.schema.Trace.credit

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

### plural.tracing.schema.Trace.turn_rewards

```python
turn_rewards(self, *, source: "Literal['outcome', 'events', 'both']" = 'outcome') -> 'list[float]'
```

Per-turn reward used as ``r_t`` before discounting.

### plural.tracing.schema.Trace.returns

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

### plural.tracing.schema.Trace.label

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

## plural.tracing.schema.TraceContext

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

## plural.execution.engine.Job

Bounded async Job scheduler across Environment-owned runtimes.

```python
plural.execution.engine.Job(spec: 'JobSpec', *, provider: 'SandboxProvider | None' = None, providers: 'Mapping[str, SandboxProvider] | None' = None, registry: 'ProviderRegistry' = <configured default>, store: 'JobStore | None' = None, environ: 'Mapping[str, str] | None' = None, progress: 'Callable[[TrialSpec, TrialResult], None] | None' = None, project_policy: 'ProjectPolicy | None' = None, catalog: 'ModelCatalog | None' = None) -> 'None'
```

### plural.execution.engine.Job.cancel

```python
cancel(self) -> 'None'
```

Request cancellation and stop active sandboxes.

### plural.execution.engine.Job.preflight

```python
preflight(self) -> 'None'
```

Validate every Environment/Harness/Verifier runtime before launching.

### plural.execution.engine.Job.run

```python
run(self, *, resume: 'bool' = False) -> 'JobResult'
```

Execute all ready Trials with global and per-runtime bounds.

### plural.execution.engine.Job.submit_review

```python
submit_review(self, trial_id: 'str', verifier_name: 'str', scores: 'Mapping[str, float]', *, feedback: 'str' = '') -> 'JobResult'
```

Resolve one pending Human Verifier and recompute deterministic aggregates.

```text
Returns:
    Updated durable Job result.
```

## plural.execution.engine.Trial

One immutable Trial with append-only TrialExecutions.

```python
plural.execution.engine.Trial(spec: 'TrialSpec', *, job_spec: 'JobSpec', provider_for: 'Callable[[str], SandboxProvider]', store: 'JobStore', environ: 'Mapping[str, str]', project_policy: 'ProjectPolicy') -> 'None'
```

### plural.execution.engine.Trial.cancel

```python
cancel(self) -> 'None'
```

Cancel all active sandboxes.

### plural.execution.engine.Trial.run

```python
run(self, retry: 'int', execution_id: 'int') -> 'TrialResult'
```

Run one TrialExecution.

## plural.execution.store.JobStore

Crash-safe filesystem persistence for local execution.

```python
plural.execution.store.JobStore(root: 'Path' = PosixPath('.plural/jobs')) -> 'None'
```

### plural.execution.store.JobStore.job_path

```python
job_path(self, job_id: 'str') -> 'Path'
```

Return a validated job directory.

### plural.execution.store.JobStore.initialize

```python
initialize(self, spec: 'JobSpec', plan: 'JobPlan') -> 'Path'
```

Create or validate a locked job directory.

### plural.execution.store.JobStore.load_spec

```python
load_spec(self, job_id: 'str') -> 'JobSpec'
```

Load a persisted job config.

### plural.execution.store.JobStore.load_lock

```python
load_lock(self, job_id: 'str') -> 'JobLock'
```

Load a persisted reproducibility lock.

### plural.execution.store.JobStore.list_jobs

```python
list_jobs(self) -> 'tuple[dict[str, Any], ...]'
```

List stored jobs without accepting partial files as results.

### plural.execution.store.JobStore.emit

```python
emit(self, job_id: 'str', event_type: 'str', status: 'str', *, trial_id: 'str | None' = None, execution_id: 'int | None' = None, message: 'str' = '', data: 'Mapping[str, Any] | None' = None, secret_values: 'Iterable[str]' = ()) -> 'ProgressEvent'
```

Append one monotonic, sanitized progress event.

### plural.execution.store.JobStore.events

```python
events(self, job_id: 'str', *, after: 'int' = 0, follow: 'bool' = False, poll_interval: 'float' = 0.1) -> 'Iterable[ProgressEvent]'
```

Yield events after a sequence cursor, optionally following updates.

### plural.execution.store.JobStore.request_cancel

```python
request_cancel(self, job_id: 'str') -> 'None'
```

Atomically create a cancellation marker.

### plural.execution.store.JobStore.clear_cancel

```python
clear_cancel(self, job_id: 'str') -> 'None'
```

Clear a prior cancellation marker before explicit resume.

### plural.execution.store.JobStore.cancel_requested

```python
cancel_requested(self, job_id: 'str') -> 'bool'
```

Return whether cancellation was requested.

### plural.execution.store.JobStore.trial_path

```python
trial_path(self, trial: 'TrialSpec | str', job_id: 'str | None' = None) -> 'Path'
```

Return a validated trial directory.

### plural.execution.store.JobStore.successful_result

```python
successful_result(self, trial: 'TrialSpec') -> 'TrialResult | None'
```

Return a successful persisted trial result, if present.

### plural.execution.store.JobStore.next_execution_id

```python
next_execution_id(self, trial: 'TrialSpec') -> 'int'
```

Return the next monotonic execution ID for a trial.

### plural.execution.store.JobStore.trial_results

```python
trial_results(self, job_id: 'str') -> 'tuple[TrialResult, ...]'
```

Load all complete trial results in lexical order.

### plural.execution.store.JobStore.write_trial_execution

```python
write_trial_execution(self, trial: 'TrialSpec', execution_id: 'int', result: 'TrialResult', *, stdout: 'bytes' = b'', stderr: 'bytes' = b'', artifacts: 'Iterable[DownloadedFile]' = (), verifier_stdout: 'bytes' = b'', verifier_stderr: 'bytes' = b'') -> 'Path'
```

Append one immutable execution and update the selected result.

### plural.execution.store.JobStore.write_job_result

```python
write_job_result(self, result: 'JobResult') -> 'Path'
```

Atomically publish the aggregate result.

### plural.execution.store.JobStore.write_review

```python
write_review(self, trial: 'TrialSpec', verifier_name: 'str', submission: 'Mapping[str, Any]', result: 'TrialResult') -> 'Path'
```

Append one immutable human review and publish its resolved Trial result.

### plural.execution.store.JobStore.read_job_result

```python
read_job_result(self, job_id: 'str') -> 'JobResult | None'
```

Load the aggregate result when complete.

### plural.execution.store.JobStore.write_sync_state

```python
write_sync_state(self, job_id: 'str', state: 'Mapping[str, Any]') -> 'Path'
```

Persist replay-safe hosted upload metadata without credentials.

### plural.execution.store.JobStore.read_sync_state

```python
read_sync_state(self, job_id: 'str') -> 'dict[str, Any] | None'
```

Read hosted upload metadata when a prior sync was registered.

## plural.environments.env.Environment

A Task-bound world with a Gymnasium ``reset`` / ``step`` episode API.

```text
Compile typed declarations into one immutable execution view. A Task pins
one Environment version. The Job or Harness constructs this instance for
that Task, calls :meth:`reset`, then applies Agent moves with :meth:`step`.
``reset`` and ``step`` are not Agent-facing ``@action`` tools.
```

```python
plural.environments.env.Environment(*, name: 'str | None' = None, version: 'str | None' = None, revision: 'str | None' = None, description: 'str | None' = None, overview: 'str | None' = None, readme: 'str | None' = None, resources: 'tuple[EnvironmentResource, ...]' = (), runtime: 'EnvironmentRuntime | None' = None, secrets: 'tuple[SecretReference, ...]' = (), guardrails: 'tuple[Guardrail, ...]' = (), harness_policy: 'HarnessPolicy | None' = None, limits: 'ExecutionLimits | None' = None, metadata: 'dict[str, Any] | None' = None, state: 'StateT | None' = None, observation: 'ObsT | None' = None, info: 'Any' = None, reset_command: 'tuple[str, ...] | None' = None) -> 'None'
```

### plural.environments.env.Environment.observation_snapshot

```python
observation_snapshot(self) -> 'Any'
```

Return a detached, JSON-safe agent-visible observation.

### plural.environments.env.Environment.state_snapshot

```python
state_snapshot(self) -> 'Any'
```

Return a detached, JSON-safe internal state snapshot.

### plural.environments.env.Environment.view

```python
view(self) -> 'dict[str, Any]'
```

Return an optional Environment-owned render document.

```text
Returns:
    A JSON-safe view. Empty means Intel falls back to the observation.
```

### plural.environments.env.Environment.persist

```python
persist(self, directory: 'str | Path' = '.') -> 'None'
```

Write ``state.json``, ``observation.json``, and ``view.json``.

### plural.environments.env.Environment.package

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

### plural.environments.env.Environment.from_config

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

### plural.environments.env.Environment.reset

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

### plural.environments.env.Environment.step

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

### plural.environments.env.Environment.terminated

```python
terminated(self) -> 'bool'
```

Return whether the episode reached a Task success or failure state.

### plural.environments.env.Environment.truncated

```python
truncated(self) -> 'bool'
```

Return whether the episode ended on a budget or external stop.

### plural.environments.env.Environment.reward

```python
reward(self, previous_state: 'Any', current_state: 'Any', action: 'Mapping[str, Any]', result: 'Any') -> 'float'
```

Return the step reward. Default is ``0``.

## plural.environments.env.action

Mark an :class:`~plural.environments.env.Environment` method as a native action.

```text
Args:
    fn: Method to register (decorator usage).
    name: Optional explicit action name. Defaults to the method name.

Returns:
    The original method (decorator) or a decorator.
```

```python
plural.environments.env.action(fn: 'Callable[..., Any] | None' = None, *, name: 'str | None' = None) -> 'Any'
```

## plural.environments.env.rewarder

Declare a train-only state-transition rewarder.

```text
The callable must accept ``previous_state, current_state, action, result``.
It is compiled into manifest metadata; the Job engine invokes rewarders
only in train mode.

Returns:
    A decorated rewarder callable.
```

```python
plural.environments.env.rewarder(fn: 'Callable[..., float] | None' = None, *, name: 'str | None' = None, weight: 'float' = 1, timeout_seconds: 'float' = 30) -> 'Any'
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

## plural.harness.models.Harness

An executable Agent interaction strategy.

## plural.harness.models.HarnessOutput

One file produced by a Harness.

## plural.sandbox.base.SandboxProvider

Async lifecycle provider, separate from environment tool runtimes.

```python
plural.sandbox.base.SandboxProvider()
```

### plural.sandbox.base.SandboxProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare controls available in the current installation.

### plural.sandbox.base.SandboxProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Fail before launch if any requested control is unavailable.

### plural.sandbox.base.SandboxProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Return dependency, daemon, or credential health.

### plural.sandbox.base.SandboxProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a fresh sandbox after successful preflight.

### plural.sandbox.base.SandboxProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Upload validated files beneath a scoped workspace.

### plural.sandbox.base.SandboxProvider.upload_bundle

```python
upload_bundle(self, handle: 'SandboxHandle', bundle: 'Path', *, root: 'str' = '/workspace') -> 'None'
```

Upload a local directory without following symlinks.

### plural.sandbox.base.SandboxProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute argv with cwd, env, timeout, stdin, and captured logs.

### plural.sandbox.base.SandboxProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download exact declared files.

### plural.sandbox.base.SandboxProvider.download_artifacts

```python
download_artifacts(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download declared artifact files.

### plural.sandbox.base.SandboxProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Force cancellation of active work.

### plural.sandbox.base.SandboxProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Idempotently delete the sandbox and scoped data.

## plural.sandbox.models.Capability

Individual controls a provider can enforce.

```python
plural.sandbox.models.Capability(*values)
```

## plural.sandbox.models.CapabilityError

A requested control cannot be enforced.

```python
plural.sandbox.models.CapabilityError
```

## plural.sandbox.models.DeclarativeImage

Portable subset of Daytona's declarative image builder.

## plural.sandbox.models.DownloadedFile

One file retrieved from a sandbox.

## plural.sandbox.models.EffectiveSandboxPolicy

Provider-confirmed requirements captured in receipts.

## plural.sandbox.models.ExecRequest

One argv-based process invocation.

## plural.sandbox.models.ExecResult

Captured process completion.

## plural.sandbox.models.FileUpload

One in-memory file copied into a sandbox.

## plural.sandbox.models.NetworkMode

Requested sandbox network policy.

```python
plural.sandbox.models.NetworkMode(*values)
```

## plural.sandbox.models.ProviderCapabilities

Provider capability declaration used by preflight and runtime doctor.

### plural.sandbox.models.ProviderCapabilities.supports

```python
supports(self, capability: 'Capability') -> 'bool'
```

Return whether a control is available.

## plural.sandbox.models.ProviderDoctor

Availability report safe for CLI output.

## plural.sandbox.models.ProviderUnavailableError

Provider dependency, daemon, or credentials are unavailable.

```python
plural.sandbox.models.ProviderUnavailableError
```

## plural.sandbox.models.ResourceRequirements

Optional compute limits.

## plural.sandbox.models.SandboxError

Base sandbox lifecycle error.

```python
plural.sandbox.models.SandboxError
```

## plural.sandbox.models.SandboxHandle

Opaque provider sandbox identity.

## plural.sandbox.models.SandboxRequirements

Controls required for one sandbox before it may launch.

### plural.sandbox.models.SandboxRequirements.required_capabilities

```python
required_capabilities(self) -> 'frozenset[Capability]'
```

Return the controls that must be enforceable.

## plural.sandbox.models.SandboxTimeoutError

A sandbox process exceeded its deadline.

```python
plural.sandbox.models.SandboxTimeoutError
```

## plural.sandbox.models.environment_required_capabilities

Derive sandbox controls required by an environment runtime declaration.

```python
plural.sandbox.models.environment_required_capabilities(runtime: 'Any') -> 'frozenset[Capability]'
```

## plural.sandbox.models.safe_relative_path

Validate and normalize a sandbox-relative path.

```python
plural.sandbox.models.safe_relative_path(value: 'str') -> 'str'
```

## plural.sandbox.registry.ProviderRegistry

Resolve built-ins and installed provider plugins lazily.

```python
plural.sandbox.registry.ProviderRegistry() -> 'None'
```

### plural.sandbox.registry.ProviderRegistry.register

```python
register(self, provider: 'SandboxProvider', *, replace: 'bool' = False) -> 'None'
```

Register one concrete provider.

### plural.sandbox.registry.ProviderRegistry.get

```python
get(self, name: 'str') -> 'SandboxProvider'
```

Return a registered provider, loading plugins first.

### plural.sandbox.registry.ProviderRegistry.doctors

```python
doctors(self, *, include_unavailable: 'bool' = False) -> 'tuple[ProviderDoctor, ...]'
```

Return dynamic provider reports in stable name order.

## plural.sandbox.local.LocalProvider

Run commands in temporary directories without isolation.

```text
This provider intentionally does not advertise network, resource, image, or
read-only-root enforcement. It is suitable only for explicitly trusted local
development workloads.
```

```python
plural.sandbox.local.LocalProvider(*, base_dir: 'Path | None' = None) -> 'None'
```

### plural.sandbox.local.LocalProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare local subprocess controls.

### plural.sandbox.local.LocalProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Report local execution availability without implying isolation.

### plural.sandbox.local.LocalProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a scoped temporary workspace.

### plural.sandbox.local.LocalProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Copy files into the temporary workspace.

### plural.sandbox.local.LocalProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Run an argv-only subprocess and kill it at timeout.

### plural.sandbox.local.LocalProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Read exact declared regular files.

### plural.sandbox.local.LocalProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Kill the active subprocess, if any.

### plural.sandbox.local.LocalProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Kill active work and remove all scoped files.

## plural.sandbox.docker.DockerProvider

Create one locked-down Docker container per execution phase.

```python
plural.sandbox.docker.DockerProvider(*, executable: 'str' = 'docker', default_image: 'str' = 'python:3.12-slim') -> 'None'
```

### plural.sandbox.docker.DockerProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare Docker controls only when the daemon is reachable.

### plural.sandbox.docker.DockerProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Reject provider-specific image forms before launch.

### plural.sandbox.docker.DockerProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Detect the Docker CLI and daemon.

### plural.sandbox.docker.DockerProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create and start a hardened, scoped container.

### plural.sandbox.docker.DockerProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Stream exact files into the writable workspace mount.

### plural.sandbox.docker.DockerProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute argv and capture logs, enforcing a host-side timeout.

### plural.sandbox.docker.DockerProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Stream exact declared paths out and reject non-regular files.

### plural.sandbox.docker.DockerProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Kill the container to force all active processes to stop.

### plural.sandbox.docker.DockerProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Force-remove the container idempotently.

## plural.sandbox.daytona.DaytonaProvider

Execute in Daytona while keeping its SDK an optional import.

```python
plural.sandbox.daytona.DaytonaProvider(*, adapter: 'DaytonaClientAdapter | None' = None, environ: 'Mapping[str, str] | None' = None) -> 'None'
```

### plural.sandbox.daytona.DaytonaProvider.capabilities

```python
capabilities(self) -> 'ProviderCapabilities'
```

Declare controls implemented by the current Daytona SDK.

### plural.sandbox.daytona.DaytonaProvider.preflight

```python
preflight(self, requirements: 'SandboxRequirements') -> 'EffectiveSandboxPolicy'
```

Reject Daytona controls whose SDK mapping is not enforceable.

### plural.sandbox.daytona.DaytonaProvider.doctor

```python
doctor(self) -> 'ProviderDoctor'
```

Detect SDK and credential presence without exposing values.

### plural.sandbox.daytona.DaytonaProvider.create

```python
create(self, requirements: 'SandboxRequirements') -> 'SandboxHandle'
```

Create a Daytona sandbox from image, snapshot, or defaults.

### plural.sandbox.daytona.DaytonaProvider.upload_files

```python
upload_files(self, handle: 'SandboxHandle', files: 'Sequence[FileUpload]', *, root: 'str' = '/workspace') -> 'None'
```

Upload exact in-memory files.

### plural.sandbox.daytona.DaytonaProvider.exec

```python
exec(self, handle: 'SandboxHandle', request: 'ExecRequest') -> 'ExecResult'
```

Execute through ``sandbox.process.exec``.

### plural.sandbox.daytona.DaytonaProvider.download_files

```python
download_files(self, handle: 'SandboxHandle', paths: 'Sequence[str]', *, root: 'str' = '/workspace') -> 'tuple[DownloadedFile, ...]'
```

Download exact declared files.

### plural.sandbox.daytona.DaytonaProvider.cancel

```python
cancel(self, handle: 'SandboxHandle') -> 'None'
```

Delete the sandbox to force cancellation.

### plural.sandbox.daytona.DaytonaProvider.destroy

```python
destroy(self, handle: 'SandboxHandle') -> 'None'
```

Idempotently delete the remote sandbox.

## plural.cli.config.CLIConfig

Persistent, non-secret CLI configuration.

## plural.cli.config.CLIProfile

One named CLI context.

## plural.cli.config.Credential

Secret tokens stored for one profile.

### plural.cli.config.Credential.redacted

```python
redacted(self) -> 'dict[str, str | None]'
```

Return presence-only values safe for logs and machine output.

## plural.cli.config.CredentialStore

Minimal credential storage abstraction.

```python
plural.cli.config.CredentialStore(*args, **kwargs)
```

### plural.cli.config.CredentialStore.get

```python
get(self, profile: 'str') -> 'Credential | None'
```

Read credentials for a profile.

### plural.cli.config.CredentialStore.set

```python
set(self, profile: 'str', credential: 'Credential') -> 'None'
```

Persist credentials for a profile.

### plural.cli.config.CredentialStore.delete

```python
delete(self, profile: 'str') -> 'None'
```

Delete credentials for a profile.

## plural.cli.config.FileCredentialStore

0600 JSON credential fallback.

```python
plural.cli.config.FileCredentialStore(path: 'Path') -> 'None'
```

### plural.cli.config.FileCredentialStore.get

```python
get(self, profile: 'str') -> 'Credential | None'
```

Read and validate one profile's credential.

### plural.cli.config.FileCredentialStore.set

```python
set(self, profile: 'str', credential: 'Credential') -> 'None'
```

Atomically save credentials with owner-only permissions.

### plural.cli.config.FileCredentialStore.delete

```python
delete(self, profile: 'str') -> 'None'
```

Delete one profile without affecting others.

## plural.cli.config.ResolvedContext

Effective CLI context after flags > environment > config precedence.

### plural.cli.config.ResolvedContext.redacted

```python
redacted(self) -> 'dict[str, Any]'
```

Return context safe for console output.

## plural.cli.config.config_home

Return the platform-aware Plural CLI config directory.

```python
plural.cli.config.config_home(environ: 'Mapping[str, str] | None' = None) -> 'Path'
```

## plural.cli.config.default_credential_store

Build optional keyring plus secure file fallback storage.

```python
plural.cli.config.default_credential_store(path: 'Path | None' = None) -> 'CredentialStore'
```

## plural.cli.config.load_config

Load config, returning defaults when the file does not exist.

```python
plural.cli.config.load_config(path: 'Path | None' = None) -> 'CLIConfig'
```

## plural.cli.config.resolve_context

Resolve flags > environment > selected profile config.

```python
plural.cli.config.resolve_context(*, api_url: 'str | None' = None, organization: 'str | None' = None, project: 'str | None' = None, profile: 'str | None' = None, environ: 'Mapping[str, str] | None' = None, config: 'CLIConfig | None' = None, credentials: 'CredentialStore | None' = None) -> 'ResolvedContext'
```

## plural.cli.config.save_config

Persist non-secret config as deterministic TOML.

```python
plural.cli.config.save_config(config: 'CLIConfig', path: 'Path | None' = None) -> 'Path'
```

## plural.cli.auth.AuthClient

Synchronous client for future LastLabs device auth endpoints.

```python
plural.cli.auth.AuthClient(base_url: 'str', *, timeout: 'float' = 15.0, transport: 'httpx.BaseTransport | None' = None) -> 'None'
```

### plural.cli.auth.AuthClient.close

```python
close(self) -> 'None'
```

Close the underlying HTTP connection pool.

### plural.cli.auth.AuthClient.device_start

```python
device_start(self) -> 'DeviceAuthorization'
```

Start a device authorization flow.

### plural.cli.auth.AuthClient.device_poll

```python
device_poll(self, device_code: 'str') -> 'AuthTokens | None'
```

Poll once, returning ``None`` while user authorization is pending.

### plural.cli.auth.AuthClient.login

```python
login(self, *, no_browser: 'bool' = False, open_browser: 'Callable[[str], Any]' = <function open at 0x10bf193a0>, on_device: 'Callable[[DeviceAuthorization], None] | None' = None, sleep: 'Callable[[float], None]' = <built-in function sleep>, monotonic: 'Callable[[], float]' = <built-in function monotonic>) -> 'tuple[DeviceAuthorization, AuthTokens]'
```

Complete device authorization without handling passwords.

### plural.cli.auth.AuthClient.refresh

```python
refresh(self, refresh_token: 'str') -> 'AuthTokens'
```

Exchange a refresh token for new tokens.

### plural.cli.auth.AuthClient.revoke

```python
revoke(self, credential: 'Credential') -> 'None'
```

Revoke available hosted tokens without exposing them.

### plural.cli.auth.AuthClient.status

```python
status(self, credential: 'Credential') -> 'AuthStatus'
```

Return hosted authentication status.

### plural.cli.auth.AuthClient.whoami

```python
whoami(self, credential: 'Credential') -> 'dict[str, Any]'
```

Return the authenticated account payload.

## plural.cli.auth.AuthHTTPError

Sanitized auth API error with a stable code.

```python
plural.cli.auth.AuthHTTPError(message: 'str', *, code: 'ErrorCode', status_code: 'int | None' = None) -> 'None'
```

## plural.cli.auth.AuthStatus

Authentication status from the hosted service.

## plural.cli.auth.AuthTokens

Access and refresh tokens from device or refresh flow.

### plural.cli.auth.AuthTokens.credential

```python
credential(self) -> 'Credential'
```

Convert the token response into stored credentials.

## plural.cli.auth.DeviceAuthorization

Device flow instructions returned by the service.

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

## plural.catalog.models.ModelCatalog

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
plural.catalog.models.ModelCatalog(path: 'str | Path | None' = None, *, entries: 'Iterable[ModelSpec | Mapping[str, Any]]' = (), include_bundled: 'bool' = True) -> 'None'
```

### plural.catalog.models.ModelCatalog.add

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

### plural.catalog.models.ModelCatalog.with_entries

```python
with_entries(self, *entries: 'ModelSpec | Mapping[str, Any]') -> 'ModelCatalog'
```

Return an independent catalog extended with project entries.

```text
Returns:
    A copy containing the effective bundled and project entries.
```

### plural.catalog.models.ModelCatalog.load_bundled

```python
load_bundled(self) -> 'None'
```

Load the package-bundled catalog snapshot.

### plural.catalog.models.ModelCatalog.load_path

```python
load_path(self, path: 'Path') -> 'None'
```

Load a catalog from a filesystem path.

```text
Args:
    path: Path to a JSON catalog file.
```

### plural.catalog.models.ModelCatalog.models

```python
models(self) -> 'list[ModelSpec]'
```

Return all model specs.

```text
Returns:
    A list of :class:`ModelSpec` entries.
```

### plural.catalog.models.ModelCatalog.get

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

### plural.catalog.models.ModelCatalog.require

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

### plural.catalog.models.ModelCatalog.refresh_from_openrouter

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

### plural.catalog.models.ModelCatalog.write_snapshot

```python
write_snapshot(self, path: 'Path') -> 'None'
```

Write the current catalog to a JSON snapshot file.

```text
Args:
    path: Destination path.
```

## plural.catalog.models.ModelSpec

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

### plural.catalog.models.ModelSpec.ordered_endpoints

```python
ordered_endpoints(self) -> 'list[ModelEndpoint]'
```

Return endpoints with US hosts first (Fireworks, then Baseten).

```text
Returns:
    Ordered endpoints, or a single implicit author host when none are listed.
```

### plural.catalog.models.ModelSpec.host_providers

```python
host_providers(self) -> 'list[str]'
```

Return host slugs that can serve this model.

### plural.catalog.models.ModelSpec.pricing_for

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

## plural.catalog.models.estimate_cost

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
plural.catalog.models.estimate_cost(usage: 'Usage', spec: 'ModelSpec | None', *, provider: 'str | None' = None, region: 'str | None' = None) -> 'float | None'
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

## plural.tracing.writer.TraceWriter

Background writer that applies redaction/sampling then sinks traces.

```text
Args:
    sink: Destination sink.
    redactor: Optional redactor applied before write.
    sampler: Optional sampler; defaults to keep-all.
    maxsize: Queue size before ``record`` blocks.
```

```python
plural.tracing.writer.TraceWriter(sink: 'Sink', *, redactor: 'Redactor | None' = None, sampler: 'Sampler | None' = None, maxsize: 'int' = 1000) -> 'None'
```

### plural.tracing.writer.TraceWriter.record

```python
record(self, trace: 'Trace') -> 'None'
```

Enqueue a trace for persistence.

```text
Args:
    trace: Trace to record.
```

### plural.tracing.writer.TraceWriter.label

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

### plural.tracing.writer.TraceWriter.flush

```python
flush(self) -> 'None'
```

Block until the queue is empty.

### plural.tracing.writer.TraceWriter.close

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

## plural.tracing.redaction.Redactor

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
plural.tracing.redaction.Redactor(*, fields: 'set[str] | None' = None, patterns: 'list[str] | None' = None, replacement: 'str' = '[REDACTED]', callables: 'list[Callable[[Trace], Trace]] | None' = None, drop_content: 'bool' = False) -> 'None'
```

### plural.tracing.redaction.Redactor.apply

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

## plural.tracing.redaction.Sampler

Decide whether a trace should be persisted.

```text
Args:
    rate: Probability in ``[0, 1]`` that a trace is kept.
    always_tags: Tags that force retention when present.
```

```python
plural.tracing.redaction.Sampler(rate: 'float' = 1.0, *, always_tags: 'set[str] | None' = None) -> 'None'
```

### plural.tracing.redaction.Sampler.accept

```python
accept(self, trace: 'Trace') -> 'bool'
```

Return whether ``trace`` should be written.

```text
Args:
    trace: Candidate trace.

Returns:
    ``True`` if the trace should be persisted.

Examples:
    >>> Sampler(rate=1.0).accept(Trace(trace_id="t"))
    True
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

## plural.providers.base.aiter_sse_lines

Async variant of :func:`iter_sse_lines`.

```text
Args:
    response: A streaming HTTP response.

Yields:
    JSON (or plain) data strings from ``data:`` lines.
```

```python
plural.providers.base.aiter_sse_lines(response: 'httpx.Response') -> 'AsyncIterator[str]'
```

## plural.providers.base.araise_for_stream_status

Async variant of :func:`raise_for_stream_status`.

```text
Args:
    response: The streaming HTTP response.
    provider: Provider slug.
    model: Model id if known.

Raises:
    PluralError: When the status code indicates failure.
```

```python
plural.providers.base.araise_for_stream_status(response: 'httpx.Response', *, provider: 'str', model: 'str | None' = None) -> 'None'
```

## plural.providers.base.classify_http_error

Map an HTTP error response to a classified :class:`PluralError`.

```text
Args:
    status_code: HTTP status code.
    body: Parsed or raw response body.
    provider: Provider slug.
    model: Model id if known.

Returns:
    A specific :class:`PluralError` subclass instance.

Examples:
    >>> err = classify_http_error(status_code=429, body={}, provider="openai")
    >>> isinstance(err, RateLimitError)
    True
```

```python
plural.providers.base.classify_http_error(*, status_code: 'int', body: 'Any', provider: 'str', model: 'str | None' = None) -> 'PluralError'
```

## plural.providers.base.iter_sse_lines

Yield data payloads from an SSE response.

```text
Args:
    response: A streaming HTTP response.

Yields:
    JSON (or plain) data strings from ``data:`` lines.
```

```python
plural.providers.base.iter_sse_lines(response: 'httpx.Response') -> 'Iterator[str]'
```

## plural.providers.base.map_transport_error

Map httpx transport errors to plural errors.

```text
Args:
    exc: The transport exception.
    provider: Provider slug.
    model: Model id if known.

Returns:
    A classified :class:`PluralError`.
```

```python
plural.providers.base.map_transport_error(exc: 'Exception', *, provider: 'str', model: 'str | None' = None) -> 'PluralError'
```

## plural.providers.base.parse_json_or_text

Parse a response body as JSON, falling back to text.

```text
Args:
    response: The HTTP response.

Returns:
    Parsed JSON or the raw text body.
```

```python
plural.providers.base.parse_json_or_text(response: 'httpx.Response') -> 'Any'
```

## plural.providers.base.raise_for_status

Raise a classified error for non-success HTTP responses.

```text
Args:
    response: The HTTP response.
    provider: Provider slug.
    model: Model id if known.

Raises:
    PluralError: When the status code indicates failure.
```

```python
plural.providers.base.raise_for_status(response: 'httpx.Response', *, provider: 'str', model: 'str | None' = None) -> 'None'
```

## plural.providers.base.raise_for_stream_status

Raise a classified error for a failed streaming response.

```text
A streaming response arrives with its body unread, and touching the body of
an unread response raises from httpx instead of surfacing the host's error.
Reading first is what turns a failed stream into a usable message.

Args:
    response: The streaming HTTP response.
    provider: Provider slug.
    model: Model id if known.

Raises:
    PluralError: When the status code indicates failure.
```

```python
plural.providers.base.raise_for_stream_status(response: 'httpx.Response', *, provider: 'str', model: 'str | None' = None) -> 'None'
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
