---
route: /docs/tutorials/first-project
title: "Build a first project"
order: 116
description: "Build a small support-ticket project from empty templates: a world, a grader, a ticket, an exam, and a contestant. Then run it on your computer."
audience: all
nav: false
---
# Build a first project

This page builds a small support-triage project from empty templates. The AI reads a
support ticket and sorts it into the right category, and a grader checks its answer.
It ends up the same shape as the finished support queue project, so you can compare
your work with it at any point.

Prefer to start from the finished project? [Download it](../assets/first-project.zip)
and follow the [support queue tutorial](support-queue.md) instead.

You need Plural installed; see [Install](../getting-started.md#install).

## Create the project

A project is the folder that holds everything you build.

```bash
plural project init support-queue
cd support-queue
```

This works offline. It creates `project.yaml`, `plural.lock`, `pyproject.toml`,
`README.md`, and a `.gitignore` that leaves out `.plural/`, where Plural keeps the
records of your runs and other local state. Commit `plural.lock`; Plural updates it
when you push.

## Scaffold the resources

Each building block gets its own template. You will create five:

- an **Environment** called `support-queue`: the world, a help desk with tickets,
- a **Verifier** called `correct-category`: the grader, which checks the category,
- a **Task** called `ticket-1`: one assignment, a single ticket to sort,
- a **Benchmark** called `support-triage`: the exam, which groups the Tasks, and
- an **Agent** called `careful`: the contestant, a model plus its instructions.

```bash
plural env init support-queue
plural verifier init correct-category
plural task init ticket-1 --environment support-queue --verifier correct-category
plural benchmark init support-triage
plural benchmark add ticket-1 --benchmark support-triage
plural agent init careful --model openai/gpt-5.6-luna
```

Each `init` command writes one folder, such as `environments/support-queue/` or
`tasks/ticket-1/`, and marks every place you must fill in with `PLURAL-TODO`:

- `environments/support-queue/environment.py`: what the world holds (its State), what
  the AI is shown (its Observation), and the moves it can make (its `@action`
  methods). Keep the answers on State, never on the Observation. Mark the fields a
  Task sets with `initial()`.
- `environments/support-queue/README.md`: what the world is and how to use it.
- `verifiers/correct-category/verify.py`: compare how things ended with what the Task
  asked for, and return a score from 0 to 1 with evidence.
- `tasks/ticket-1/instruction.md`: what the AI must accomplish, in plain language. Set
  the Task's starting State under `initial_state` in `task.yaml`.
- `benchmarks/support-triage/benchmark.yaml` and its `README.md`: the `purpose`, and
  what a score means in `scoring.description`.

Also write the Agent's `instructions` in `agents/careful/agent.yaml`. The Agent has no
`harness`, so it plays with `native`, Plural's built-in tool loop.

The finished files in the [support queue tutorial](support-queue.md) show one way to
fill in each of these.

> **Good to know:** The new Environment uses the `docker` runtime, a sealed box that
> keeps the AI's world separate from your computer, so Docker must be running when you
> run it. The finished project uses `runtime.provider: local` instead, which runs the
> Environment as a trusted subprocess on your machine; it is not a sandbox.

## Validate and run

Check your work, preview the run, run it, and look at the result:

```bash
plural benchmark validate support-triage
plural run --benchmark support-triage --agent careful --dry-run
plural run --benchmark support-triage --agent careful
plural job show <job-id>
```

- `validate` checks a resource and everything it depends on, and lists every
  `PLURAL-TODO` you left unfinished.
- `--dry-run` shows the plan without running anything.
- The real run calls the model through the Plural gateway, so it needs a Plural API key
  (`plural auth login`, `plural auth login --api-key-stdin`, or `PLURAL_API_KEY`). The
  run prints the Job id to pass to `plural job show`.

To run without any credential, add a Harness that calls no model and an Agent with
`auth_mode: none`, like the `scripted` Agent in the finished project.

## Next steps

To add more tickets, repeat `plural task init` and `plural benchmark add`.

When you want Plural to run it for you, register the project with
`plural project init support-queue --push` and push the Benchmark with
`plural benchmark push support-triage --with-deps`. The
[support queue tutorial](support-queue.md#push-it-and-run-hosted) covers both. Pushing
never makes anything public.
