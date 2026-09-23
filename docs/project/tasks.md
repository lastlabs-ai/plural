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

## Save a Task in a project

In a [project](../getting-started.md#create-a-project), each Task is a directory under `tasks/` named after the Task. Create one from inside the project:

```bash
plural task init ticket-1 --environment support-queue --verifier correct-category
```

This creates:

```text
tasks/ticket-1/
├── task.yaml
└── instruction.md
```

Add a `resources/` directory when the Task needs its own files. `task.yaml` names the Task, its one Environment, and its Verifiers. This is `tasks/ticket-1/task.yaml` from the [first project](../tutorials/first-project.md):

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

- `name` must match the directory name.
- `instructions` is the path of a UTF-8 file in the Task directory, `instruction.md` by default. Its contents are the Task's instructions.
- `environment` is the name of one Environment in `environments/`, and `verifiers` lists at least one Verifier in `verifiers/`, each once. References between resources are always by name within the project.
- `initial_state`, `info`, `goals`, `metadata`, and `reset_options` have the same meaning as the `Task` fields described on this page.
- `resources` lists files and directories to give the Task, relative to its directory. It defaults to `resources`, so every file placed below `resources/` is included, and a missing `resources/` directory is not an error. Task files must be UTF-8 text; a binary file fails validation. Paths must stay inside the Task directory.

Check the Task and everything it depends on:

```bash
plural task validate ticket-1
```

Validation loads the Environment and each Verifier as well, and reports every problem it finds, including placeholders the template left for you to fill in. Omit the name to validate the Task whose directory you are in.

### Push the Task

Pushing saves the Task as an immutable, private revision in the hosted project this checkout is bound to:

```bash
plural task push ticket-1 --with-deps
```

`--with-deps` also pushes the Environment and Verifiers when they are not hosted yet. Without it, each dependency must already be pushed with identical content, and the push stops before uploading anything if one is not. Pushing unchanged content reuses the existing revision. If you change a file but keep the same `version`, the push is refused; bump `version` first. A pushed revision is available in its project immediately and becomes the Task's current version. Pushing never makes a Task public.

`plural task pull ticket-1` restores a hosted revision into `tasks/ticket-1/`. It refuses to overwrite local files that differ unless you pass `--force`, which keeps the old copy under `.plural/backups`.

## Load a Task from Python

The CLI and the Python SDK read the same directories. Load a saved Task by name and run it:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
task = workspace.get("task", "ticket-1")
agent = workspace.get("agent", "careful")
result = Job(task, agents=[agent]).run()
```

The loaded value is an ordinary `Task`, so everything on this page applies to it. A `Task` built in Python, like the one at the top of this page, also runs directly with `Job` for scripting. Project directories are how the CLI and hosted projects exchange Tasks.

## Set the initial State

Use `initial_state` when each Task should start the Environment with different data. Mark those State fields with `initial()`. Constraints passed there, such as `min_length=5` and `pattern=r"^[a-z]{5}$"`, are requirements on the value a Task saves. Plural checks the values against the Environment's State schema and loads them before each Trial calls `reset`. A Task cannot set unmarked fields, such as whether the episode is already solved.

The following small project shows both initial State and resource files. Create it with:

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

Put this policy in `environments/ticket-triage/resources/policy.md`:

```text
Duplicate charges should be assigned to billing for refund review.
```

Put this sample attachment in `tasks/duplicate-charge/resources/invoice.csv`:

```csv
invoice_id,amount_usd,status
INV-101,49.00,paid
INV-102,49.00,duplicate
```

Save the Environment in `environments/ticket-triage/environment.py`:

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

Reset clears progress while preserving the Task's `issue` and `expected` fields. Replacing State with an empty `TicketState()` here would discard those initial conditions.

Replace the placeholder comment in `environments/ticket-triage/README.md` with a sentence describing the Environment, such as "A support queue with one ticket and its invoice." Validation reports every placeholder the templates leave, and the run below refuses to start until they are filled in. Then replace `environments/ticket-triage/environment.yaml` with:

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

Save the `resolved_correctly` function from the [DeterministicVerifier example](verifiers.md#deterministicverifier) in `verifiers/correct-team/verify.py`, and point `verifiers/correct-team/verifier.yaml` at it:

```yaml
name: correct-team
version: 0.1.0
kind: deterministic
check: verify.py:resolved_correctly
```

Finally, write the case. `tasks/duplicate-charge/instruction.md` holds the instructions:

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

The shared policy belongs to the Environment, so it is listed under `resources` in `environment.yaml`. The invoice describes an input for this Task, so it lives in the Task's `resources/` directory. Each Trial receives both, under separate roots:

```text
/workspace/resources/
  shared/resources/policy.md     # from the Environment
  task/resources/invoice.csv     # from this Task only
```

Environment code reads the root from `PLURAL_RESOURCES_DIR`. Reset reads the policy into the Observation; `read_invoice` exposes the attachment through an action. Files are not added to the model's prompt automatically.

A URI alone does not fetch data. For data that must be resolved at launch, use `resolver` delivery as described in [Environment resources](environments.md#resources).

This example uses one invoice. To support many cases, give each Task its own files, or add a public case ID and have Environment code select the corresponding data. Package only the inputs that should be accessible together; a custom Harness with filesystem access may read other staged files.

### Supply data for just one Task

Files in a Task's `resources/` directory reach that Task's Trials only. Task files are UTF-8 text, such as CSV, JSON, or Markdown. They never replace shared files, even when their paths match.

A `Task` built in Python takes the same file as an inline resource:

```python
invoice = Resource(
    "invoice.csv",
    content="invoice_id,amount,currency\ninv-204,49.00,USD\n",
    content_type="text/csv",
)
```

Pass `resources=[invoice]` to the Task. It becomes `/workspace/resources/task/invoice.csv` for this Trial only. Read it in an Environment action:

```python
import os
from pathlib import Path

resource_root = Path(os.environ["PLURAL_RESOURCES_DIR"])
invoice_text = (resource_root / "task" / "invoice.csv").read_text()
```

Keep case-specific files out of the Environment when other Tasks should not receive them. Initial state and resource files are separate: `initial_state` initializes the Environment's State, while resources provide files that reset or actions can read. Both are prepared before reset. Reset code should preserve Task-injected State fields it intends to use.

## Run the example

From `support-eval`, validate and preview the run before making model calls:

```bash
plural task validate duplicate-charge
plural run --task duplicate-charge --model openai/gpt-5.6-luna --dry-run
plural auth login --api-key-stdin < plural-api-key.txt
plural run --task duplicate-charge --model openai/gpt-5.6-luna
```

`--model` without `--harness` uses `native`, Plural's built-in tool loop. A live model needs an API key: store a Plural API key with `plural auth login --api-key-stdin`, as above, or export `PLURAL_API_KEY` or `OPENAI_API_KEY`. A browser login alone is not accepted for model calls. The run is a Job recorded under `.plural/jobs/`. `plural trial show TRIAL_ID` prints the Trial's score, Verifier evidence, and artifacts directory. Open `observation.json` there to check that the issue and invoice reached the Observation, and `state.json` to check that the expected category stayed in internal State. The `local` runtime is a trusted subprocess, not a sandbox; see [Runtime](environments.md#runtime) for isolation options.

## Choose the right place for data

- **`instructions` and `goals`:** what the agent should accomplish.
- **`info`:** public case information, such as an identifier.
- **`initial_state`:** internal starting values defined by the State schema.
- **`resources`:** files the case uses, which Environment code can read.
- **`metadata`:** organizational labels, such as an owner or a training or evaluation split.

Plural stores a Task's `reset_options` but does not yet pass them to `reset`. Use `initial_state` or load the case in Environment code instead.

Keep one coherent outcome per Task. Include common cases and important failures, test your Verifiers on known outcomes, and reserve held-out Tasks if you plan to train. Collect Tasks into a [Benchmark](benchmarks.md) to compare agents across the work you care about.
