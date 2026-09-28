---
route: /docs/tutorials/support-queue
title: Support queue
order: 150
description: Walk through a complete support-triage project, run its Benchmark offline and with a model, read the results, and push it to a private hosted project.
audience: all
nav: true
nav_group: Tutorials
outcome: You can run, inspect, rerun, and adapt a three-ticket support Benchmark from the CLI, then push it and run it hosted.
---
# Support queue

In this tutorial you run a small, finished Plural project: a pretend customer support
desk with three open tickets. An AI reads each ticket, sends it to the right team
(billing, technical, or account), writes a reply, and closes it. A grader then checks
whether it picked the right team.

By the end you will have:

- run a three-ticket exam, first offline and then with a real model,
- read the scores and looked inside one attempt to see what the AI did,
- repeated a run exactly,
- added a fourth ticket of your own, and
- optionally pushed the project to your private hosted project and run it there.

The first half needs no account and no API key, and nothing contacts a real support
system. Every action only changes the pretend desk inside the run.

## Before you start

You need Plural installed; see [Install](../getting-started.md#install). No account or
key is needed until [Run it with a model](#run-it-with-a-model).

[Download the project](../assets/first-project.zip) and unzip it, or copy
`examples/first-project` from the [Plural repository](https://github.com/lastlabs-ai/plural).
Then move into the folder:

```bash
unzip first-project.zip
cd first-project
```

Commands find the project by looking upward from the folder you are in, so from now on
you can run them from anywhere inside `first-project`.

## What is in the project

A Plural project is a folder with one subfolder per piece. Here is the whole support
desk, using the words from [Core concepts](../getting-started/concepts.md):

- **The world** (Environment): `support-queue`, the help desk and its rules.
- **Three assignments** (Tasks): `ticket-1`, `ticket-2`, and `ticket-3`, one ticket each.
- **The grader** (Verifier): `correct-category`, which checks the team and the reply.
- **The exam** (Benchmark): `support-triage`, the three tickets together, with a leaderboard.
- **Three contestants** (Agents): `careful` and `concise` use a real model with different
  instructions; `scripted` follows keyword rules and never calls a model.
- **One way of playing** (Harness): `scripted-triage`, the keyword rules the `scripted`
  Agent uses.

On disk it looks like this:

```text
project.yaml                  project name and description
plural.lock                   hosted revisions; commit it
pyproject.toml                dependencies = ["plural>=0.17.2"]
environments/support-queue/   environment.yaml, environment.py, README.md, resources/policy.md
tasks/ticket-1/, ticket-2/, ticket-3/   task.yaml, instruction.md
verifiers/correct-category/   verifier.yaml, verify.py
harnesses/scripted-triage/    harness.yaml, harness.py
agents/careful/               agent.yaml (a model on the native harness)
agents/concise/               agent.yaml (a model on the native harness)
agents/scripted/              agent.yaml (keyword rules, no model call)
benchmarks/support-triage/    benchmark.yaml, README.md
```

Each folder is named after the thing inside it, and the pieces refer to one another by
those names. The project itself is named `support-queue` in `project.yaml`. Ask Plural
to list what it found:

```bash
plural project show support-queue
```

You should see every piece, grouped by kind:

```text
Project support-queue (local)
  Path:   /path/to/first-project
  Hosted: not registered (`--push` to register)
resource     local names
environment  support-queue
verifier     correct-category
harness      scripted-triage
task         ticket-1, ticket-2, ticket-3
agent        careful, concise, scripted
benchmark    support-triage
```

`Hosted: not registered` is expected. It only means you have not pushed this project
anywhere yet. The next few sections open each piece so you know what the run will do.

### The Environment

The Environment is the help desk. It knows each ticket, including the right answer,
and it offers the AI four moves: `inspect_ticket`, `categorize`, `draft_response`, and
`resolve`.

`environments/support-queue/environment.yaml` names the Python class that holds that
behavior, the files placed in the world, and the limits on each attempt:

```yaml
name: support-queue
version: 1.0.0
description: A customer support queue with one open ticket per Task.
overview: Inspect a customer ticket, categorize it, draft a reply, and resolve it.
python: environment.py:SupportQueue
readme: README.md
resources:
  - resources/policy.md
runtime:
  provider: local
harness_policy:
  mode: allow_all
limits:
  max_turns: 6
  max_seconds: 120
```

Each attempt gets at most 6 turns and 120 seconds. The `local` runtime runs the
Environment directly on your machine, as a trusted subprocess. It is not a sandbox, so
use `docker` instead for code you do not trust.

`environment.py` holds the behavior. The important idea is the split between what the
desk knows and what the AI is shown. **State** is the full truth, including the
`expected` category. The **Observation** is what the AI sees, and it leaves `expected`
out, so the AI can never read the answer:

```python
class QueueState(State):
    ticket_id: str = initial("", description="Which ticket this Task opens.")
    customer_tier: str = ""
    issue: str = ""
    expected: str = ""
    policy: str = ""
    category: str = ""
    draft_reply: str = ""
    status: str = "open"
    done: bool = False


class QueueObservation(Observation):
    ticket_id: str = ""
    customer_tier: str = ""
    issue: str = ""
    policy: str = ""
    category: str = ""
    draft_reply: str = ""
    status: str = "open"
    done: bool = False
```

Each of the four moves is a method marked `@action`, and its docstring is the
description the AI reads. The episode ends when `terminated()` sees the ticket
resolved.

The Environment also defines `reward()`, which gives 0.25 each time the ticket moves
forward, from open to triaged to drafted to resolved. A reward is per-step credit
recorded for training. It never counts toward the score and is never shown to the
Agent.

### The Tasks

A Task is one assignment. Here, each Task opens one ticket by setting the `ticket_id`
State field, the one `environment.py` marks with `initial()`.
`tasks/ticket-1/task.yaml`:

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

The model sees `instruction.md` and the Environment's Observations, and nothing else:
not the State, the score, or the rewards.

### The Verifier

The Verifier is the grader. It marks the finished attempt, not the AI's own claim that
it did well. `verifiers/correct-category/verifier.yaml` points at a small Python check:

```yaml
name: correct-category
version: 0.1.0
kind: deterministic
check: verify.py:verify
weight: 1
```

`verify.py` reads the final State, including the private `expected` category, and
returns a score of 1 or 0 with evidence explaining why:

```python
from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Score 1 when the ticket was resolved with the expected category and a reply."""
    state = episode.state
    drafted = bool(str(state.get("draft_reply") or "").strip())
    correct = bool(state.get("done") and state.get("category") == state.get("expected") and drafted)
    score = float(correct)
    return VerifierOutput(
        score=score,
        scores={"correct_category": score, "response_drafted": float(drafted)},
        evidence=[
            f"status={state.get('status')}",
            f"category={state.get('category')}",
            f"correct={correct}",
        ],
    )
```

The file in the project also returns human-readable `feedback`; it is omitted here.

### The Benchmark and Agents

The Benchmark is the exam. `benchmarks/support-triage/benchmark.yaml` lists the three
Tasks and says how results are ranked:

```yaml
name: support-triage
version: 1.0.0
description: Categorize and resolve support tickets according to policy.
purpose: >-
  Measures whether an Agent reads a ticket and its policy, routes it to the
  right team, and closes it with a reply, which is the core of support triage.
tasks:
  - ticket-1
  - ticket-2
  - ticket-3
scoring:
  metric: Correctly triaged tickets
  description: Share of tickets resolved with the expected category and a drafted reply.
  aggregation: weighted_mean
  score_range: [0.0, 1.0]
  success_threshold: 1.0
  agent_failure: zero
  infrastructure_error: exclude
```

In plain words: each Agent's result is the share of tickets it got right. An attempt
that fails because of the Agent counts as 0, and an attempt lost to an infrastructure
problem is left out and reported separately.

The Agents are the contestants. `agents/careful/agent.yaml` is a model plus
instructions. It names no Harness, so it uses `native`, Plural's built-in tool loop:

```yaml
name: careful
version: 0.1.0
model: openai/gpt-5.6-luna
instructions: Inspect the ticket before categorizing it. Use the Environment actions.
```

`agents/concise/agent.yaml` is the same model with shorter instructions, so you can
compare the two.

`agents/scripted/agent.yaml` runs the `scripted-triage` Harness, which sorts tickets by
keyword instead of calling a model. The `model` is recorded but never called, and
`auth_mode: none` tells Plural the Agent needs no credential:

```yaml
name: scripted
version: 0.1.0
model: openai/gpt-5.6-luna
harness: scripted-triage
auth_mode: none
```

That is the whole project. Time to run it.

## Run it offline

Start with the `scripted` Agent. It needs no account or API key, so it is a quick way
to check that everything is wired together.

First, validate the Benchmark. This also checks every Task, Verifier, and Environment
it depends on:

```bash
plural benchmark validate support-triage
```

Next, ask for a dry run. It shows what would run, and the exact version of every
input, without running anything:

```bash
plural run --benchmark support-triage --agent scripted --dry-run
```

```text
Would run benchmark/support-triage with agent/scripted (openai/gpt-5.6-luna, harness scripted-triage) locally: 3 trial(s), 3 at a time (auto: every Trial at once).
input                      version  content hash
environment/support-queue  1.0.0    sha256:e8f5b9574267
verifier/correct-category  0.1.0    sha256:0a3f50cac523
task/ticket-1              0.1.0    sha256:52486ca1f4f5
task/ticket-2              0.1.0    sha256:dccd443cb4e6
task/ticket-3              0.1.0    sha256:0184b5293170
benchmark/support-triage   1.0.0    sha256:cce07fc58690
harness/scripted-triage    0.1.0    sha256:45d48f6690d2
agent/scripted             0.1.0    sha256:b6a12537ca6a
```

The content hash is a fingerprint of each file's exact contents. Plural records it so
a later run can prove it used the same inputs.

Now run it for real:

```bash
plural run --benchmark support-triage --agent scripted
```

You should see one line per attempt as it finishes, then the result. Your ids will
differ, and because attempts run at the same time, the tickets may finish in a
different order:

```text
Running benchmark/support-triage@1.0.0 with scripted (openai/gpt-5.6-luna) locally: 3 trial(s), 3 at a time (auto: every Trial at once).
  [1/3] trl_d16f384431533c57de0022ee  ticket-3  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/3] trl_ea0e25de78e3905c0f791c67  ticket-2  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
  [3/3] trl_c23042ff033379be000ab471  ticket-1  succeeded  score=1.000  | 3 succeeded, 0 failed, mean 1.000
Job job_9550337c63403bb187d212d1 succeeded.
  scripted: mean score 1.000 over 3 trial(s), 3 succeeded
Details: plural job show job_9550337c63403bb187d212d1
```

That is your first scored run. The whole thing is one **Job**, and each attempt at one
ticket is a **Trial**: three Tasks, one Agent, and one attempt each make three Trials.
Add `--attempts 3` to run each Task three times and see how steady the scores are.

## Run it with a model

Now swap the keyword rules for a real model. These runs call a model through the
Plural gateway and can incur charges.

Every model call needs a Plural API key. You can create one in the web app under Keys.
Store it with `plural auth login --api-key-stdin`, or export it for this terminal:

```bash
export PLURAL_API_KEY=...
```

A browser login is enough to push and run hosted, but the model gateway does not
accept it.

Try one ticket with a model first, then the whole Benchmark with each saved Agent:

```bash
plural run --task ticket-1 --model openai/gpt-5.6-luna
plural run --benchmark support-triage --agent careful
plural run --benchmark support-triage --agent concise
```

`--model` without `--harness` uses `native`, the same loop the `careful` and `concise`
Agents use. To see which models you can run, use `plural models list`. Signed in to an
organization, it lists the models that organization offers; `--all` shows the whole
catalog.

## Read the results

Every run is saved as a new Job under `.plural/jobs/<job-id>/`, with every input pinned
by version and content hash. Three commands take you from the overview down to one
attempt:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

`job list` shows each Job, where it ran, and its status. `job show` gives the Job's
summary and each Trial with its Task, status, and score:

```text
Job job_9550337c63403bb187d212d1 (local) succeeded
  Source: benchmark/support-triage
  Model:  openai/gpt-5.6-luna via scripted-triage
  scripted: mean score 1.000 over 3 trial(s), coverage 100%
trial                         task      status     score
trl_c23042ff033379be000ab471  ticket-1  succeeded  1.000
trl_ea0e25de78e3905c0f791c67  ticket-2  succeeded  1.000
trl_d16f384431533c57de0022ee  ticket-3  succeeded  1.000
```

`trial show` zooms in on one attempt. It prints the score, the grader's evidence, and
where the attempt's files are kept:

```text
Trial trl_ea0e25de78e3905c0f791c67 (local) succeeded
  Job:            job_9550337c63403bb187d212d1
  Task:           ticket-2
  Score:          1.0
  Artifacts:      /path/to/first-project/.plural/jobs/job_9550337c63403bb187d212d1/trials/trl_ea0e25de78e3905c0f791c67/executions/0/artifacts
  Logs:           /path/to/first-project/.plural/jobs/job_9550337c63403bb187d212d1/trials/trl_ea0e25de78e3905c0f791c67/executions/0/logs
  Verifier correct-category: succeeded score=1.0
    - status=resolved
    - category=technical
    - correct=True
```

Ticket 2 was the app crash, and the grader confirms it went to `technical`.

> **Good to know:** A Trial that succeeded can still score 0. That means the Agent
> chose the wrong team or closed the ticket without a reply, not that the run crashed.

When a score surprises you, look at what the Agent actually did before you change the
model or its instructions. If one model gets billing tickets right and account tickets
wrong, compare their trajectories side by side.

### What is in the Artifacts folder

The `Artifacts` directory holds the full record of the attempt:

- `trajectory.json`: the Agent's turns in ATIF, with the Observation after each
  action.
- `episode.jsonl`: the underlying record of every step and model call, one per line.
- `observation.json`: the final Observation, which is what the Agent saw.
- `state.json`: the final State, including the `expected` category the Agent never saw.
- `result.json`: the Agent's final response.

Each Verifier's score, sub-scores, evidence, and feedback are in the Trial's
`result.json`, which `plural trial show` prints.

The `Logs` directory holds the standard output and standard error of the run
(`stdout.log`, `stderr.log`) and of the Verifiers (`verifier.stdout.log`,
`verifier.stderr.log`).

## Rerun exactly

Because every Job pins its inputs, you can repeat one exactly, even after you have
edited your files:

```bash
plural job rerun <job-id>
plural trial rerun <trial-id>
```

A rerun uses the inputs the original Job pinned, not your current files. It creates a
new Job linked to the original, and `job show` on the new Job prints `Rerun of job
<job-id>`. `trial rerun` runs one Trial again as a new one-Trial Job. When you *do*
want your latest edits, run `plural run` again instead.

## Adapt it

Now make the project your own by adding a fourth ticket. This takes four steps.

**1. Add the ticket to the desk.** The tickets live in the Environment, so first add a
`ticket-4` entry to `TICKETS` in `environments/support-queue/environment.py`, with the
same fields as the other three.

**2. Create the Task.** This makes `tasks/ticket-4/` with a starter `task.yaml` and
`instruction.md`:

```bash
plural task init ticket-4 --environment support-queue --verifier correct-category
```

In the new `tasks/ticket-4/task.yaml`, replace `initial_state: {}` with the ticket the
Task opens:

```yaml
initial_state:
  ticket_id: ticket-4
```

**3. Write the instructions.** Replace the `PLURAL-TODO` comment in
`tasks/ticket-4/instruction.md` with what the Agent should do. The text in
`tasks/ticket-1/instruction.md` works for any ticket.

**4. Add it to the exam and run.**

```bash
plural benchmark add ticket-4 --benchmark support-triage
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted
```

You should now see four Trials instead of three.

`validate` does not run the Environment, so a missing `initial_state.ticket_id` or
`TICKETS` entry only shows up as a failed Trial. If you have already pushed the
project, bump `version` in `environment.yaml` and `benchmark.yaml` before you push
again, because `plural <kind> push` refuses changed content under an existing version.
(`plural project push --bump` can give each changed resource the next patch version
for you.)

To judge how *good* the reply is, not only whether there is one, add an
[AgentVerifier](../project/verifiers.md#agentverifier) with a rubric, or a
[HumanVerifier](../project/verifiers.md#humanverifier). A HumanVerifier pauses the
Trial until a person scores it: `plural review list` shows waiting Trials, and
`plural review submit <trial-id> --verifier <name> --score <value>` records the score.

## Push it and run hosted

So far everything ran on your machine. Pushing copies the project to a private hosted
project, so Plural can run it for you and your team can see the results in the web app
under Jobs. This needs a Plural account. From inside the project:

```bash
plural auth login
plural project init support-queue --push
plural benchmark push support-triage --with-deps
plural agent push scripted --with-deps
plural run --benchmark support-triage --agent scripted --hosted --follow
```

Here is what each line does:

1. `plural auth login` opens your browser to sign in. The credential is stored in your
   user config directory or OS keyring, never in the project.
2. `project init --push` takes the name in `project.yaml` (`support-queue`) and
   registers the existing project as it is, without changing any local file. It
   creates a private hosted project, stores the connection in `.plural/project.json`,
   and selects the project as your scope. If that name already exists, add
   `--connect` to use it.
3. `benchmark push --with-deps` pushes the Benchmark and everything it depends on: the
   Tasks, Verifier, and Environment.
4. `agent push --with-deps` pushes the `scripted` Agent and its Harness.
5. `run --hosted` runs the pushed versions on hosted workers, and `--follow` streams
   progress until the Job finishes.

Afterwards `plural job list` shows the hosted Job beside your local ones.

> **Good to know:** Pushing never makes anything public. Listing a project on the Hub
> or publishing a Benchmark is a separate, explicit step in the Plural web app.

### How pushing behaves

For readers who want the precise rules:

- A push validates first and uploads nothing unless the whole push can succeed.
- Pushing unchanged content reuses the existing revision, and a pushed revision is
  available in the private project immediately.
- Push refuses files that look like credentials, such as `.env` or `id_rsa`, and
  manifest paths that point outside the resource directory.
- `plural run --hosted` runs pushed revisions. Before it submits, it pushes any input
  the hosted project does not hold yet; a resource whose content changed while its
  version stayed the same gets the next patch version. If someone else changed that
  resource in the hosted project since your checkout last synced, it stops rather than
  write over their work.

## Where to go next

You have run, read, repeated, extended, and pushed a complete Plural project. From
here:

- [Wordle](wordle.md) is a second project that also runs from Python.
- [Core concepts](../getting-started/concepts.md) explains every word used above.
- The [CLI guide](../cli/evaluation.md) covers the details behind each command.
