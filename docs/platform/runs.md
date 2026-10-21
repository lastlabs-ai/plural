---
route: /docs/platform/runs
title: Track runs and run in the cloud
order: 106
description: "Every Job runs from your machine. Record it in your hosted project with --record, run its Trials in cloud sandboxes with a Runtime, and supply the credentials and secrets a run needs."
audience: all
nav: true
nav_group: Platform
outcome: You can record a run in the web app, move its Trials to cloud sandboxes, and supply its credentials and secrets.
---
# Track runs and run in the cloud

Plural runs every Job from your machine. It never runs a Job on its own servers. Two
independent choices decide what happens around that:

| You want to | Do this |
| --- | --- |
| See runs in the web app and share them with your team | Add `--record`, or push a finished Job with `plural job record` |
| Run Trials somewhere other than your machine | Give the Environment a cloud Runtime, such as Daytona |

The two combine freely: a recorded run of an Environment on Daytona starts each Trial
in a cloud sandbox, and records the Job in the web app as it runs.

## Record a run in the web app

Connect the project folder to a private hosted project once. Run this inside the
folder; it registers the project as it is and overwrites nothing:

```bash
plural project init my-eval --push
```

Then add `--record` to any run:

```bash
plural run --benchmark support --agent careful --record
```

The run still happens here. `--record` first pushes anything the run needs that the
hosted project doesn't hold, such as an edited Task, as its next revision. Then it
opens the hosted Job and reports each Trial as it starts, while it runs, and when it is
scored. Open **Jobs** in the web app to watch it.

| Command | What it records |
| --- | --- |
| `plural run ... --record` | The Job, while it runs |
| `plural job record JOB_ID` | A finished local Job, after the fact |
| `plural job rerun JOB_ID --record` | A rerun of a local Job with exactly the same pinned inputs |

If the connection drops mid-run, the local Job still finishes, and `plural job record`
uploads what was missed. Pushing a recorded Job again records nothing twice. Pushing
never makes anything public.

In the web app, **Run a Job** on the Jobs page and **Rerun** on a Job build the exact
command for you to copy. A Job can be rerun only from the checkout that ran it, since
that's where its record lives.

### Bind a Benchmark run to an evaluation track

A Benchmark can declare evaluation **tracks**, versioned rules that make results
comparable, such as a fixed number of attempts. Only a Job bound to a track can be
ranked on a leaderboard and published. Name the track by id:

```bash
plural run --benchmark support --agent careful --record --evaluation-track controlled
```

The run uses the track's attempts. An Agent that breaks the track's rules, such as a
Harness the track doesn't allow, is refused before anything runs. See
[Benchmarks](../project/benchmarks.md#declare-what-a-release-measures).

## Run Trials in cloud sandboxes

An Environment's `runtime` decides where its Trials execute:

```yaml
runtime:
  provider: daytona
```

| Provider | Where Trials run | You need |
| --- | --- | --- |
| `local` | A process on your machine, with no isolation | Nothing |
| `docker` | A container on your machine | Docker |
| `daytona` | A cloud sandbox | Nothing, on Plural's account |

A Daytona Runtime starts its sandboxes on Plural's Daytona account unless you give it
your own key, so you don't need a Daytona account. Sandboxes are billed to your credits
by the vCPU, memory, and disk they use, and **Usage** shows that compute separately from
model calls. The provider's API key never reaches your machine. A sandbox idle for 30
minutes is stopped, and one running for 6 hours is ended.

A long run that uses up your credits pauses rather than fails: model calls wait until
you add credits, and sandboxes keep their state until the balance is $5 below zero.
See [Out of credits](../operations/troubleshooting.md#a-run-pauses-or-a-model-call-fails-with-out-of-credits).

To size sandboxes, use your own Daytona account, or let an organization decide which
providers members may use, set up a project Runtime. See [Runtimes](../project/runtimes.md).

## Supply credentials and secrets

Apps declare the names of the values they need, and a run fills them in. No value ever
reaches the model or its Harness.

- A **credential** belongs to whoever runs the Agent, such as their own GitHub token.
  Store yours once with `plural credential set NAME`. Each Trial records whose
  credential acted.
- A **secret** belongs to the project, for setup such as a reset command or a
  Verifier's database password. Store it in the hosted project with
  `plural secret set NAME`, and a run fills it in for every member.

`plural run` names any value that's missing before it starts. See
[Apps](../concepts/apps.md) for how an App declares them.

## Where this goes next

- [Push and pull](../guides/studio-sync.md) explains revisions, `plural.lock`, and
  sharing resources with your team.
- [Publish to the Hub](publish.md) shares a Benchmark and its leaderboard.
- [Jobs](../running/jobs.md) covers attempts, concurrency, and retries.
