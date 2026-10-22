---
route: /docs/project/external-tracing
title: "Trace an External Agent"
order: 67
description: Register an agent built with any framework, trace its runs to Plural from wherever it runs, and evaluate it on your Tasks with nothing to rewrite.
audience: all
nav: true
nav_group: Build
outcome: Your agent is registered with Plural, its runs are traced with the fields you chose, and the same code answers Plural Jobs as an External Agent.
---
# Trace an External Agent

An agent built with LangGraph, the OpenAI Agents SDK, or your own code can stay
exactly where it runs. Install `plural[external]`, add one config file and a line or
two of setup, and Plural records each run as a trace. Point a Job at the same service
and it becomes an [External Agent](external-agents.md), scored on your Tasks.

```bash
pip install "plural[external]"
```

The package is the agent's half of Plural: the config, a tracer, adapters for
common frameworks, and an endpoint that takes episodes from Jobs. It never needs your
Tasks, Verifiers, or Apps.

## 1. Generate the config

```bash
plural external init support-bot --model acme/support-v3 \
  --url https://agents.acme.dev/plural
```

This writes `plural-agent.yaml`, with a comment on every field. Edit it, then
commit it beside the agent:

```yaml
agent:
  name: support-bot
  version: 0.1.0
  model: acme/support-v3
  url: https://agents.acme.dev/plural
  signing_key: PLURAL_SIGNING_KEY
  ca_bundle: null

plural:
  api_key: PLURAL_API_KEY
  project: null
  api_url: null

tracing:
  enabled: true
  production: true
  sample_rate: 1.0
  flush: end
  capture:
    messages: true
    system_prompt: true
    reasoning: true
    tool_arguments: true
    tool_results: true
    usage: true
    metadata: true
  redact: []
  max_trace_bytes: 4000000
  tags: {}
```

The file names environment variables, never values. `plural.api_key` and
`agent.signing_key` are the names of the variables that hold your Plural API key and
the Jobs' signing key. The tracer looks for `plural-agent.yaml` in the working
directory, or at the path in `PLURAL_AGENT_CONFIG`.

### Fields every trace carries

Some fields are always written, because a trace means nothing without them: the
trace id, `agent.name` and `agent.version`, when the run started and ended, its
status, and each step's source, time, and model. Everything else is optional, and
`capture` decides it:

| `capture` | What it keeps |
| --- | --- |
| `messages` | The text of user and agent messages. |
| `system_prompt` | The system prompt. |
| `reasoning` | A model's reasoning, when it reports any. |
| `tool_arguments` | What each tool was called with. |
| `tool_results` | What each tool returned. |
| `usage` | Tokens, cost, and latency of each model call. |
| `metadata` | Values you attach with `run.metadata(...)`. |

A field turned off is never written, so it never leaves your service. `redact` takes
regular expressions, and replaces every match with `[REDACTED]` in every string the
trace holds. Your API key and signing key are always redacted. A trace larger than
`max_trace_bytes` keeps its first steps and says how many it dropped.

### When traces are written

`flush` decides when the trace is sent:

- `end`, the default, writes it once, when the run finishes.
- `interval:5` also writes it every 5 seconds while the run is going.
- `steps:10` also writes it every 10 steps.

A write before the end is marked in progress, and the next one replaces it. The
final write can't be replaced. Writes happen on a background thread, so a slow
network never slows the agent. Call `tracer().flush()` before a short-lived process
exits.

### Overriding the file

Each setting has a default in the file, and two ways to change it per deploy or per
run:

| Variable | Overrides |
| --- | --- |
| `PLURAL_TRACE_ENABLED` | `tracing.enabled` |
| `PLURAL_TRACE_PRODUCTION` | `tracing.production` |
| `PLURAL_TRACE_SAMPLE_RATE` | `tracing.sample_rate` |
| `PLURAL_TRACE_FLUSH` | `tracing.flush` |
| `PLURAL_AGENT_VERSION` | `agent.version`, for setting it on each release |

In code, `tracer().run(flush="steps:5", capture={"tool_results": False})` changes
one run only.

## 2. Register the agent

```bash
export PLURAL_API_KEY=...
plural external register
plural external check
```

`register` creates the Agent in your project from the config, or adds a revision when
the version or URL changed. It needs `agent.url` and `agent.model`. `check` confirms
the config loads, the API key is set, the Agent is registered, and the service
answers a signed ping.

Production tracing needs `PLURAL_API_KEY` wherever the agent runs. Without it, the
tracer refuses to start and names the variable. To trace only the episodes of Plural
Jobs, set `production: false`. Those traces go to the Job with each episode's own
credential, so the service needs no API key at all.

## 3. Trace the agent

Pick the adapter for your framework. Each one turns a framework's run into one
Plural trace, with its model calls, tool calls, and final answer. Every adapter takes
an optional `Tracer`, and uses `tracer()`, the one for `plural-agent.yaml`, when you
pass none.

### OpenTelemetry

For any framework that emits OpenTelemetry spans, including OpenLLMetry and
OpenInference instrumentations:

```python
from plural.external import otel

otel.instrument()
```

`instrument` adds a span processor to the global tracer provider, and installs one
when there is none. It reads the GenAI semantic conventions, OpenLLMetry's
`gen_ai.prompt` attributes, and OpenInference's `llm.input_messages`. Each root span is
one run; a root span that ends in error is a failed run.

### LangChain and LangGraph

```python
from plural.external.langchain import PluralCallbackHandler

graph.invoke(state, config={"callbacks": [PluralCallbackHandler()]})
```

The handler records each chat model call and tool call. The final answer is the last
AI message of a LangGraph state, or the chain's `output`, `answer`, or `result`.

### OpenAI Agents SDK

```python
from plural.external import openai_agents

openai_agents.install()
```

### Anything else

Record the run yourself. This is also how the adapters work underneath:

```python
from plural.external import ToolCall, tracer

with tracer().run(input=question) as run:
    reply = client.chat.completions.create(model=model, messages=messages)
    run.llm(
        model=model,
        messages=messages,
        output=reply.choices[0].message.content,
        tool_calls=[ToolCall(id="c1", name="lookup", arguments={"id": 42})],
        usage={"prompt_tokens": 812, "completion_tokens": 64},
    )
    run.tool("lookup", arguments={"id": 42}, result=order, call_id="c1")
    run.finish(answer)
```

A run that raises is recorded as failed, with the error. `run.metadata(...)`
attaches values to the trace.

## 4. Take episodes from Jobs

To evaluate the agent on Tasks, serve the episode endpoint at `agent.url`:

```python
from plural.external import serve


def work(episode, run):
    return my_agent.invoke(episode.task.instructions)


app = serve.app(work)  # uvicorn service:app
```

For an existing FastAPI or Starlette app, mount `serve.endpoint(work)` on a `POST`
route instead.

The endpoint checks every request's signature, answers pings, and runs `work` in the
background for each episode. What `work` returns is the agent's answer. Inside `work`,
every adapter records into that episode's run, so the trace reaches the Job with
nothing more to set up. The Task's instructions are its first message.

Use `episode.act(...)` for Tasks whose Environment has Apps. For a bare Environment,
with no Apps, the answer is all there is to score: a Verifier reads it as
[`episode.answer`](verifiers.md).

## What the Trial shows

On a Trial's Trajectory tab, **Observed by Plural** shows what Plural recorded: every
action through the App host, which is what the score comes from. **Agent's own trace**
shows the agent's trace as a conversation: its prompts, model calls, tool calls, and
answer. Plural can't verify that one, so the Overview lists every place the two
disagree. See [What the results show](external-agents.md#what-the-results-show).

Production traces appear under **Traces**, linked to the registered Agent. A trace
still being written is marked in progress.

## Security

- **Keys stay in the environment.** The config names variables, and the tracer reads
  them at start. Neither key is ever written to a trace.
- **Episode traces need no API key.** They go to the Job that sent the episode, with
  that episode's own token, which stops working when the episode ends.
- **You choose what leaves the service.** Fields turned off in `capture` are never
  recorded, and `redact` runs before anything is sent.
- **Nothing that grades reaches the agent.** Scores, rewards, App State, and Verifier
  code stay with the Job, as for every External Agent.
