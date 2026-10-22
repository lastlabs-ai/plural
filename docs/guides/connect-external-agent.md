---
route: /docs/guides/connect-external-agent
title: Connect an External Agent
order: 33
description: Benchmark an agent you built with any framework and run yourself. Serve it to Plural, write Tasks with answer keys in an Environment with no Apps, and run a Benchmark against it.
audience: all
nav: true
nav_group: Build
outcome: An agent running as your own service is scored on a Benchmark of your Tasks, with what Plural observed and what the agent reported side by side on each Trial.
---
# Connect an External Agent

Your agent already exists. Maybe it's built with LangGraph or the OpenAI Agents SDK,
and it runs on your own infrastructure. This guide benchmarks it without moving it.
The agent stays a web service, Plural sends it one signed request per episode, and
Verifiers score its answers against answer keys it never sees.

The example is a support-triage agent. It reads a ticket and replies with the team
that should handle it. There's nothing for it to act on, so its Environment has no
Apps, and each Task is scored on the answer alone. For agents that act on real
systems, see [External Agents](../project/external-agents.md#a-worked-example-counting-doors-on-a-drawing).

There are two sides, often owned by different people:

- **The agent's side:** the service, with `plural[external]` installed.
- **The project's side:** a Plural project with the Tasks, Verifiers, and
  Benchmark. Answer keys live here, and the agent never sees them.

## 1. Serve the agent

On the agent's side, install the package and generate its config:

```bash
pip install "plural[external]"
plural external init support-bot --model acme/support-v3 \
  --url http://localhost:8765/plural
```

`plural-agent.yaml` holds the agent's name, version, and URL, and what its traces
record. For running on Tasks only, set `production: false` under `tracing`. Then the
service needs no Plural API key. See
[Trace an External Agent](../project/external-tracing.md) for every field.

Wrap the agent in the episode endpoint. Whatever `work` returns is its answer:

```python
# service.py
from plural.external import serve
from plural.external.langchain import PluralCallbackHandler

from support_bot import graph


def work(episode, run):
    state = graph.invoke(
        {"messages": [("user", episode.task.instructions)]},
        config={"callbacks": [PluralCallbackHandler()]},
    )
    return state["messages"][-1].content


app = serve.app(work)
```

The callback handler records each model and tool call as the agent's own trace. Use
the [adapter for your framework](../project/external-tracing.md#3-trace-the-agent), or
none at all. Then make a signing key, and start the service with it:

```bash
plural agent key
export PLURAL_SIGNING_KEY=whsec_...
uvicorn service:app --port 8765
```

The endpoint refuses any request that isn't signed with this key.

## 2. Add the Agent to the project

On the project's side, create the Agent from the service's URL, and give it the same
key:

```bash
plural agent init support-bot --external http://localhost:8765/plural
export SUPPORT_BOT_SIGNING_KEY=whsec_...
plural agent test support-bot
```

```text
✓ support-bot answered the signed ping with 200 in 0.03s over plain http.
```

`agents/support-bot/agent.yaml` names the variable holding the key, never the key.
Store it with `plural secret set SUPPORT_BOT_SIGNING_KEY` to keep it out of your
shell. The agent's owner can register it in a hosted project instead, from the
service, with `plural external register`.

## 3. Make an Environment with no Apps

The agent only answers, so the Environment needs nothing but a Runtime and limits.
Write `environments/answers/environment.yaml`:

```yaml
name: answers
description: The agent replies with its answer. There are no Apps to act on.
readme: README.md
runtime:
  provider: local
limits:
  max_seconds: 120
```

In its `README.md`, say what the agent is asked to do. `plural env validate answers`
checks both files.

## 4. Score the answer

A Verifier compares the agent's answer, `episode.answer`, with the Task's answer key,
`episode.expected`:

```bash
plural verifier init right-team
```

```python
# verifiers/right-team/verify.py
from plural import Episode, VerifierOutput


def check(episode: Episode) -> VerifierOutput:
    answer = str(episode.answer or "").strip().lower()
    return VerifierOutput(
        score=float(answer == episode.expected),
        evidence=[f"answered {answer!r}, expected {episode.expected!r}"],
    )
```

One Verifier scores every Task, each against its own key. For answers that can be
right in more than one way, use an [AgentVerifier](../project/verifiers.md#agentverifier)
instead. It is shown the answer key as the reference.

## 5. Write the Tasks

```bash
plural task init duplicate-charge --environment answers --verifier right-team
```

Put the question in `tasks/duplicate-charge/instruction.md`:

```text
A customer was charged twice for invoice INV-102. Reply with the team that should
handle it: billing, shipping, or support.
```

Add the answer key to `tasks/duplicate-charge/task.yaml`:

```yaml
expected: billing
```

`expected` is never sent to the agent. `info` and `metadata` are, so never put an
answer there. A Job with an External Agent refuses to start a Task whose `info` has a
key such as `expected` or `score`.

For many Tasks, write the rest as cases. Each one copies `duplicate-charge` with its
own question and answer:

```json
{"name": "lost-parcel", "instructions": "A customer says their parcel never arrived. Reply with the team that should handle it: billing, shipping, or support.", "expected": "shipping"}
{"name": "password-reset", "instructions": "A customer can't sign in after resetting their password. Reply with the team that should handle it: billing, shipping, or support.", "expected": "support"}
```

```bash
plural task cases duplicate-charge cases.jsonl
```

## 6. Make a Benchmark

```bash
plural benchmark init triage
plural benchmark add duplicate-charge lost-parcel password-reset --benchmark triage
```

Fill in the Benchmark's purpose and what its score means, in
`benchmarks/triage/benchmark.yaml`. See [Benchmarks](../project/benchmarks.md).

## 7. Run it

```bash
plural run --benchmark triage --agent support-bot
```

```text
Running benchmark/triage with support-bot (acme/support-v3) locally: 3 Trials.
  [1/3] duplicate-charge  succeeded  score=1.000
  [2/3] lost-parcel       succeeded  score=1.000
  [3/3] password-reset    succeeded  score=0.000
  support-bot: mean score 0.667 over 3 Trials, 3 succeeded, coverage 100%
```

`plural trial show` gives each Trial's evidence, such as
`answered 'billing', expected 'support'`. Add `--record` to keep the Job in your
hosted project. On each Trial page, the Trajectory tab then shows **Observed by
Plural** and the **Agent's own trace**, a conversation of its model and tool calls.
The Overview lists any place the two disagree.

The Job serves episodes on `127.0.0.1`, which suits a service on the same machine. For
a service elsewhere, see
[Run it](../project/external-agents.md#run-it) for `--listen`, `--public-url`, and
TLS.

## Troubleshooting

| Message | What to do |
| --- | --- |
| `Could not reach the external Agent` | The service isn't running at `external.url`, or the Job can't reach that address. |
| `refused the episode with HTTP 401` | The two sides have different signing keys. |
| `The Task's info has 'expected'` | Move the answer from `info` to the Task's `expected`. |
| `The external Agent did not finish within max_seconds` | Raise `limits.max_seconds` in the Environment, or make `work` return sooner. |
| A score of 0 with `answered ''` | `work` returned nothing. Return the answer, or call `run.finish(answer)`. |
