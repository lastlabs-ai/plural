---
route: /docs/tutorials/first-project
title: "Build a first project"
order: 116
description: "Create a project in the standard layout, scaffold an Environment, Verifier, Task, Benchmark, and Agent with the CLI, and run it locally."
audience: all
nav: false
---
# Build a first project

This page builds a small support-triage project from empty templates, the same shape
as the finished support queue project. To start from the finished project instead,
[download it](../assets/first-project.zip) and follow the
[support queue tutorial](support-queue.md). You need Plural installed; see
[Install](../getting-started.md#install).

## Create the project

```bash
plural project init support-queue
cd support-queue
```

This works offline. It creates `project.yaml`, `plural.lock`, `pyproject.toml`,
`README.md`, and a `.gitignore` that excludes `.plural/`, where Plural keeps Job
records and other local state. Commit `plural.lock`; Plural updates it when you push.

## Scaffold the resources

```bash
plural env init support-queue
plural verifier init correct-category
plural task init ticket-1 --environment support-queue --verifier correct-category
plural benchmark init support-triage
plural benchmark add ticket-1 --benchmark support-triage
plural agent init careful --model openai/gpt-5.6-luna
```

Each `init` command writes one directory, such as `environments/support-queue/` or
`tasks/ticket-1/`, and marks the places you must fill in with `PLURAL-TODO`:

- `environments/support-queue/environment.py`: the State fields, the Observation the
  Agent sees, and the `@action` methods. Keep answers on State, never on the
  Observation. Mark the fields a Task sets with `initial()`.
- `environments/support-queue/README.md`: what the world is and how to use it.
- `verifiers/correct-category/verify.py`: compare the final State with what the Task
  asked for and return a score from 0 to 1 with evidence.
- `tasks/ticket-1/instruction.md`: what the Agent must accomplish. Set the Task's
  starting State under `initial_state` in `task.yaml`.
- `benchmarks/support-triage/benchmark.yaml` and its `README.md`: the `purpose`, and
  what a score means in `scoring.description`.

Also write the Agent's `instructions` in `agents/careful/agent.yaml`. It has no
`harness`, so it uses `native`, Plural's built-in tool loop.

The finished files in the [support queue tutorial](support-queue.md) show one way to
fill in each of these.

The new Environment uses the `docker` runtime, so Docker must be running when you run
it. The finished project uses `runtime.provider: local` instead, which runs the
Environment as a trusted subprocess on your machine; it is not a sandbox.

## Validate and run

```bash
plural benchmark validate support-triage
plural run --benchmark support-triage --agent careful --dry-run
plural run --benchmark support-triage --agent careful
plural job show <job-id>
```

`validate` checks a resource and everything it depends on, and lists every
`PLURAL-TODO` you left unfinished. `--dry-run` shows the plan without running
anything. The real run calls the model, so it needs an API key
(`plural auth login --api-key-stdin`, `PLURAL_API_KEY`, or `OPENAI_API_KEY` for
`openai/` models). A browser login is not accepted for model calls. The run prints
the Job id to pass to
`plural job show`. To run without any credential, add a Harness that calls no model
and an Agent with `auth_mode: none`, like the `scripted` Agent in the finished project.

To add more tickets, repeat `plural task init` and `plural benchmark add`. When you
want hosted runs, register the project with `plural project init support-queue --push`
and push the Benchmark with `plural benchmark push support-triage --with-deps`; the
[support queue tutorial](support-queue.md#push-it-and-run-hosted) covers both.
Pushing never makes anything public.
