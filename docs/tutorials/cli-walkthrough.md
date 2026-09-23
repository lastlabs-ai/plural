---
route: /docs/tutorials/cli-walkthrough
title: "Run your first Job"
order: 450
description: "Validate, dry-run, run, inspect, and rerun the support-queue Benchmark from the command line, offline and without credentials."
audience: all
nav: false
---
# Run your first Job

This walkthrough uses the [support queue project](../assets/first-project.zip). Its
`scripted` Agent follows keyword rules instead of calling a model, so every command
here until [Run it hosted](#run-it-hosted) works offline and without an account. You
need Plural installed; see [Install](../getting-started.md#install).

## Validate and run

```bash
unzip first-project.zip
cd first-project
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted --dry-run
plural run --benchmark support-triage --agent scripted
```

`validate` checks the Benchmark and every Task, Verifier, Environment, and Harness it
depends on. `--dry-run` prints the plan and each input's version and content hash
without running anything. The real run creates a Job with one Trial per Task and
prints their ids:

```text
Running benchmark/support-triage with scripted (openai/gpt-5.6-luna) locally: 3 trial(s).
  trl_b6991b19a99ed402d9de2a77  ticket-1  succeeded  score=1.000
  trl_c2f6511b9ba8e29056f007ee  ticket-2  succeeded  score=1.000
  trl_3afd9a846afc6455beecec42  ticket-3  succeeded  score=1.000
Job job_7d83afa695e6cb8d51f52e1a succeeded.
  scripted: mean score 1.000 over 3 trial(s), 3 succeeded
Details: plural job show job_7d83afa695e6cb8d51f52e1a
```

## Inspect and rerun

Every run is a new Job, recorded under `.plural/jobs/<job-id>/` with its inputs
pinned. Use the ids the run printed:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

`job show` lists each Trial with its Task, status, and score. `trial show` prints the
score, each Verifier's evidence, and where the Trial's artifacts and logs are stored.

Rerun it:

```bash
plural job rerun <job-id>
```

A rerun uses the exact inputs the original Job pinned, not your current files, and
creates a new Job linked to the original.

## Run it hosted

Local execution is the default. To run on hosted infrastructure, sign in, register the
project, push what the run uses, and add `--hosted`. This needs a Plural account:

```bash
plural auth login
plural project init support-queue --push
plural benchmark push support-triage --with-deps
plural agent push scripted --with-deps
plural run --benchmark support-triage --agent scripted --hosted --follow
```

The credential is stored in your user config directory, never in the project. The
hosted project is private, and pushing never makes anything public. The
[support queue tutorial](support-queue.md) explains each file in the project and how
to read the results.
