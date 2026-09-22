---
route: /docs/project/environments
title: Environments
order: 30
description: Define what an agent can see and do, choose where it runs, and build a repeatable workflow for your Tasks.
audience: all
nav: true
nav_group: Build
---
# Environments

An Environment defines the world an agent works in: what it can see, which actions it can take, and how those actions change the world. Reuse the same Environment across many Tasks to compare agents on consistent terms.

For customer support, the Environment might expose tickets and support policies, then let an agent categorize a ticket, draft a response, and resolve it. Each Task selects a ticket. A Verifier checks whether the work was done correctly.

## Start with the work you want to measure

Before writing code, decide:

1. **What should the agent accomplish?** Choose one workflow, such as resolving a support ticket.
2. **What information would it have?** Expose the ticket and applicable policy.
3. **What can it do?** Define focused actions that reflect the real workflow.
4. **How will you know it succeeded?** Keep the expected outcome available to a Verifier.
5. **When should it stop?** Decide what counts as finished and set a turn and time budget. See [How an episode ends](#how-an-episode-ends).

Start with a small, representative workflow. Add cases and complexity after you can explain why a known good run passes and a known bad run fails.

## Actions, State, and Observation

These three parts describe the interaction:

- **Actions** are operations the agent can call, such as `categorize` or `resolve`.
- **State** holds internal data, including the expected answer and changes made during the run.
- **Observation** contains the information you choose to show the agent.

Plural keeps State out of its agent-facing payloads. Your actions must preserve that separation: return an Observation or selected fields, rather than the full State. A Verifier can read the final State to check the result. This separation controls what Plural shows the model; use Runtime isolation when running untrusted code.

## Define the Environment

Save Environment classes in a Python file. This small example lets an agent classify one support request:

```python
from plural import Environment, Observation, Runtime, State, action, initial


class TicketObservation(Observation):
    issue: str = "I was charged twice."
    category: str = ""
    done: bool = False

    def render(self) -> str:
        return f"{self.issue}\n{self.text}\nCategory: {self.category or 'unassigned'}"


class TicketState(State):
    expected: str = initial("billing", description="The category this ticket should receive.")
    category: str = ""
    done: bool = False


class TicketTriage(Environment[TicketObservation, TicketState]):
    name = "ticket-triage"
    overview = "Assign a support request to the right team."

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.state = TicketState(seed=self.state.seed)
        self.observation = TicketObservation(text="Choose billing, technical, or account.")
        return self.observation, {}

    @action
    def categorize(self, category: str) -> TicketObservation:
        """Assign the ticket to billing, technical, or account."""
        if category not in {"billing", "technical", "account"}:
            raise ValueError("Choose billing, technical, or account")
        self.state.category = category
        self.state.done = True
        self.observation.category = category
        self.observation.done = True
        return self.observation

    def terminated(self) -> bool:
        return self.state.done


environment = TicketTriage(runtime=Runtime.local())
```

`runtime` is a required Environment parameter. It selects where the Environment and agent run. This example uses your machine for trusted development.

The Job calls `reset` to start each run and invokes the actions the agent selects. Only agent-facing methods use `@action`; `reset` and `step` are lifecycle methods. Typed action parameters tell the model which inputs each action accepts. Clear docstrings and validation errors help it use them correctly.

The directory containing the class is its source package. Keep the code and data it needs there, and keep credentials, caches, and generated results elsewhere. Plural records the source hash and copies the package into the Runtime.

## How an episode ends

Every agent action goes through `step`, which returns the same five values Gymnasium uses:

```python
observation, reward, terminated, truncated, info = environment.step("categorize", category="billing")
```

The agent only ever sees the observation. The remaining values describe the transition, and Plural records them on the episode rather than showing them to the model, so a reward or a terminal flag never leaks into the model's context.

An episode can stop for three reasons, and each records a different `stop_reason` on the Trial:

- **The Environment ends it.** Override `terminated()` when the world reaches a Task success or failure state, as the example above does when the ticket is categorized. Override `truncated()` when the episode cannot usefully continue but reached neither outcome. Both default to `False`, so an Environment that never overrides them leaves the stop decision entirely to the agent and the budget.
- **The agent ends it.** Plural adds a `finish` tool alongside your actions, and the agent calls it when the work is done or when it cannot make progress. Its optional `summary` becomes the Trial's response. Declare an `@action` named `finish` if you would rather handle that yourself.
- **A budget cuts it short.** `max_turns`, `max_seconds`, and `max_cost_usd` truncate the episode instead of failing the Trial, so you still get a trajectory and Verifier results.

`terminated` and `truncated` are recorded separately from `stop_reason`, because neither is set when the agent chose to stop. Read `stop_reason` to tell an agent that finished early from a world that declared the Task over.

## Rewards

A reward is per-step credit for one state transition. Verifiers decide whether the Trial succeeded; rewards explain which action deserved the credit. They are recorded on the episode in every mode, and they never contribute to a score.

For a single signal, override `reward`:

```python
class TicketTriage(Environment[TicketObservation, TicketState]):
    def reward(self, previous_state, current_state, action, result) -> float:
        return 1.0 if current_state["category"] == current_state["expected"] else 0.0
```

For several named signals, declare a `@rewarder` for each. Every one runs inside `step` immediately after the action that changed the world, and `weight` scales its contribution:

```python
from plural import rewarder


class TicketTriage(Environment[TicketObservation, TicketState]):
    @rewarder(weight=2)
    def correct_category(self, previous_state, current_state, action, result) -> float:
        return 1.0 if current_state["category"] == current_state["expected"] else 0.0

    @rewarder
    def progress(self, previous_state, current_state, action, result) -> float:
        return 1.0 if current_state["category"] and not previous_state["category"] else 0.0
```

Every reward signal takes exactly `previous_state, current_state, action, result`. The two states are detached JSON snapshots taken before and after the action, so read them like dictionaries rather than as your `State` class. `action` is the action name plus its parameters, and `result` is whatever the action returned.

The `reward` returned by `step` is the weighted total of `reward()` and every rewarder, and `info["rewards"]` breaks that total down by name. A signal that raises is recorded as `0.0` with its error in that breakdown, because a reward bug must not fail an action that already changed the world. A trainer reads these per-step values; see [Training and RL](../running/training.md).

## Connect Tasks and scoring

The example above always uses the same ticket. For a useful benchmark, reuse the Environment with different case data. Each [Task](tasks.md) supplies instructions, selects its case, and attaches one or more [Verifiers](verifiers.md).

Use `reset` to load the selected case and clear previous progress. Task `info` is public, so it can hold a ticket ID but should not hold the answer key. `initial_state` supplies schema-checked setup data; your reset implementation must preserve any fields it needs. Mark those State fields with `initial()`, and pass constraints such as `min_length=5` or `pattern=r"^[a-z]{5}$"` when a Task's value must match a rule. Unmarked fields, such as `done` or a running guess list, belong to the episode and a Task cannot set them. `State.seed` is settable. `State.metadata` is not. Task `reset_options` are stored, but package Jobs do not currently forward them to `reset`.

The [support queue tutorial](../tutorials/support-queue.md) shows how the Environment loads the Task's ticket and scores the completed workflow.

## Runtime

Choose a Runtime based on where the code should run and which controls it needs. Plural checks support before execution and fails if the selected provider cannot enforce a requested control.

### Local

```python
Runtime.local()
```

Use this for trusted development. Plural runs a subprocess in a temporary workspace on your machine. Local execution does not provide a sandbox, network isolation, or compute limits. `Runtime.local()` explicitly enables local execution through `allow_unsafe_local`.

### Docker

```python
Runtime.docker()
Runtime.docker(image="my-org/eval:1")
Runtime.docker(cpus=2, memory_mb=2048, read_only_root=True)
```

Use Docker for container isolation on a machine with Docker installed. The default image is `python:3.12-slim`. The workspace remains writable when the root filesystem is read-only. Pin an image digest when you need reproducible system dependencies.

To install additional dependencies, place a Dockerfile beside the Environment:

```dockerfile
FROM python:3.12-slim
WORKDIR /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

```python
Runtime.docker(dockerfile="Dockerfile", build_context=".")
```

`build_context` identifies the directory Docker uses for the build. Builds have a default timeout of 600 seconds. Choose one image source: a registry image, snapshot, declarative image, or Dockerfile.

### Remote

Use a remote Runtime to run away from your machine. The bundled provider is Daytona. Install the supported remote integration and set `DAYTONA_API_KEY`:

```bash
python -m pip install "plural[daytona]"
```

```python
Runtime.daytona(image="python:3.12-slim")
```

Remote execution requires an image or snapshot the provider can access. It cannot build from a Dockerfile on your laptop. See [Providers and integrations](../reference/integrations.md) for setup and extensions.

### Network

Model calls run inside the Runtime and need access to the model endpoint. Choose the narrowest network access that supports your workflow:

- `public` allows outbound connections and is the default.
- `no-network` blocks outbound connections.
- `allowlist` permits the hosts listed in `allowed_hosts` on a supporting provider.

Local execution cannot isolate networking. Docker supports blocking outbound traffic, but does not enforce a host allowlist. The remote provider supports allowlists:

```python
Runtime.daytona(
    image="python:3.12-slim",
    network="allowlist",
    allowed_hosts=("api.openai.com",),
)
```

Use your actual model endpoint hostname. Verifiers have an independent `VerifierRuntime`; model judges also need connectivity to their endpoint.

### Compute, timeouts, and persistence

`cpus` and `memory_mb` request compute limits on supporting providers. Runtime `timeout_seconds` defaults to 300 seconds for execution and upload operations. Environment limits separately bound the episode:

```python
from plural import ExecutionLimits

environment = TicketTriage(
    runtime=Runtime.local(),
    limits=ExecutionLimits(max_turns=4, max_seconds=60),
)
```

The default episode limits are eight turns and 120 seconds. An optional `max_cost_usd` sets a cost budget, subject to the usage the runner can measure.

Local, Docker, and the bundled remote provider do not support persistent workspaces across Trials. Recreate the data each Trial needs in `reset`.

## Resources

Resources are the files and data a Task can use. Environment resources are shared inputs; Task resources belong to one case. Each Trial receives a fresh copy:

```text
/workspace/resources/
  shared/             # Environment inputs
    policies/refunds.md
  task/               # Inputs for this Task only
    invoice.csv
  manifest.json       # File locations and SHA-256 hashes
```

Use relative file paths. Task files never replace shared files, even when their names match. Environment code reads the root from `PLURAL_RESOURCES_DIR`, then exposes the appropriate information through actions or observations. Files are not automatically included in the model's prompt.

### The short form

A file that already lives next to your Environment code needs one line. It is
staged from the source package automatically:

```python
from plural import Resource

policy = Resource("policies/refunds.md")
```

That is `kind="file"`, `delivery="source"`, with the name defaulting to the
path. Pass `resources=[policy]` when creating the Environment.

### Saved text and configuration

```python
from plural import Resource

policy = Resource(
    "policies/refunds.md",
    content="Refund duplicate charges after confirming the invoice.",
    content_type="text/markdown",
)
```

Pass `resources=[policy]` when creating the Environment. Plural calculates the content hash and writes the file before reset. Inline resources support text, CSV, JSON, and other UTF-8 configuration, up to 1 MiB of characters and the 16 MiB staged-file limit. They are stored with the definition; use runtime secrets for credentials.

### Packaged files

The short form already stages a file from the Environment's source package
into the resource directory. The explicit mapping form says the same thing:

```python
policy = Resource(
    kind="file",
    name="policies/refunds.md",
    path="policies/refunds.md",
    delivery="source",
)
```

The path must identify a file inside the package. Source files may be binary. Each staged file is limited to 16 MiB. The manifest records the actual hash; an optional `digest` requires an exact match.

### Data resolved at launch

For external data, store its location, resolver name, configuration, and expected hash. Supply the resolver implementation to the Job:

```python
import hashlib
from plural import Job, Resource

expected_bytes = b'{"ticket_id": "ticket-123", "category": "billing"}'
ticket = Resource(
    kind="data",
    name="ticket",
    path="ticket.json",
    delivery="resolver",
    uri="support://tickets/ticket-123",
    resolver="support-ticket",
    config={"ticket_id": "ticket-123"},
    digest="sha256:" + hashlib.sha256(expected_bytes).hexdigest(),
)

def load_ticket(resource: Resource) -> bytes:
    # Replace this fixture with a read from your data service.
    # Set a timeout on external calls and return a stable encoding.
    assert resource.config["ticket_id"] == "ticket-123"
    return expected_bytes

# Add ticket to the Task's resources before creating this Job.
job = Job(task, agents=[agent], resource_resolvers={"support-ticket": load_ticket})
```

Resolvers run in the Job process before the Agent starts. They receive the resource declaration and return bytes. Plural rejects missing resolvers or mismatched hashes. Register implementations in the process running the Job; saving a resolver name in the UI does not install it on a hosted worker. A URI alone is never fetched automatically.

Existing resources without a delivery setting use `descriptor`: they remain references and do not stage files. Existing Environment code can continue to load them itself.

## Runtime variables and secrets

Declare names and expected values in the Runtime. Supply actual values only when the Job is invoked:

```python
import os
from plural import Job, Runtime, RuntimeVariable

runtime = Runtime.docker(variables=[
    RuntimeVariable(
        name="SUPPORT_API_URL",
        format="url",
        description="Base URL of the support API.",
    ),
    RuntimeVariable(
        name="SUPPORT_API_TOKEN",
        secret=True,
        description="Token with access to the evaluation support account.",
    ),
])

# Use this runtime when constructing your Environment and Task.
job = Job(task, agents=[agent], environ={
    "SUPPORT_API_URL": os.environ["SUPPORT_API_URL"],
    "SUPPORT_API_TOKEN": os.environ["SUPPORT_API_TOKEN"],
})
```

Required declarations must have a nonempty value. Supported formats are `text`, `url`, `integer`, and `json`. Set `required=False` for optional inputs. Values are injected into Environment reset and action commands; declarations never contain values. The Harness shares the runtime and can access these variables, so use trusted Harness code.

Existing `Secret` references are also injected according to their `environment`, `harness`, or `verifier` target. Environment secret references as metadata declare names and targets only; values are supplied when the Job runs and are never stored on the Environment. Verifier credentials are supplied to the scoring process. Managed stdout and stderr redact declared secrets; Environment code must avoid writing credentials into observations or custom artifacts.

Docker and Daytona connection credentials configure the run worker, separately from these Task variables. The UI shows the saved provider configuration; availability and capability checks happen when a run starts. Authenticate model calls through the Job's `client` or `api_key` parameter.

## Optional components

- **Metadata:** use `name`, `version`, and `overview` to identify the Environment; use `metadata` for labels and ownership.
- **Display:** override `Observation.render()` to control model-facing text and `Environment.view()` to create an operator summary.
- **Harness policy:** restrict custom Harnesses and their capabilities. See [Harnesses](harnesses.md).
- **Rewards:** attach per-step credit to state transitions. See [Rewards](#rewards).

## Build a complete example

Continue with [Tasks](tasks.md) to add cases to your Environment, or follow an end-to-end tutorial:

- [Support queue](../tutorials/support-queue.md): inspect, categorize, answer, and resolve three tickets.
- [Wordle](../tutorials/wordle.md): guess a hidden word using feedback from one action.
