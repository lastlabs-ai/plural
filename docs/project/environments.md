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
5. **When should it stop?** Define completion and set a turn and time budget.

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
from plural import Environment, Observation, Runtime, State, action


class TicketObservation(Observation):
    issue: str = "I was charged twice."
    category: str = ""
    done: bool = False

    def render(self) -> str:
        return f"{self.issue}\n{self.text}\nCategory: {self.category or 'unassigned'}"


class TicketState(State):
    expected: str = "billing"
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

## Connect Tasks and scoring

The example above always uses the same ticket. For a useful benchmark, reuse the Environment with different case data. Each [Task](tasks.md) supplies instructions, selects its case, and attaches one or more [Verifiers](verifiers.md).

Use `reset` to load the selected case and clear previous progress. Task `info` is public, so it can hold a ticket ID but should not hold the answer key. `initial_state` supplies schema-checked setup data; your reset implementation must preserve any fields it needs. Task `reset_options` are stored, but package Jobs do not currently forward them to `reset`.

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

### Saved text and configuration

```python
from plural import Resource

policy = Resource(
    kind="file",
    name="refund-policy",
    path="policies/refunds.md",
    delivery="inline",
    content="Refund duplicate charges after confirming the invoice.",
    content_type="text/markdown",
)
```

Pass `resources=[policy]` when creating the Environment. Plural calculates the content hash and writes the file before reset. Inline resources support text, CSV, JSON, and other UTF-8 configuration, up to 1 MiB of characters and the 16 MiB staged-file limit. They are stored with the definition; use runtime secrets for credentials.

### Packaged files

Use `delivery="source"` to copy a file from the Environment's source package into the resource directory:

```python
policy = Resource(
    kind="file",
    name="refund-policy",
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

Existing `Secret` references are also injected according to their `environment`, `harness`, or `verifier` target. Verifier credentials are supplied to the scoring process. Managed stdout and stderr redact declared secrets; Environment code must avoid writing credentials into observations or custom artifacts.

Docker and Daytona connection credentials configure the run worker, separately from these Task variables. The UI shows the saved provider configuration; availability and capability checks happen when a run starts. Authenticate model calls through the Job's `client` or `api_key` parameter.

## Optional components

- **Metadata:** use `name`, `version`, and `overview` to identify the Environment; use `metadata` for labels and ownership.
- **Display:** override `Observation.render()` to control model-facing text and `Environment.view()` to create an operator summary.
- **Harness policy:** restrict custom Harnesses and their capabilities. See [Harnesses](harnesses.md).
- **Rewarders:** define additional learning signals for a supported training integration. Final success is scored by Verifiers. See [Training and RL](../running/training.md).

## Build a complete example

Continue with [Tasks](tasks.md) to add cases to your Environment, or follow an end-to-end tutorial:

- [Support queue](../tutorials/support-queue.md): inspect, categorize, answer, and resolve three tickets.
- [Wordle](../tutorials/wordle.md): guess a hidden word using feedback from one action.
