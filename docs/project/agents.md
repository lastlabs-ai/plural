---
route: /docs/project/agents
title: "Agents"
order: 65
description: An Agent is a contestant you evaluate, a model plus its instructions. Pick a model, write the instructions, and run it on your Tasks.
audience: all
nav: true
nav_group: Build
outcome: You can find a model, create an Agent, and evaluate it on your Tasks.
---
# Agents

An **Agent** is a contestant: a model from the catalog, plus the instructions you
give it. It is the thing you are evaluating, and it is what ends up on a leaderboard.

Every Agent also has a [Harness](harnesses.md), the way the contestant plays: the
loop that shows the model what it can see, asks it what to do, and carries out the
move. You rarely have to think about it. If you don't pick one, Plural uses its own
built-in loop.

## Why make more than one

The point of an Agent is comparison. Create one Agent for each setup you want to
try, then run them all on the same Tasks with the same grading. For example:

- `careful`: a model told to read the policy before acting.
- `concise`: the same model, told to finish quickly.
- `support-claude`: a different model, playing through Claude Code.

Because the Tasks and scoring stay the same, any difference in the results comes
from the Agent.

Agents are not tied to one world. The same Agent can play Wordle in one run and work
support tickets in the next.

## What an Agent sees

An Agent only ever sees two things: the Task's instructions and what its actions
return. It never sees the score, the
rewards, the hidden State, or anything the grader knows. That keeps the test fair.

## Find a model

Start by listing the model IDs you may run:

```bash
plural model list
```

What you see depends on who you are:

- **Signed out**, you see the catalog bundled with Plural.
- **Signed in, outside an organization**, you see the whole catalog.
- **Signed in, in an organization**, you see the models your organization offers:
  models it serves from its own cloud endpoints, its private models, and any models
  an admin has explicitly allowed. If the organization has configured none of these,
  you see the whole catalog.

Run `plural model list --all` to see every catalog model. Models your organization
does not permit are marked `not permitted`; the service refuses them for runs,
reruns, and model calls through the gateway.

You can also browse the model Catalog in the web app, with model cards and prices.

From Python, a `Client` exposes the same catalog. `Client()` needs a Plural API key,
stored with `plural auth login --api-key-stdin` or set as `PLURAL_API_KEY`:

```python
from plural import Client

client = Client()
for model in client.catalog.models():
    print(model.id)
```

Calling a model requires credentials and an endpoint that supports it. See
[Quickstart](../getting-started.md) for authentication.

## Create your Agent

Choose a model ID from the catalog and write the instructions:

```python
from plural import Agent

agent = Agent(
    name="support-assistant",
    model="openai/gpt-5.6-luna",
    instructions=(
        "Inspect the ticket and follow its support policy. "
        "Use the available actions to categorize it, draft a reply, and resolve it. "
        "Stop when the Environment reports that the ticket is done."
    ),
)
```

This Agent has no Harness, so it uses `native`, Plural's built-in tool loop. You do
not need a custom Harness to get started.

> **Tip:** Task instructions describe *this particular assignment*. Agent
> instructions describe *how to approach work in general*, across every Task. Keep
> them clear, avoid rules that conflict, and say when to stop.

### Save the Agent in a project

In a project, an Agent is a folder under `agents/` named after it, holding one
`agent.yaml` file. Create one with:

```bash
plural agent init support-assistant --model openai/gpt-5.6-luna
```

`agent.yaml` takes the same fields as `Agent`:

```yaml
name: support-assistant
version: 0.1.0
model: openai/gpt-5.6-luna
instructions: >-
  Inspect the ticket and follow its support policy. Use the available actions
  to categorize it, draft a reply, and resolve it. Stop when the Environment
  reports that the ticket is done.
```

Check it, then save a private copy to your hosted project:

```bash
plural agent validate support-assistant
plural agent push support-assistant --with-deps
```

`validate` checks the model ID, the Harness, and its options. `push` saves a private
revision, together with any project Harness the Agent uses that is not hosted yet.
Pushing never makes anything public.

The fields, for reference:

- `name` must match the folder name, which is also the hosted slug. An optional
  `title` sets the display name.
- `harness` is optional. It names a Harness in the project's `harnesses/` folder, or a
  built-in (`hermes`, `claude-code`, or `codex`).
- `harness_config` sets the Harness's options. A built-in Harness checks them; a
  Harness of your own reads them in `self.config`, over the `config:` in its
  `harness.yaml`. Two Agents can share one Harness and differ only in options.
- `auth: none` marks an Agent whose Harness never calls a model, so it runs
  without credentials.
- `endpoint` and `endpoint_key` point the Agent at its own model server; see
  [Use your own endpoint](#use-your-own-endpoint).
- `external` points the Agent at an agent service you run yourself; see
  [External Agents](external-agents.md).

Model keys and other credentials are never written in `agent.yaml`.

## Use a different Harness

To have the same kind of contestant play a different way, attach a built-in Harness
by name, or pass an instance of a custom `Harness` subclass from the
[Harnesses guide](harnesses.md#build-a-custom-harness):

```python
claude = Agent(
    name="support-claude",
    model="anthropic/claude-sonnet-5",
    instructions="Follow the support policy and finish the ticket using the available tools.",
    harness="claude-code",
    harness_config={"reasoning_effort": "high"},
)

custom = Agent(
    name="support-custom-loop",
    model="openai/gpt-5.6-luna",
    instructions="Follow the support policy and finish the ticket using the available tools.",
    harness=harness,
)
```

The Harness runs inside the Runtime (the place the world runs, usually a Docker
container) chosen by the Task's Environment. Built-ins install their command-line
tool there. A custom Harness still needs its dependencies in that Runtime.

Model authentication comes from the Job's Client, not from the Agent. A custom
Harness declares the environment variable names it reads, and the Agent's
`secrets` grants a subset of those names. If one of those names is missing when
the run starts, the error lists it and does not include the value. See
[Harnesses](harnesses.md).

## Use your own endpoint

To evaluate a model that isn't in the catalog, such as a fine-tuned model you serve
yourself, give the Agent the address of any OpenAI-compatible server. Its model calls
then go straight there, not through the Plural gateway:

```python
from plural import Agent

tuned = Agent(
    name="support-tuned",
    model="support-tuned-v3",
    endpoint="https://models.example.com/v1",
    endpoint_key="TUNED_API_KEY",
    instructions="Follow the support policy and finish the ticket using the available tools.",
)
```

```yaml
name: support-tuned
version: 0.1.0
model: support-tuned-v3
endpoint: https://models.example.com/v1
endpoint_key: TUNED_API_KEY
instructions: Follow the support policy and finish the ticket using the available tools.
```

- `model` is whatever name your server expects. It isn't checked against the catalog.
- `endpoint` is the server's base URL; Plural calls `{endpoint}/chat/completions`.
- `endpoint_key` is optional. It names the secret holding the server's API key, never
  the key itself. Export it, or store it in the hosted project with
  `plural secret set NAME`, before `plural run`. It is sent only as the request's
  bearer token, and a missing value stops the run before it starts.
- An endpoint Agent uses the native Harness unless you give it a custom one. A custom
  Harness reaches the endpoint through `agent.complete`, with the same key. A built-in
  Harness such as `codex` calls models through the gateway, so it can't use an
  endpoint.
- An endpoint Agent can't set `provider` or `fallback_models`, and takes `secrets` only
  for a custom Harness that declares them.
- A Job whose Agents all use their own endpoints, or `auth: none`, needs no
  Plural API key. The endpoint must be reachable from the Runtime.

This is the usual way to check a trained model against the same Benchmark you used
for the baseline; see [Training and RL](../running/training.md).

### Check which model answers

An endpoint's `model` is only a name, and many local servers answer to a name they
don't have. llama.cpp serves its one loaded model whatever a request asks for, and
`mlx_lm.server` loads whatever repository the request names. So before a run, Plural
asks the server what it has loaded and shows you what it found:

```console
$ plural run -b support-triage -a local
Agent local runs a local model you have not accepted yet:
  server: ollama 0.12.0 at http://localhost:11434/v1
  requested: qwen3:8b
  weights: ollama:qwen3:8b@500a1f067a9f
  parameters: 8.2B
  quantization: Q4_K_M
  fingerprint: SHA256:Rtzr8m0c... (from the model the server reports loaded)
Is this the model you mean to evaluate? [y/N]:
```

Plural reads Ollama's, vLLM's, llama.cpp's, and LM Studio's reports of the loaded
model. `mlx_lm.server` and other servers report nothing about it, so Plural
fingerprints the model by its answers to a few fixed prompts. When the server runs on
this machine, Plural also reads the named model's weights from the Hugging Face cache
and counts their parameters. Weights in the cache only show what could be loaded,
while the answers show what actually responds, so the fingerprint uses both. A server
on another machine is identified by its answers alone, and the prompt says so. A
warning appears when the name and the weights disagree, such as `qwen:8b` answered by
27 billion parameters.

Plural remembers a fingerprint you accept, the way SSH remembers a host key, so the
next run of the same model goes ahead without asking. When the fingerprint changes:

- If the weights are different, the run warns that the model has changed and asks
  again.
- If the weights are the same but the server's version is new, the run says that
  serving changed and asks again.
- If the model answers exactly like one you accepted under another name, the run
  stops, naming that model, because the server is likely running it under this
  name.

`plural run --yes` uses the model without asking or remembering, even in that last
case, for scripts and CI.

In Python, `Job` refuses an endpoint model whose fingerprint you haven't accepted, and
its error lists what it found. Accept it once with `plural run`, or pass
`allow_local_models=True`:

```python
Job(benchmark, agents=[tuned], allow_local_models=True).run()
```

Each Trial records what it found as `TrialResult.model_identity`, with how the run
came to trust it. Before each Trial starts, Plural checks the fingerprint again, asking
the fixed prompts again where the answers are part of it, and a Trial whose model
changed mid-Job fails without running. This makes a mislabeled
run visible. It can't prove what a server you don't control runs.

An `endpoint` Agent's calls bypass Plural, so they never appear in the account's
**Usage** page and never draw on credits. The Trial still records each call's tokens
from the `usage` the server returns, which Ollama, vLLM, llama.cpp, LM Studio, and
`mlx_lm.server` all do. A call to a server on this machine or a private network costs
$0. Plural can't know what a remote server charges, so its cost is left unreported.
To have the calls observed instead, an organization admin can add the server under
**Organization → Providers → Endpoints** in the web app. Calls the gateway routes there
are recorded on the Trial with `billing="organization"` and a reference cost, and never
draw on credits.

## Bring an agent that runs elsewhere

An agent you already run as a web service can be evaluated as it is, without moving
its code into a Harness. Plural calls it once per episode, observes every action it
takes, and scores its answer. See [External Agents](external-agents.md).

## Give the Agent credentials

When an App acts as a user of a real system, such as a CRM, it needs that user's
token. The Agent says which tokens it needs; **each person saves their own**. You and
a coworker can run the same Agent in the same project, each as yourselves, with your
own permissions, and every Trial records whose token acted.

List each credential in `agent.yaml`, by the name the App declares, with the scopes the
token grants:

```yaml
name: sales-bot
version: 0.1.0
model: openai/gpt-5.6
credentials:
  CRM_TOKEN:
    scopes: [read:accounts, write:opportunities]
    description: Your Salesforce token.
```

Then save your own value once, from the CLI or under **Credentials** on your Profile:

```bash
plural credential set CRM_TOKEN
```

Every Agent you run that needs `CRM_TOKEN` now uses yours. Your coworker runs the same
command with their token, and their runs use theirs. Values are encrypted, never shown
again, and only you can use yours.

- The value goes only to the process that runs the Apps. The model and its Harness
  never receive it, and it is never written to the project or the Trial.
- A run stops before it starts when an App needs a credential the Agent doesn't
  declare, or a scope it doesn't list, or when you have no value for it.

:::details Where a value can come from
`plural run` uses, in order, a value you saved to your account, then one exported in
your environment. CI, which signs in with a project API key rather than as you, can't
read anyone's saved credentials, so export the values there instead. In Python, pass
them to the Job by Agent name:

```python
agent = Agent(model="openai/gpt-5.6", name="sales-bot",
              credentials={"CRM_TOKEN": {"scopes": ["read:accounts"]}})
Job(task, [agent], credentials={"sales-bot": {"CRM_TOKEN": token}}).run()
```

`plural credential list` shows the names you have saved, never the values, and
`plural credential delete NAME` deletes one.
:::

:::details What each Trial records
Per credential: the App, the Agent and its revision, the scopes, where the value came
from (`hosted`, `environment`, or `provided` from Python), a short fingerprint of the
value, and, for a saved value, which user saved it. `plural trial show` prints it.
`scopes` is what you declare the token may do; the system that issued the token
enforces what it can really do.
:::

## Evaluate the Agent

From the command line, run a saved Agent on a Task, or try a model without saving an
Agent first:

```bash
plural run --task ticket-1 --agent support-assistant
plural run --task ticket-1 --model openai/gpt-5.6-luna
```

Every run is a new Job, one run you start. Add `--dry-run` to see the plan without
calling a model.

A few things to know:

- A run is recorded under `.plural/jobs/`. A run with `--record` is also recorded in
  the hosted project, where you can see it in the web app under Jobs.
- A live local run sends every model call through the Plural gateway, so it needs a
  Plural API key, such as the one `plural auth login` stores. An Agent with its own
  `endpoint` is the exception.
- To turn conversations an agent already had into Tasks, see
  [Start from traces](../start/from-traces.md).

In Python, given a Task named `task`, run the Agent with your Client:

```python
from plural import Job

job = Job(task, agents=[agent], client=client)
print(job.plan.trial_count)
result = job.run()
```

To compare Agents across many Tasks at once, use a [Benchmark](benchmarks.md).

## Make a useful comparison

Change one thing at a time, so you know what caused a difference:

- **Model:** keep the Harness and instructions the same.
- **Instructions:** keep the model and Harness the same.
- **Harness:** keep the model and Task set the same.

Run repeated attempts to see how consistent the results are. Look at the actions the
Agent took and the grader's evidence, not just the final score.

> **Good to know:** Leave `fallback_models` unset when comparing individual models.
> Otherwise a different model can quietly finish the work and take the credit.

Advanced endpoint setup and routing work to the model you choose are covered in
[Providers and integrations](../reference/integrations.md).
