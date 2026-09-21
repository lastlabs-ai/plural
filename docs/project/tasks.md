---
route: /docs/project/tasks
title: Tasks
order: 40
description: Set up cases with initial State, shared Environment data, and Task-specific resources.
audience: all
nav: true
nav_group: Build
outcome: You can supply starting State and files, expose them to the agent, and run the Task.
---
# Tasks

A Task is one case you want an agent to complete in an Environment. It supplies instructions, initial conditions, additional inputs, and the Verifiers that define success.

The Environment provides reusable behavior. Tasks vary the case: a different support ticket, document, codebase, or starting state.

## Create a Task

Using the `environment` and `verifier` from the [support queue tutorial](../tutorials/support-queue.md):

```python
from plural import Task

task = Task(
    name="ticket-1",
    instructions="Inspect, categorize, answer, and resolve the ticket.",
    goals=("Follow the support policy.", "Leave the ticket resolved."),
    info={"ticket_id": "ticket-1"},
    environment=environment,
    verifiers=[verifier],
)
```

`info` is public case data. Here, the Environment uses the ticket ID to look up the case. Keep expected answers out of `info`, instructions, and observations.

## Start from a task directory

For hosted work, keep the task itself local until it is ready to publish:

```bash
plural task init support-ticket --environment ticket-triage --verifier correct-team
```

This creates a directory with the same name:

```text
support-ticket/
├── instruction.md
├── task.yaml
└── resources/
```

`task.yaml` stores the task identity, `initial_state`, public `info`, the
hosted environment slug, and verifier slugs. The `instructions` field points
to `instruction.md`; its contents are inlined when the task loads. A literal
instruction string in `task.yaml` continues to work. Every UTF-8 text file
added below `resources/` is staged as a task file at the same relative path.
Use `--bare` for empty instructions, resources, and identity-only `task.yaml`,
and `--push` to publish immediately after creating the directory.

In Python, the same helper writes the same package:

```python
from plural.cli.scaffold import init_task

init_task("support-ticket", environment="ticket-triage", verifiers=["correct-team"])
```

If `PLURAL_API_KEY` is set, `plural task init` checks whether the slug already
exists in the current project and asks whether to proceed. Answering `n`
writes nothing. Without a key, the command creates the directory locally and
reports that the remote name was not checked. The Python helper warns when the
slug exists but does not prompt.

Publish the directory when it is ready:

```bash
plural task push support-ticket
```

Push resolves each environment and verifier slug to its current published
revision in the same project. A missing slug, or a bare task without bindings,
is an error. Explicit `--environment-revision-id` and repeatable
`--verifier-revision-id` values override slug lookup.

## Publish a Task object

A `Task` has the same local-to-hosted relationship as an `Environment`.
`task.definition()` compiles the canonical revision, so `client.create()`,
`client.update()`, and `client.push()` all accept a public `Task` exactly like
they accept a public `Environment`:

```python
from plural import Client, Task

task = Task(
    name="support-ticket",
    instructions="Inspect, categorize, answer, and resolve the ticket.",
    environment=environment,
    verifiers=[verifier],
)
task.push()
```

`task.push()` publishes the task revision, creating its hosted parent by slug
when needed. Like `plural task push`, it resolves each bound Environment and
Verifier to its current published revision unless exact ids are passed:

```python
task.push(
    Client(),
    environment_revision_id="env-revision",
    verifier_revision_ids=["verifier-revision"],
)
```

`task.delete()` removes the hosted parent and all of its revisions. Revisions
themselves are immutable: publishing an edited task mints a new revision under
the same parent, which is how updates work for every Plural resource.

## Set the initial State

Use `initial_state` when each Task should start the Environment with different data. Plural checks these fields against the Environment's State schema and loads them before `reset` during package Job execution.

The following small project shows both initial State and packaged files:

```text
support-eval/
  project.py
  verify.py
  environment/
    world.py
    data/
      policy.md
      invoice.csv
```

Put this policy in `environment/data/policy.md`:

```text
Duplicate charges should be assigned to billing for refund review.
```

Put this sample attachment in `environment/data/invoice.csv`:

```csv
invoice_id,amount_usd,status
INV-101,49.00,paid
INV-102,49.00,duplicate
```

Save the Environment in `environment/world.py`:

```python
from pathlib import Path

from plural import Environment, Observation, State, action

DATA = Path(__file__).parent / "data"


class TicketState(State):
    issue: str = ""
    expected: str = ""
    category: str = ""
    done: bool = False


class TicketObservation(Observation):
    issue: str = ""
    policy: str = ""
    invoice: str = ""
    category: str = ""
    done: bool = False


class TicketTriage(Environment[TicketObservation, TicketState]):
    name = "ticket-triage"
    overview = "Read a support ticket and its invoice, then assign the right team."

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        # Preserve the issue and expected category supplied by the Task.
        self.state.category = ""
        self.state.done = False
        self.observation = TicketObservation(
            text=self.state.issue,
            issue=self.state.issue,
            policy=(DATA / "policy.md").read_text(),
        )
        return self.observation, {}

    @action
    def read_invoice(self) -> TicketObservation:
        """Read the invoice attached to this support case."""
        self.observation.invoice = (DATA / "invoice.csv").read_text()
        return self.observation

    @action
    def categorize(self, category: str) -> TicketObservation:
        """Assign billing, technical, or account and finish the case."""
        if category not in {"billing", "technical", "account"}:
            raise ValueError("Choose billing, technical, or account")
        self.state.category = category
        self.state.done = True
        self.observation.category = category
        self.observation.done = True
        return self.observation

    def terminated(self) -> bool:
        return self.state.done
```

Reset clears progress while preserving the Task's `issue` and `expected` fields. Replacing State with an empty `TicketState()` here would discard those initial conditions.

## Add shared and Task-specific resources

Save `resolved_correctly` from the [DeterministicVerifier example](verifiers.md#deterministicverifier) in `verify.py`. Then create `project.py`:

```python
from environment.world import TicketTriage
from verify import resolved_correctly

from plural import (
    Agent, DeterministicVerifier, Job, Resource, Runtime, Task,
)

environment = TicketTriage(
    runtime=Runtime.local(),
    resources=[
        Resource(
            "data/policy.md",
            kind="data",
            content_type="text/markdown",
        ),
    ],
)

verifier = DeterministicVerifier(name="correct-team", check=resolved_correctly)

task = Task(
    name="duplicate-charge",
    instructions="Read the ticket, policy, and invoice. Assign the ticket to the right team.",
    environment=environment,
    initial_state={
        "issue": "I was charged twice for the same subscription.",
        "expected": "billing",
    },
    resources=[
        Resource("data/invoice.csv", content_type="text/csv"),
    ],
    verifiers=[verifier],
)

agent = Agent(
    model="openai/gpt-5.6-luna",
    instructions="Read the available evidence before assigning the ticket.",
)
job = Job(task, agents=[agent])
```

The shared policy belongs to the Environment. The invoice describes an input for this Task. In this example, both files are packaged beneath the Environment's source directory and staged automatically by the short `Resource("path")` form. Reset reads the policy into the Observation; `read_invoice` exposes the attachment through an action.

A URI alone does not fetch data. For data that must be resolved at launch, use `resolver` delivery as described in [Environment resources](environments.md#resources).

This example uses one invoice. To support many cases, add a public case ID or resource name and have Environment code select the corresponding file. Package only the inputs that should be accessible together; a custom Harness with filesystem access may read other staged files.

### Supply data for just one Task

Use an inline resource for a small case-specific attachment:

```python
invoice = Resource(
    "invoice.csv",
    content="invoice_id,amount,currency\ninv-204,49.00,USD\n",
    content_type="text/csv",
)
```

Pass `resources=[invoice]` to this Task. It becomes `/workspace/resources/task/invoice.csv` for this Trial only. Shared inputs stay in `/workspace/resources/shared/`. Read the attachment in an Environment action:

```python
import os
from pathlib import Path

resource_root = Path(os.environ["PLURAL_RESOURCES_DIR"])
invoice_text = (resource_root / "task" / "invoice.csv").read_text()
```

Keep case-specific files out of a shared source package when other Tasks should not receive them. Initial state and resource files are separate: `initial_state` initializes the Environment's State, while resources provide files that reset or actions can read. Both are prepared before reset. Reset code should preserve Task-injected State fields it intends to use.

## Run the example

From `support-eval`, validate and preview the Job before making model calls:

```bash
plural validate project.py:job
plural run project.py:job --dry-run
plural auth login
plural run project.py:job
```

Inspect the resulting Trial to check that the issue appeared in the Observation, the invoice was available, and the expected category remained in internal State. Local execution is for trusted code; see [Runtime](environments.md#runtime) for isolation options.

## Choose the right place for data

- **`instructions` and `goals`:** what the agent should accomplish.
- **`info`:** public case information, such as an identifier.
- **`initial_state`:** internal starting values defined by the State schema.
- **`resources`:** descriptions of files, datasets, or applications used by the case.
- **`metadata`:** organizational labels, such as owner or training/evaluation split.

Task `reset_options` are stored but are not currently forwarded to `reset` by package Jobs. Use initial State or explicit case loading for those runs.

Keep one coherent outcome per Task. Include common cases and important failures, test your Verifiers on known outcomes, and reserve held-out Tasks if you plan to train. Collect Tasks into a [Benchmark](benchmarks.md) to compare agents across the work you care about.
