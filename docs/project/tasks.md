---
route: /docs/project/tasks
title: Tasks
order: 40
description: "One assignment in an Environment: the instructions, the starting situation, any files that case needs, and the Verifiers that grade it."
audience: all
nav: true
nav_group: Build
outcome: You can supply starting State and files, expose them to the agent, and run the Task.
---
# Tasks

A **Task** is one assignment in an [Environment](environments.md). If the Environment
is the game of Wordle, a Task is one secret word. If the Environment is a support
desk, a Task is one support ticket.

The Environment says how the world *works*. The Task says what is true about *this
particular case*: what the Agent should do, how the world starts, which files it
needs, and which [Verifiers](verifiers.md), the graders, decide whether it succeeded.
Keeping the two apart lets you write the world once and add as many cases as you like.

## What goes in a Task

Each piece of a Task has its own place. Put information in the right one and the
Agent sees exactly what it should, and nothing more.

| Field | What it is | Support desk example |
| --- | --- | --- |
| `instructions` and `goals` | What the Agent should accomplish | "Resolve the ticket" |
| `info` | Public case information, such as an identifier | `ticket_id: ticket-1` |
| `initial_state` | Hidden starting values, defined by the Environment's State | The expected category |
| `resources` | Files the case uses, which Environment code can read | The customer's invoice |
| `metadata` | Labels for you, such as an owner or a training or evaluation split | `owner: support-team` |
| `verifiers` | The graders that score the attempt | `correct-category` |

> **Good to know:** Keep expected answers out of `info`, the instructions, and the
> Observation. Those are visible to the Agent. The answer belongs in `initial_state`,
> which becomes part of the hidden State that a Verifier can check.

Plural stores a Task's `reset_options` but does not yet pass them to `reset`. Use
`initial_state`, or load the case in Environment code, instead.

## Create a Task

This Task uses the `environment` and `verifier` from the
[support queue tutorial](../tutorials/support-queue.md):

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

`info` is public case data. Here, the Environment uses the ticket ID to look up the
case.

## Save a Task in a project

In a [project](../getting-started.md#create-a-project), each Task is a folder under
`tasks/`, named after the Task. Create one from inside the project:

```bash
plural task init ticket-1 --environment support-queue --verifier correct-category
```

This creates:

```text
tasks/ticket-1/
├── task.yaml
└── instruction.md
```

Add a `resources/` folder when the Task needs its own files. `task.yaml` names the
Task, its one Environment, and its Verifiers. This is `tasks/ticket-1/task.yaml` from
the [first project](../tutorials/first-project.md):

```yaml
name: ticket-1
version: 0.1.0
instructions: instruction.md
environment: support-queue
verifiers:
  - correct-category
initial_state:
  ticket_id: ticket-1
```

Check the Task and everything it depends on:

```bash
plural task validate ticket-1
```

Validation also loads the Environment and each Verifier, and reports every problem it
finds, including placeholders the template left for you to fill in. Leave out the name
to validate the Task whose folder you are in.

### The manifest fields

Here is what each field in `task.yaml` means, for when you need the exact rules:

- `name` must match the folder name, which is also the Task's slug in the hosted
  project. The optional `title` is its display name there, such as
  `title: Refund triage`; without it, the display name is `name`. The title is part of
  the Task's content, so changing it needs a new `version:`. Pushing that version
  renames the hosted Task while its slug stays the same.
- `instructions` is the path of a UTF-8 file in the Task folder, `instruction.md` by
  default. Its contents are the Task's instructions.
- `environment` is the name of one Environment in `environments/`, and `verifiers`
  lists at least one Verifier in `verifiers/`, each once. Resources always refer to
  each other by name within the project.
- `initial_state`, `info`, `goals`, `metadata`, and `reset_options` mean the same as
  the `Task` fields described on this page.
- `resources` lists files and folders to give the Task, relative to its folder. It
  defaults to `resources`, so every file below `resources/` is included, and a missing
  `resources/` folder is not an error. Task files must be UTF-8 text; a binary file
  fails validation. Paths must stay inside the Task folder.

### Push the Task

Pushing saves the Task as an unchangeable, private revision in the hosted project this
checkout is bound to:

```bash
plural task push ticket-1 --with-deps
```

`--with-deps` also pushes the Environment and Verifiers when they are not hosted yet.
Without it, each dependency must already be pushed with identical content, and the
push stops before uploading anything if one is not.

A few more rules:

- Pushing unchanged content reuses the existing revision.
- Changed content becomes the Task's next numbered revision. You never bump
  `version`.
- A pushed revision is available in its project right away and becomes the Task's
  current revision.
- Pushing never makes a Task public.

To bring a hosted Task back down, pull it:

```bash
plural task pull ticket-1
```

This restores a hosted revision into `tasks/ticket-1/`, plus its Environment and
Verifiers if this project lacks them. A Task created in the web app is written from its
stored content. Pull refuses to overwrite local files that differ unless you pass
`--force`, which keeps the old copy under `.plural/backups`.

## Load a Task from Python

The CLI and the Python SDK read the same folders. Load a saved Task by name and run it:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
task = workspace.get("task", "ticket-1")
agent = workspace.get("agent", "careful")
result = Job(task, agents=[agent]).run()
```

The loaded value is an ordinary `Task`, so everything on this page applies to it. A
`Task` built in Python, like the one at the top of this page, also runs directly with
`Job` for scripting. Project folders are how the CLI and hosted projects exchange
Tasks.

## Set the initial State

The **State** is the hidden truth of the world, such as the secret word in Wordle or
the correct category for a ticket. Use `initial_state` when each Task should start the
world differently.

The Environment decides which State fields a Task may set by marking them with
`initial()`. Constraints passed there, such as `min_length=5` and
`pattern=r"^[a-z]{5}$"`, are requirements on the value a Task saves. Plural checks the
values against the Environment's State schema and loads them before each Trial calls
`reset`. A Task cannot set unmarked fields, such as whether the episode is already
solved.

The rest of this section builds a small project that uses both initial State and
files. Create it with:

```bash
plural project init support-eval
cd support-eval
plural env init ticket-triage
plural verifier init correct-team
plural task init duplicate-charge --environment ticket-triage --verifier correct-team
```

When you have filled in the files below, the project looks like this:

```text
support-eval/
├── project.yaml
├── environments/ticket-triage/
│   ├── environment.yaml
│   ├── environment.py
│   ├── README.md
│   └── resources/policy.md
├── verifiers/correct-team/
│   ├── verifier.yaml
│   └── verify.py
└── tasks/duplicate-charge/
    ├── task.yaml
    ├── instruction.md
    └── resources/invoice.csv
```

**1. Add the shared policy.** Put this in
`environments/ticket-triage/resources/policy.md`:

```text
Duplicate charges should be assigned to billing for refund review.
```

**2. Add the Task's own file.** Put this sample attachment in
`tasks/duplicate-charge/resources/invoice.csv`:

```csv
invoice_id,amount_usd,status
INV-101,49.00,paid
INV-102,49.00,duplicate
```

**3. Write the Environment.** Save this in
`environments/ticket-triage/environment.py`:

```python
import os
from pathlib import Path

from plural import Environment, Observation, State, action, initial


def resource(scope: str, path: str) -> str:
    return (Path(os.environ["PLURAL_RESOURCES_DIR"]) / scope / path).read_text()


class TicketState(State):
    issue: str = initial("", description="The support request for this Task.")
    expected: str = initial("", description="The category this ticket should receive.")
    category: str = ""
    done: bool = False


class TicketObservation(Observation):
    issue: str = ""
    policy: str = ""
    invoice: str = ""
    category: str = ""
    done: bool = False


class TicketTriage(Environment[TicketObservation, TicketState]):
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        # Preserve the issue and expected category supplied by the Task.
        self.state.category = ""
        self.state.done = False
        self.observation = TicketObservation(
            text=self.state.issue,
            issue=self.state.issue,
            policy=resource("shared", "resources/policy.md"),
        )
        return self.observation, {}

    @action
    def read_invoice(self) -> TicketObservation:
        """Read the invoice attached to this support case."""
        self.observation.invoice = resource("task", "resources/invoice.csv")
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

`reset` clears progress but keeps the Task's `issue` and `expected` fields. Replacing
State with an empty `TicketState()` here would throw away those starting conditions.

**4. Describe the Environment.** Replace the placeholder comment in
`environments/ticket-triage/README.md` with a sentence describing the Environment, such
as "A support queue with one ticket and its invoice." Validation reports every
placeholder the templates leave, and the run below refuses to start until they are
filled in. Then replace `environments/ticket-triage/environment.yaml` with:

```yaml
name: ticket-triage
version: 0.1.0
overview: Read a support ticket and its invoice, then assign the right team.
python: environment.py:TicketTriage
readme: README.md
resources:
  - resources/policy.md
runtime:
  provider: local
limits:
  max_turns: 4
  max_seconds: 60
```

**5. Add the grader.** Save the `resolved_correctly` function from the
[DeterministicVerifier example](verifiers.md#deterministicverifier) in
`verifiers/correct-team/verify.py`, and point `verifiers/correct-team/verifier.yaml` at
it:

```yaml
name: correct-team
version: 0.1.0
kind: deterministic
check: verify.py:resolved_correctly
```

**6. Write the case.** `tasks/duplicate-charge/instruction.md` holds the instructions:

```text
Read the ticket, policy, and invoice. Assign the ticket to the right team.
```

and `tasks/duplicate-charge/task.yaml` supplies the initial State:

```yaml
name: duplicate-charge
version: 0.1.0
instructions: instruction.md
environment: ticket-triage
verifiers:
  - correct-team
initial_state:
  issue: I was charged twice for the same subscription.
  expected: billing
```

## Add shared and Task-specific resources

**Resources** are files the world starts with. The support policy applies to every
ticket, so it belongs to the Environment and is listed under `resources` in
`environment.yaml`. The invoice belongs to this one case, so it lives in the Task's
`resources/` folder. Each Trial, one attempt at the Task, receives both, under
separate folders:

```text
/workspace/resources/
  shared/resources/policy.md     # from the Environment
  task/resources/invoice.csv     # from this Task only
```

Environment code reads the root folder from `PLURAL_RESOURCES_DIR`. In the example,
`reset` reads the policy into the Observation, and the `read_invoice` action shows the
attachment when the Agent asks for it.

> **Good to know:** Files are not added to the model's prompt automatically. The Agent
> only sees what your Environment code puts in the Observation.

A URI alone does not fetch data. For data that must be fetched when a run starts, use
`resolver` delivery as described in [Environment resources](environments.md#resources).

This example uses one invoice. To support many cases, give each Task its own files, or
add a public case ID and have Environment code pick the matching data. Package together
only the inputs that should be reachable together; a custom Harness with filesystem
access may read other staged files.

### Supply data for a single Task

Files in a Task's `resources/` folder reach that Task's Trials only. Task files are
UTF-8 text, such as CSV, JSON, or Markdown. They never replace shared files, even when
their paths match.

A `Task` built in Python takes the same file as an inline resource:

```python
from plural import Resource

invoice = Resource(
    "invoice.csv",
    content="invoice_id,amount,currency\ninv-204,49.00,USD\n",
    content_type="text/csv",
)
```

Pass `resources=[invoice]` to the Task. It becomes
`/workspace/resources/task/invoice.csv` for this Trial only. Read it in an Environment
action:

```python
import os
from pathlib import Path

resource_root = Path(os.environ["PLURAL_RESOURCES_DIR"])
invoice_text = (resource_root / "task" / "invoice.csv").read_text()
```

Keep case-specific files out of the Environment when other Tasks should not receive
them.

Initial State and resource files do different jobs. `initial_state` sets the
Environment's hidden State, while resources provide files that `reset` or actions can
read. Both are prepared before `reset`, and `reset` should preserve any State fields
the Task set that it intends to use.

## Run the example

From `support-eval`, validate and preview the run before making any model calls, then
run it for real:

```bash
plural task validate duplicate-charge
plural run --task duplicate-charge --model openai/gpt-5.6-luna --dry-run
plural auth login --api-key-stdin < plural-api-key.txt
plural run --task duplicate-charge --model openai/gpt-5.6-luna
```

`--model` without `--harness` uses `native`, Plural's built-in tool loop. A live model
call goes through the Plural gateway and needs a Plural API key: store one with
`plural auth login --api-key-stdin`, as above, or export `PLURAL_API_KEY`. A browser
login alone is not accepted for model calls.

The run is a Job, recorded under `.plural/jobs/`. To see how it went:

```bash
plural trial show TRIAL_ID
```

This prints the Trial's score, the Verifier's evidence, and its artifacts folder.
Open `observation.json` there to check that the issue and invoice reached the
Observation, and `state.json` to check that the expected category stayed in the hidden
State.

The `local` runtime is a trusted subprocess, not a sandbox; see
[Runtime](environments.md#runtime) for isolation options.

## Choose the right place for data

A quick recap of [What goes in a Task](#what-goes-in-a-task):

- **`instructions` and `goals`:** what the Agent should accomplish.
- **`info`:** public case information, such as an identifier.
- **`initial_state`:** hidden starting values defined by the State schema.
- **`resources`:** files the case uses, which Environment code can read.
- **`metadata`:** organizational labels, such as an owner or a training or evaluation split.

Keep one clear outcome per Task. Include common cases and important failures, test
your Verifiers on known outcomes, and hold some Tasks back if you plan to train.
Collect Tasks into a [Benchmark](benchmarks.md), the exam, to compare Agents across
the work you care about.
