# support-queue

A complete Plural project in the standard layout: one Environment, three Tasks, one
Verifier, a Benchmark, two model Agents, and a scripted Agent that needs no model.

```
environments/support-queue/   environment.yaml, environment.py, README.md, resources/policy.md
tasks/ticket-{1,2,3}/         task.yaml, instruction.md
verifiers/correct-category/   verifier.yaml, verify.py
harnesses/scripted-triage/    harness.yaml, harness.py
agents/careful/               agent.yaml   (model, native harness)
agents/concise/               agent.yaml   (model, native harness)
agents/scripted/              agent.yaml   (keyword harness, no model call)
benchmarks/support-triage/    benchmark.yaml, README.md
```

## Run it offline

The `scripted` Agent follows keyword rules instead of calling a model, so this works
without an account or API key:

```bash
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted
plural job list
plural trial show <trial-id>
plural job rerun <job-id>
```

Every run is a new Job under `.plural/jobs/`, with the exact inputs recorded. A rerun
uses those pinned inputs, not your current files.

## Run it with a model

These call a model and can incur charges:

```bash
export OPENAI_API_KEY=...                # or: plural auth login
plural run --task ticket-1 --model openai/gpt-5.6-luna
plural run --benchmark support-triage --agent careful
```

`--model` without `--harness` uses `native`, Plural's built-in tool loop.

## Push it to Plural

```bash
plural auth login
plural project init support-queue --push       # creates a private hosted project
plural benchmark push support-triage --with-deps
plural agent push scripted --with-deps
plural run --benchmark support-triage --agent scripted --hosted
```

Pushing never makes anything public. The `local` runtime is a trusted subprocess, not
a sandbox; switch `runtime.provider` to `docker` for code you do not trust.
