---
route: /docs/project/benchmarks
title: "Benchmarks"
order: 70
description: A Benchmark is the exam, a fixed set of Tasks with a leaderboard. Build one, run your Agents on it, and choose on correctness, consistency, latency, and cost.
audience: all
nav: true
nav_group: Build
outcome: You can create a Benchmark, run a Job against it, and use those four metrics to choose an agent.
---
# Benchmarks

A **Benchmark** is the exam: a fixed set of Tasks that every Agent sits, plus the
rules for ranking the results. Run several Agents on it and you get a leaderboard
for your own work.

For a support team, a Benchmark might be thirty real tickets: some billing, some
technical, some account questions, and the tricky ones that matter most. Every Agent
works the same thirty tickets, so the comparison is fair.

```mermaid
flowchart LR
  Tasks --> Benchmark
  Benchmark --> Job
  Job --> Metrics
  Metrics --> Decision
```

## How it works, in plain words

**The leaderboard.** You don't score a Benchmark by hand. You run a Job (one run you
start) with the Agents you want to compare. Each Task's grader, its Verifier, scores
every attempt. Plural then ranks the Agents on those scores and shows, beside each
one, how consistent it was, how long it took, and what it cost.

**Versions.** A Benchmark has a version number, like `1.0.0`. Each saved version is a
*release* that never changes. When you add Tasks or change how they are graded, you
save a new version. That way an old result is never quietly compared against a
different exam.

**Scoring rules.** A release can say exactly how its score is built: whether some
Tasks count more than others, what counts as a pass, and what happens when an attempt
crashes. It can also declare *tracks*, the rules that make two results fair to
compare, such as "same loop, no extra instructions, two attempts each". Only the
Verifier score counts. Rewards (small per-step credit used for training) never do.

**Publishing.** Everything you build and run stays private to your project. If you
want others to see a release and its leaderboard, you publish it to the Hub in the
web app. That is a separate, deliberate step, and you see a preview of exactly what
becomes public first.

The usual decision at the end is about cost and correctness together: keep the
Agents that are accurate enough, then prefer the cheaper ones.

## Create a Benchmark

Start from Tasks you already have. Each Task is one case: instructions, an
Environment, and the Verifiers that define success. See [Tasks](tasks.md) if you
still need to write those.

```python
from plural import Agent, Benchmark, Job

benchmark = Benchmark(
    name="support-triage",
    version="1.0.0",
    description="Categorize, answer, and resolve common support requests.",
    tasks=[ticket_1, ticket_2, ticket_3],
)

careful = Agent(
    name="careful",
    model="openai/gpt-5.6-luna",
    instructions="Read the ticket and policy before assigning a category.",
)
concise = Agent(
    name="concise",
    model="openai/gpt-5.6-luna",
    instructions="Complete the ticket using the available actions. Be concise.",
)

job = Job(benchmark, agents=[careful, concise], attempts=2, concurrency=2)
```

That is the whole setup: group the Tasks, choose the Agents, and attach them to a
Job. Task names must be unique. The version is required; every saved version is a
release, and a release never changes.

Choose cases that represent the decisions you need to make. For customer support,
include billing, technical, and account requests, then add the difficult ones that
matter to your product. A small set checks that evaluation works; a representative
set is what you use to choose an Agent.

### Save a Benchmark in a project

In a project, a Benchmark is a folder under `benchmarks/` named after it. It holds
`benchmark.yaml` and a required `README.md` that explains what the Benchmark
measures. Create one and add Tasks by name:

```bash
plural benchmark init support-triage
plural benchmark add ticket-1 --benchmark support-triage
plural benchmark add ticket-2 --benchmark support-triage
plural benchmark add ticket-3 --benchmark support-triage
```

`plural benchmark add` and `plural benchmark remove` edit the `tasks` list in
`benchmark.yaml` and keep its comments. Both are local edits until you push. This is
`benchmarks/support-triage/benchmark.yaml` from the
[first project](../tutorials/first-project.md):

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

- `name` must match the folder name, which is the hosted slug. An optional `title`
  sets the display name.
- Each entry in `tasks` names a Task in `tasks/`.
- Validation requires a `README.md`, a `purpose`, a `scoring.description`, and at
  least one Task.
- The release fields described [further down](#declare-what-a-release-measures), such
  as `categories` and `tracks`, go in `benchmark.yaml` with the same names and nesting
  as the Python arguments.

Check it and save a private copy:

```bash
plural benchmark validate support-triage
plural benchmark push support-triage --with-deps
```

`validate` checks the Benchmark and every Task, Environment, and Verifier it depends
on. `push` saves an immutable, private revision; `--with-deps` also pushes
dependencies that are not hosted yet. Pushing unchanged content reuses the existing
revision, and a changed file under an unchanged `version` is refused. To use the saved
Benchmark from Python, load it with `Workspace(Project.find()).get("benchmark",
"support-triage")` from `plural.project`.

`primary_metric` defaults to `score`, the correctness score written by each Task's
Verifiers. Leave it as `score` unless you have a named Verifier score you want to rank
on.

## Run the Benchmark

The Job expands into Trials, one attempt each: every Agent attempts every Task, once
per `attempts` value. Three Tasks, two Agents, and two attempts make twelve Trials.

From the command line, run a saved Benchmark with one saved Agent at a time. Each
command is a separate Job:

```bash
plural run --benchmark support-triage --agent careful --attempts 2 --concurrency 2 --dry-run
export PLURAL_API_KEY=...   # or: plural auth login --api-key-stdin
plural run --benchmark support-triage --agent careful --attempts 2 --concurrency 2
plural run --benchmark support-triage --agent concise --attempts 2 --concurrency 2
```

- `--dry-run` validates the inputs and prints the plan without calling a model.
- Pass `--model` instead of `--agent` to run a catalog model with no saved Agent.
  Without `--harness` it uses `native`, Plural's built-in tool loop.
- Live runs send every model call through the Plural gateway, so they need a Plural
  API key, such as the one `plural auth login` stores. Calls are billed at the exact
  provider cost.
- Runs are local by default and recorded under `.plural/jobs/`. `--hosted` runs the
  pushed revisions on hosted infrastructure instead.

A Python `Job` can compare several Agents in one Job. `job.run()` returns the results
directly:

```python
result = job.run()
for row in result.aggregates:
    print(
        row.agent_name,
        row.mean_score,
        row.coverage,
        row.total_cost,
        row.mean_latency_seconds,
    )
```

`mean_score` is aggregated by the release's rules (see
[How a score is aggregated](#how-a-score-is-aggregated)); `coverage` is the share of
Tasks with at least one scored attempt.

## Read the four metrics

Every completed Trial records a score, whether later attempts agree, how long it
took, and what it cost. Read them together. An overall average hides the tradeoffs.

### Correctness

Correctness is the Verifier score. For a support ticket, that is usually 1 when the
Agent assigned the right category, drafted a reply, and resolved the ticket, and 0
otherwise. The Benchmark ranks Agents on `primary_metric`, which defaults to this
score.

A Trial can finish running and still score 0. Completing the run is not the same as
doing the work correctly.

### Consistency

`attempts` repeats each Agent and Task pair as independent Trials. Two attempts is
enough to see whether a score is stable. If an Agent solves a ticket once and fails
the same ticket the next time, the average score is hiding unreliable behavior.

Do not use retries for this. Retries recover a failed execution; attempts are the
repeated samples you compare.

### Latency

Latency is how long the Trial took. The Job aggregate is mean latency in seconds per
attempt, over the attempts that reported it. Use it to catch Agents that get the
answer by taking many more turns, or models that are too slow for the workflow.

### Cost

Cost is measured model usage in USD when the runner can attribute it. The Job
aggregate is total cost for that Agent across the Benchmark. Cheaper is only useful
if the Agent is also correct.

### Cost and correctness together

The comparison people actually make is cost against correctness, often called a
Pareto frontier.

An Agent is on the frontier when no other Agent is both more correct and cheaper. A
slightly more expensive Agent is worth it only when it is also more correct. A cheaper
Agent that fails the cases you care about is not a win.

A common rule:

1. Set a correctness floor for the workflow, such as a mean score you will accept.
2. Drop every Agent below that floor.
3. Among the Agents that remain, prefer lower cost. Use latency as the tie-breaker
   when two Agents cost about the same.

Look at the same tradeoff per kind of Task. An Agent may be cheap and correct on
account questions, then expensive and wrong on billing. The Benchmark average will
not tell you that.

## Understand the results

Start with the Job, then one Task, then one Trial:

```bash
plural job list
plural job show JOB_ID
plural trial show TRIAL_ID
```

`job show` prints the Job and its Trials, with the per-case scores behind the
averages. `trial show` prints one Trial's result, Verifier evidence, and the location
of its artifacts and logs. Add `--json` to either for the full record. Hosted Jobs
also appear in the web app under Jobs.

When a score is surprising, open the artifacts folder that `trial show` prints. For a
local Trial it is `.plural/jobs/JOB_ID/trials/TRIAL_ID/executions/0/artifacts/`:

1. **Trajectory** (`trajectory.json`, or `atif-trajectory.json` in ATIF): what the Agent saw, which actions it took, and
   the feedback it received.
2. **Final State and Observation** (`state.json`, `observation.json`): what actually
   changed in the Environment.
3. **Verifier results** (`trial show`, or the Trial's `result.json`): which checks
   passed and the evidence behind the score.
4. **Receipt** (`receipt.json`, one folder up): which Agent, Task, and Runtime
   produced the result.

For a misrouted ticket, check whether the Agent skipped the policy, misunderstood it,
chose an invalid action, or stopped early. These traces explain the observed score.
They do not reveal every internal reason a model made its decision.

Local Jobs stay on your machine. `plural job rerun JOB_ID` runs the exact inputs a Job
pinned again, as a new linked Job, even if your files have changed since. A Job run
with `--hosted` is recorded in the hosted project, where Plural Intel can show it as a
leaderboard.

## Use the findings

Keep the Tasks and scoring stable while you compare Agents. When you add cases, change
a Verifier, or edit the Environment, push the Benchmark again with `--with-deps`. It
becomes a new numbered revision, so earlier results keep their meaning. When the
revision is ready to cite or publish, give it a version with
`plural benchmark release NAME 1.1.0`.

A newer Task or Environment version never changes an existing release. Plural Intel
offers it as an update you review and save as the next release. Scores from different
releases are comparable only on Tasks, scoring, and tracks that did not change. See
[Updating and versioning](updating.md).

Use recurring failures to improve the instructions, the Harness, or the Environment,
or to decide that the work needs [training](../running/training.md). When an Agent
meets the correctness floor at an acceptable cost, apply that choice in
[routing](../reference/integrations.md#route-after-evaluation).

## Publish a release with results

Publishing puts a release and the results you choose on the Hub, where anyone can
see the leaderboard. Pushing a Benchmark keeps it private to its project; publishing
to the Hub is a separate, explicit step on Plural Intel:

1. Pick which results to publish. Each is frozen from exactly the Jobs it ran in, on
   one track; untracked runs are never published.
2. Choose whether Task instructions and Verifier findings on example attempts are
   public. Both are private by default because they can reveal answers. Traces,
   Verifier setups, hidden state, resources, and secrets are never published.
3. Read the preview of exactly what becomes public, then publish.

A published release never changes. It is addressed by a reference such as
`plural:benchmark/support-triage@1.1.0#sha256:…`. Corrections and withdrawals add a
new manifest to the history; earlier manifests stay readable.

Others can submit results against an exact release and track. Every result is labelled
Plural-executed, independently reproduced, or self-reported. That label says how a
result was produced. It does not say whether the Benchmark is a good one.

The public manifest is described in
[Benchmark publications](../architecture/benchmark-publications.md).

## Going deeper

The rest of this page is for readers who want to control exactly how a release is
scored and ranked.

### Declare what a release measures

A release can say what it measures, how its score is built, and which comparisons are
fair. All of these fields are optional. A Benchmark without them still runs, but it
cannot rank results officially until it declares a track.

```python
from plural import Benchmark, BenchmarkCategory, BenchmarkScoring, EvaluationTrack

benchmark = Benchmark(
    name="support-triage",
    version="1.1.0",
    tasks=[ticket_1, ticket_2, ticket_3],
    purpose="How reliably an Agent resolves common support requests end to end.",
    success="The ticket is categorized, answered, and resolved according to policy.",
    limitations=["English tickets only.", "No phone or chat channels."],
    license="CC-BY-4.0",
    categories=[
        BenchmarkCategory(id="billing", name="Billing", tasks=["ticket-1", "ticket-2"]),
        BenchmarkCategory(id="technical", name="Technical", tasks=["ticket-3"]),
    ],
    scoring=BenchmarkScoring(task_weights={"ticket-3": 2}),
    tracks=[
        EvaluationTrack(
            id="controlled",
            name="Controlled",
            kind="models",
            instructions="none",
            attempts=2,
            description="Built-in loop, no extra instructions, two attempts.",
        ),
        EvaluationTrack(id="open", name="Open systems", kind="agents"),
    ],
    default_view="models",
)
```

- **Categories** group Tasks so results can be read per category. Their ids are
  stable; keep them when you rename. A category only means something inside its
  Benchmark: two Benchmarks' "Billing" scores are not comparable.
- **Scoring** declares the score range, the success threshold, Task weights, how much
  coverage an entry needs to rank, and whether Agent failures count as zero or are
  excluded.
- **Tracks** are versioned comparison rules: attempts, retries, allowed Harnesses,
  instructions, tools, inference settings, and turn, time, and cost limits. A
  **Models** track holds everything but the model constant. An **Agents** track
  compares complete systems as built. A track may not be looser than a Task's
  Environment limits.

A track's rules are hashed. Changing any rule of an existing track requires a new
track `version`, so results already tied to the old version keep their meaning.
Renaming or re-describing a track does not.

### How a score is aggregated

The score of one configuration on one release and track is built in two steps, so a
Task with many attempts never outweighs a Task with few:

1. Attempts at the same Task are averaged. Every attempt the track requires counts;
   the best attempt is never selected.
2. Task averages are combined with the release's declared weights, equal by default.

Each attempt is classified before it is scored:

| Outcome | Examples | Effect |
| --- | --- | --- |
| Scored | The Verifiers returned a score | Counts |
| Agent failure | The Agent crashed, gave up, or hit its turn, time, or cost limit | Zero by default, or excluded if the release says so |
| Infrastructure error | Provider outage, lost machine, sandbox failure | Excluded and shown |
| Cancelled or still running | | Not counted; blocks official ranking while running |

A Task with no scored attempt is unknown, not zero. An entry ranks officially only
when it ran on a track, covers the release's declared share of Tasks (all of them by
default), and every required attempt has finished. Anything else is still shown,
labelled as not ranked, with the reasons.

The interval shown beside a score is a 95% normal approximation over Task scores. It
is reported only when at least `min_tasks_for_interval` Tasks (five by default) have
results, and it does not include attempt-to-attempt variation. Cost is USD per attempt
and latency is seconds per attempt, each averaged over the attempts that reported
them; the count of measured attempts is always shown. Per-step Environment rewards are
never part of a score.
