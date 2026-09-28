---
route: /docs/tutorials/cli-walkthrough
title: "Run your first Job"
order: 450
description: "Check, preview, run, inspect, and rerun the support-queue Benchmark from the command line. Everything works offline and without an account until the hosted step."
audience: all
nav: false
---
# Run your first Job

A **Job** is one run you start; each attempt inside it is a **Trial**. This
walkthrough runs a complete Job from the command line and shows you how to read and
repeat it.

It uses the [support queue project](../assets/first-project.zip), a small help desk
where an AI sorts tickets into categories. Its `scripted` Agent follows keyword rules
instead of calling a model, so every command here until
[Run it hosted](#run-it-hosted) works offline, costs nothing, and needs no account.

You need Plural installed; see [Install](../getting-started.md#install).

## Validate and run

Unpack the project, check it, preview the run, then run it:

```bash
unzip first-project.zip
cd first-project
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted --dry-run
plural run --benchmark support-triage --agent scripted
```

- `validate` checks the Benchmark and every Task, Verifier, Environment, and Harness it
  depends on.
- `--dry-run` prints the plan and each input's version and content hash (a fingerprint
  of its exact files) without running anything.
- The real run creates a Job with one Trial per Task, prints each Trial as it
  finishes, and ends with the Agent's mean score:

```text
Running benchmark/support-triage@1.0.0 with scripted (openai/gpt-5.6-luna) locally: 3 trial(s), 3 at a time (auto: every Trial at once).
  [1/3] trl_53c727d33aeaa097dda21e40  ticket-2  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/3] trl_5fd546be688383450e6dd8d2  ticket-3  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
  [3/3] trl_d124de45ec874ebc651f51dc  ticket-1  succeeded  score=1.000  | 3 succeeded, 0 failed, mean 1.000
Job job_7ca838103054ee8c4ae74a51 succeeded.
  scripted: mean score 1.000 over 3 trial(s), 3 succeeded
Details: plural job show job_7ca838103054ee8c4ae74a51
```

Trials run at the same time, so they can finish in any order. The model shown is
recorded on the Agent but never called.

## Inspect and rerun

Every run is a new Job, recorded under `.plural/jobs/<job-id>/` with its inputs pinned
by version and content hash. Use the ids the run printed:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

- `job show` lists each Trial with its Task, status, and score.
- `trial show` prints the score, each Verifier's evidence, and where the Trial's
  artifacts and logs are stored.

To run the exact same experiment again:

```bash
plural job rerun <job-id>
```

A rerun uses the exact inputs the original Job pinned, not your current files, and
creates a new Job linked to the original. That means you can edit the project freely
and still repeat an old result.

## Run it hosted

Runs happen on your computer by default. To have Plural run them on its servers, sign
in, register the project, push what the run uses, and add `--hosted`. This step needs a
Plural account:

```bash
plural auth login
plural project init support-queue --push
plural benchmark push support-triage --with-deps
plural agent push scripted --with-deps
plural run --benchmark support-triage --agent scripted --hosted --follow
```

`plural auth login` opens your browser to sign in, which is enough for hosted commands
like these. Model calls from your own computer need an API key instead; see
[Sign in](../getting-started.md#sign-in).

The credential is stored in your user config folder, never in the project. The hosted
project is private, and pushing never makes anything public. You can also follow the
Job in the web app under **Jobs**.

The [support queue tutorial](support-queue.md) explains each file in the project and
how to read the results.
