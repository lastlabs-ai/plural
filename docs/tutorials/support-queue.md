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

This project simulates a customer support queue. The Agent inspects a ticket, assigns
it to billing, technical, or account, drafts a reply, and resolves it. A deterministic
Verifier scores 1 when the ticket is resolved with the right category and a reply.

You need Plural installed; see [Install](../getting-started.md#install). No account or
key is needed until [Run it with a model](#run-it-with-a-model).
[Download the project](../assets/first-project.zip) and unzip it, or copy
`examples/first-project` from the [Plural repository](https://github.com/lastlabs-ai/plural).
The actions change local evaluation state only; nothing contacts a real support system.

```bash
unzip first-project.zip
cd first-project
```

## What is in the project

```text
project.yaml                  project name and description
plural.lock                   hosted revisions; commit it
pyproject.toml                dependencies = ["plural>=0.15"]
environments/support-queue/   environment.yaml, environment.py, README.md, resources/policy.md
tasks/ticket-1/, ticket-2/, ticket-3/   task.yaml, instruction.md
verifiers/correct-category/   verifier.yaml, verify.py
harnesses/scripted-triage/    harness.yaml, harness.py
agents/careful/               agent.yaml (a model on the native harness)
agents/concise/               agent.yaml (a model on the native harness)
agents/scripted/              agent.yaml (keyword rules, no model call)
benchmarks/support-triage/    benchmark.yaml, README.md
```

Each resource is a directory named after it, and resources refer to one another by
name. The project itself is named `support-queue` in `project.yaml`, and
`plural project show support-queue` lists its resources:

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

Commands find the project by walking up from the current directory, so you can run
them from any subdirectory.

### The Environment

`environments/support-queue/environment.yaml` names the Python class, the files staged
into the runtime, and the per-Trial limits:

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

The `local` runtime runs the Environment as a trusted subprocess on your machine. It is
not a sandbox; use `docker` for code you do not trust.

`environment.py` defines the behavior. State holds the whole ticket, including the
`expected` category. The Observation class leaves `expected` out, so the Agent never
sees the answer:

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

The four actions are `inspect_ticket`, `categorize`, `draft_response`, and `resolve`.
Each is a method marked `@action`, and its docstring is the description the Agent
reads. The episode ends when `terminated()` sees the ticket resolved.

The Environment also defines `reward()`, which credits 0.25 for each status the ticket
advances, from open to triaged to drafted to resolved. Rewards are per-step credit
recorded for training. They never contribute to the score and are never shown to the
Agent.

### The Tasks

Each Task opens one ticket by setting the `ticket_id` State field that
`environment.py` marks with `initial()`. `tasks/ticket-1/task.yaml`:

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

`verifiers/correct-category/verifier.yaml` points at a Python check:

```yaml
name: correct-category
version: 0.1.0
kind: deterministic
check: verify.py:verify
weight: 1
```

`verify.py` reads the final State, including the private `expected` category, and
returns a score with evidence:

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

`benchmarks/support-triage/benchmark.yaml` lists the three Tasks and how results rank:

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

`agents/careful/agent.yaml` is a model with instructions. It names no harness, so it
uses `native`, Plural's built-in tool loop:

```yaml
name: careful
version: 0.1.0
model: openai/gpt-5.6-luna
instructions: Inspect the ticket before categorizing it. Use the Environment actions.
```

`agents/concise/agent.yaml` is the same model with shorter instructions, so you can
compare the two.

`agents/scripted/agent.yaml` runs the `scripted-triage` Harness, which routes tickets
by keyword instead of calling a model. The `model` is recorded but never called, and
`auth_mode: none` tells Plural the Agent needs no credential:

```yaml
name: scripted
version: 0.1.0
model: openai/gpt-5.6-luna
harness: scripted-triage
auth_mode: none
```

## Run it offline

The `scripted` Agent needs no account or API key. Validate the Benchmark, which also
validates every Task, Verifier, and Environment it depends on, then run it:

```bash
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted --dry-run
plural run --benchmark support-triage --agent scripted
```

`--dry-run` prints the plan and each input's version and content hash without running
anything:

```text
Would run benchmark/support-triage with agent/scripted (openai/gpt-5.6-luna, harness scripted-triage) locally: 3 trial(s).
input                      version  content hash
environment/support-queue  1.0.0    sha256:e8f5b9574267
verifier/correct-category  0.1.0    sha256:0a3f50cac523
task/ticket-1              0.1.0    sha256:52486ca1f4f5
task/ticket-2              0.1.0    sha256:dccd443cb4e6
task/ticket-3              0.1.0    sha256:0184b5293170
benchmark/support-triage   1.0.0    sha256:cce07fc58690
harness/scripted-triage    0.1.0    sha256:08b617418c4d
agent/scripted             0.1.0    sha256:d4611af090c0
```

The real run prints one line per Trial, then the Job's result. Your ids will differ:

```text
Running benchmark/support-triage with scripted (openai/gpt-5.6-luna) locally: 3 trial(s).
  trl_b6991b19a99ed402d9de2a77  ticket-1  succeeded  score=1.000
  trl_c2f6511b9ba8e29056f007ee  ticket-2  succeeded  score=1.000
  trl_3afd9a846afc6455beecec42  ticket-3  succeeded  score=1.000
Job job_7d83afa695e6cb8d51f52e1a succeeded.
  scripted: mean score 1.000 over 3 trial(s), 3 succeeded
Details: plural job show job_7d83afa695e6cb8d51f52e1a
```

Three Tasks, one Agent, and one attempt each make three Trials. Add `--attempts 3` to
run each Task three times and see how stable the scores are.

## Run it with a model

These runs call a model and can incur charges. Store a Plural API key with
`plural auth login --api-key-stdin`, or export `PLURAL_API_KEY`. A browser login is
enough to push and run hosted, but the model gateway does not accept it. Or bring
your own OpenAI key, which works for `openai/` models:

```bash
export OPENAI_API_KEY=...
```

Then run one Task with a model directly, or the whole Benchmark with a saved Agent:

```bash
plural run --task ticket-1 --model openai/gpt-5.6-luna
plural run --benchmark support-triage --agent careful
plural run --benchmark support-triage --agent concise
```

`--model` without `--harness` uses `native`, the same loop the `careful` and `concise`
Agents use. `plural models list` shows the models you can run; signed in, it shows
only the models your organization permits.

## Read the results

Every run is a new Job recorded under `.plural/jobs/<job-id>/`, with every input
pinned by version and content hash.

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

`job list` shows each Job with where it ran and its status. `job show` lists each Trial
with its Task, status, and score:

```text
Job job_7d83afa695e6cb8d51f52e1a (local) succeeded
  Source: benchmark/support-triage
  Model:  openai/gpt-5.6-luna via scripted-triage
trial                         task      status     score
trl_b6991b19a99ed402d9de2a77  ticket-1  succeeded  1.000
trl_c2f6511b9ba8e29056f007ee  ticket-2  succeeded  1.000
trl_3afd9a846afc6455beecec42  ticket-3  succeeded  1.000
```

`trial show` prints the score, each Verifier's evidence, and where the artifacts and
logs are:

```text
Trial trl_c2f6511b9ba8e29056f007ee (local) succeeded
  Job:            job_7d83afa695e6cb8d51f52e1a
  Task:           ticket-2
  Score:          1.0
  Artifacts:      /path/to/first-project/.plural/jobs/job_7d83afa695e6cb8d51f52e1a/trials/trl_c2f6511b9ba8e29056f007ee/executions/0/artifacts
  Logs:           /path/to/first-project/.plural/jobs/job_7d83afa695e6cb8d51f52e1a/trials/trl_c2f6511b9ba8e29056f007ee/executions/0/logs
  Verifier correct-category: succeeded score=1.0
    - status=resolved
    - category=technical
    - correct=True
```

When a score is surprising, open the files in the `Artifacts` directory:

- `trajectory.jsonl`: the steps the Harness recorded, one per line, with the
  Observation after each action.
- `observation.json`: the final Observation, which is what the Agent saw.
- `state.json`: the final State, including the `expected` category the Agent never saw.
- `verifier-results.json`: each Verifier's score, sub-scores, evidence, and feedback.
- `result.json`: the Agent's final response.

The `Logs` directory holds the standard output and standard error of the run
(`stdout.log`, `stderr.log`) and of the Verifiers (`verifier.stdout.log`,
`verifier.stderr.log`).

A Trial that succeeded can still score 0. That means the Agent chose the wrong
category or resolved without a reply, not that the run crashed. If one model gets
billing tickets right and account tickets wrong, compare their trajectories before
changing the model or instructions.

## Rerun exactly

```bash
plural job rerun <job-id>
plural trial rerun <trial-id>
```

A rerun uses the inputs the original Job pinned, not your current files, and creates a
new Job linked to the original; `job show` on the new Job prints `Rerun of job
<job-id>`. `trial rerun` runs one Trial again as a new one-Trial Job. Edit a Task and
run `plural run` again when you want the new content.

## Adapt it

To add a ticket, first add a `ticket-4` entry to `TICKETS` in
`environments/support-queue/environment.py`, then create the Task:

```bash
plural task init ticket-4 --environment support-queue --verifier correct-category
```

In the new `tasks/ticket-4/task.yaml`, replace `initial_state: {}` with the ticket the
Task opens:

```yaml
initial_state:
  ticket_id: ticket-4
```

Replace the `PLURAL-TODO` comment in `tasks/ticket-4/instruction.md` with the
instructions; the text in `tasks/ticket-1/instruction.md` works for any ticket. Then add the Task
to the Benchmark, validate, and run:

```bash
plural benchmark add ticket-4 --benchmark support-triage
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted
```

`validate` does not run the Environment, so a missing `initial_state.ticket_id` or
`TICKETS` entry only shows up as a failed Trial. If you have already pushed the
project, bump `version` in `environment.yaml` and `benchmark.yaml` before you push
again, because a push refuses changed content under an existing version.

To judge the quality of the reply rather than only its presence, add an
[AgentVerifier](../project/verifiers.md#agentverifier) with a rubric, or a
[HumanVerifier](../project/verifiers.md#humanverifier). A HumanVerifier pauses the
Trial until someone scores it: `plural review list` shows waiting Trials, and
`plural review submit <trial-id> --verifier <name> --score <value>` records the score.

## Push it and run hosted

Pushing needs a Plural account. From inside the project:

```bash
plural auth login
plural project init support-queue --push
plural benchmark push support-triage --with-deps
plural agent push scripted --with-deps
plural run --benchmark support-triage --agent scripted --hosted --follow
```

`plural auth login` opens your browser and stores the credential in your user config
directory or OS keyring, never in the project. `project init --push` takes the name in
`project.yaml` (`support-queue`) and registers the existing project as it is, without
changing any local file. It creates or connects a private hosted project, stores the
binding in `.plural/project.json`, and selects the project as your scope.
`--with-deps` also pushes the Tasks, Verifier, Environment, and Harness the resource
depends on. `--follow` streams progress until the Job finishes.

A push validates first and uploads nothing unless the whole push can succeed. Pushing
unchanged content reuses the existing revision, and a pushed revision is available in
the private project immediately. Push refuses files that look like credentials, such
as `.env` or `id_rsa`, and manifest paths that point outside the resource directory.
Pushing never makes anything public; listing a project on the Hub or publishing a
Benchmark is a separate, explicit action in the Plural web app.

`--hosted` runs the pushed revisions. It fails if anything the run uses is not pushed
with identical content, so push again after you edit a resource. `plural job list`
then shows the hosted Job beside your local ones.

Next, read [Wordle](wordle.md) for a second project that also runs from Python, or
[Core concepts](../getting-started/concepts.md) and the [CLI guide](../cli/evaluation.md)
for the details behind each command.
