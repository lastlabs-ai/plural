---
route: /docs/project/external-agents
title: "External Agents"
order: 66
description: Evaluate an agent that already runs as its own service. Plural calls it once per episode, observes every action it takes, and scores its answer.
audience: all
nav: true
nav_group: Build
outcome: You can point an Agent at your own agent service, run it on your Tasks, and read what Plural observed next to what the agent reported.
---
# External Agents

Most Agents are a model plus a [Harness](harnesses.md) that Plural runs inside the
Task's Runtime. An **External Agent** is different: it is an agent you already built
and already run somewhere else, as a web service. Plural doesn't install it, doesn't
hash its code, and never sees its prompts. It calls the service once per episode, and
the service works the Task through the same actions any Agent gets.

Use one when:

- You sell or operate an agent and want it scored on someone else's Tasks without
  handing over its code.
- A team built Apps and Tasks, and other teams bring their own agents to them.
- The agent depends on infrastructure that can't move into a Runtime.

Built the agent with LangGraph, the OpenAI Agents SDK, or OpenTelemetry? See
[Trace an External Agent](external-tracing.md) to register it, trace its runs, and
serve episodes with `plural[external]`. To score an agent that only answers, on Tasks
with answer keys and no Apps, follow
[Connect an External Agent](../guides/connect-external-agent.md).

Everything that decides the score stays with you. The Apps, their State, and the
Verifiers run in the Runtime your Job owns, on your laptop, in CI, or in a sandbox.
The agent only ever receives the Task, the actions, and the Task's files.

## How an episode runs

1. `plural run` resets the Environment and opens a short-lived HTTPS address for the
   episode.
2. It sends the agent service one signed `POST` with the Task, the actions, the file
   names, that address, and a token for it.
3. The agent takes actions and reads files at that address. Each action runs through
   the App host, exactly as a Harness's would, and Plural records it.
4. The agent reports its own trace, then finishes with its answer.
5. The token stops working, and the Verifiers score the episode.

The agent can also answer straight away, in its reply to the first request, if it
needs no actions at all.

## A worked example: counting doors on a drawing

A construction company wants to know which takeoff agent counts doors on an
architectural drawing most accurately. It doesn't want to see the vendors' code, and
the vendors must never see the answer key.

The Task gives the drawing as a file. A small App holds what the agent submits, and the
Verifier compares it with the count only the Verifier knows:

```python
from plural import App, DeterministicVerifier, Environment, Resource, Runtime, State, Task
from plural import VerifierOutput, action


class Count(State):
    doors: int | None = None


class Takeoff(App[Count]):
    """Record what the drawing shows."""

    @action
    def submit(self, doors: int) -> str:
        """Submit the number of doors on the drawing."""
        self.state.doors = doors
        return "recorded"

    def terminated(self) -> bool:
        return self.state.doors is not None


def doors(episode) -> VerifierOutput:
    return VerifierOutput(score=float(episode.state.get("doors") == 12))


task = Task(
    name="count-doors-a201",
    instructions="Count the doors on drawing A-201 and submit the number.",
    environment=Environment(name="drawings", apps=[Takeoff()], runtime=Runtime.local()),
    resources=[Resource.from_file("drawings/A-201.pdf")],
    verifiers=[DeterministicVerifier(name="doors", check=doors)],
)
```

The drawing can be any file type: PDF, Word, images, code, or text. See
[Task files](tasks.md).

## Point an Agent at the service

Create the Agent and a signing key, then give the key to the service:

```bash
plural agent init takeoff --external https://agents.acme.dev/plural
plural agent key
```

`agent init` writes `agents/takeoff/agent.yaml`:

```yaml
name: takeoff
version: 0.1.0
model: acme/takeoff
external:
  url: https://agents.acme.dev/plural
  signing_key: TAKEOFF_SIGNING_KEY
  version: 0.1.0
```

- `url` is where the Job sends each episode. It must be `https`, or `http` only on
  `localhost`, and it can't carry a user name or password.
- `signing_key` names the secret holding the key, never the key itself. Export it, or
  store it with `plural secret set TAKEOFF_SIGNING_KEY`. The service keeps the same
  value as `PLURAL_SIGNING_KEY`.
- `version` is the service's release label. It and the `url` are the Agent's
  identity, so a new release, or a new address, is a new revision on the leaderboard.
  The key and the CA bundle are not part of it.
- `ca_bundle` is optional: a CA file for a service with a private certificate.
- `model` is the name the results show. It isn't checked against the catalog.

An External Agent takes no Harness, endpoint, provider, sampling settings, or secrets.
Those belong to the service.

Check that the Job can reach the service and that the service checks signatures:

```bash
plural agent test takeoff
```

It sends a signed ping and reports the status, whether TLS was used, and the time it
took. Any `2xx` reply passes.

## Write the service

`plural.external` gives the service its half in a few lines. This FastAPI handler
verifies the request, accepts it at once, and works the episode in the background:

```python
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from plural.external import Episode, SignatureError, verify_request

app = FastAPI()


def count_doors(episode: Episode) -> None:
    drawing = episode.read("task-resources/A-201.pdf")
    doors = my_takeoff_model(drawing)
    episode.act("submit", doors=doors)
    episode.trace(my_trace_as_atif())
    episode.finish(f"{doors} doors")


@app.post("/plural")
async def plural(request: Request, background: BackgroundTasks) -> Response:
    try:
        message = verify_request(await request.body(), request.headers)
    except SignatureError:
        raise HTTPException(status_code=401)
    if message.type == "episode.start":
        background.add_task(count_doors, Episode(message))
    return Response(status_code=202)
```

- `verify_request` reads the key from `PLURAL_SIGNING_KEY` and refuses a request that
  isn't signed with it, is more than five minutes old, or was received before.
- `episode.task` has the instructions, `episode.actions` the actions with their
  parameters, and `episode.files` the file names.
- `episode.tools()` describes the actions in the shape model APIs take for tool
  calls.
- `episode.act(name, **arguments)` takes one action and returns what it observed.
  After the action that ends the episode, `episode.done` is true.
- `episode.trace(document)` reports the agent's own trace, as an
  [ATIF](../running/traces.md) document.
- `episode.finish(answer)` ends the episode. It can be sent once. Verifiers read the
  answer as [`episode.answer`](verifiers.md#check-the-final-answer), so a Task with
  a bare Environment, one with no Apps, is scored on the answer alone.

The episode also has an MCP server at `episode.start.urls.mcp`, with each action as a
tool, for an agent that already speaks MCP. It takes the same token.

To call models through Plural, use `episode.start.gateway` when it is present: a
gateway URL and a key that works for this episode only. It is there only for a run
with `--record`, and the key is never your own.

## Run it

```bash
plural run --task count-doors-a201 --agent takeoff
```

The Job serves the episode on `127.0.0.1` by default, which suits a service on the
same machine. For a service elsewhere, serve on an address it can reach, with TLS:

```bash
plural run --task count-doors-a201 --agent takeoff \
  --listen 0.0.0.0:8443 --public-url https://runner.example.com:8443 \
  --tls-cert runner.pem --tls-key runner-key.pem
```

The Job refuses to listen beyond loopback without a certificate. `--public-url` is the
address the service is told to use, for a Job behind a proxy or inside a company
network.

External Agents run Tasks one Agent works alone, in `eval` Jobs and Benchmarks. They
can't take a seat in a [multi-agent Task](multi-agent.md) or be trained.

## What the results show

Each Trial records what Plural observed, separately from what the agent reported:

- **Observed:** every action, its arguments, and what it returned, from the App host,
  in the episode log. The score is computed from the App's State, never from anything
  the agent says.
- **Self-reported:** the agent's trace, kept as `agent-trace.json` and shown as
  *Agent's own trace* on the Trial's Trajectory tab, as a conversation.

Plural compares the two and lists each disagreement as an integrity finding:

| Finding | Meaning |
| --- | --- |
| `no_trace` | The agent reported no trace. |
| `actions_not_observed` | The trace claims more calls of an action than Plural saw. |
| `actions_not_traced` | Plural saw calls of an action that the trace leaves out. |
| `answer_differs` | The trace's final message isn't the answer the agent submitted. |
| `trace_outside_episode` | Trace steps are timed outside the episode. |

Findings appear in `plural trial show` and on the Trial page. They are evidence for a
person to read; they never change a score. Agent results are marked **External** in
Trial lists and in Benchmark results.

## Security

- **Every request is signed.** The Job signs each request with HMAC-SHA256 over its
  id, time, and body, in the Standard Webhooks format, so the service can tell it
  came from your Job and wasn't replayed.
- **Each episode has its own token.** It is 256 random bits, works only for that
  episode's address, and stops working when the episode finishes or its time runs
  out. The Job stores only its hash, and masks it in everything it writes.
- **Nothing that grades reaches the agent.** It never receives the score, rewards,
  App State, Verifier code, or secrets. A Task whose `info` holds an answer key is
  refused before the episode starts.
- **Bodies are capped.** Actions, traces, and answers each have a size limit, and the
  Job refuses redirects from the service.
- **Your key stays yours.** A recorded run gives the agent a gateway key for that
  execution alone, revoked when it finishes. Without `--record`, the agent gets no
  gateway at all.
