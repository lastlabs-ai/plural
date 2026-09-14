---
route: /docs/getting-started
title: Getting started
order: 20
description: Build one public evaluation graph in Python, export the same graph to YAML, and run it locally from the CLI.
audience: all
nav: true
nav_group: Start
outcome: You can author, validate, inspect, export, and dry-run a Job.
---
# Getting started

Plural 0.13.0 requires Python 3.10 or newer:

```bash
python -m pip install "plural==0.13.0"
plural init support-eval
cd support-eval
```

Open the generated Python project. Its essential graph is:

```python
from plural import Agent, Benchmark, Client, Environment, Episode, Job, Runtime, Task
from plural import VerifierOutput
from plural.verifiers import DeterministicVerifier

environment = Environment(name="support-queue", runtime=Runtime.docker())

def resolved(episode: Episode) -> VerifierOutput:
    return VerifierOutput(reward=float(bool(episode.observation.get("done"))))

verifier = DeterministicVerifier(name="resolved", check=resolved)
task = Task(
    name="ticket-1",
    instructions="Resolve the support ticket.",
    environment=environment,
    verifiers=[verifier],
)
benchmark = Benchmark(name="support", version="1.0.0", tasks=[task])
agent = Agent(model="openai/gpt-5.6-luna")
job = Job(benchmark, agents=[agent], client=Client())
```

This is the golden flow throughout the docs: Environment → Verifier → Task →
Benchmark → Agent → Job. Python constructors define field names, defaults, and
validation. YAML stores the same objects and the CLI resolves them.

`Runtime.docker()`, `Runtime.local()`, and `Runtime.daytona()` are the beginner
Runtime API. Harbor defaults are a public network and `python:3.12-slim`.

## Validate before execution

```bash
plural validate project.py:job
plural inspect project.py:job
plural export project.py:job --output job.yaml
plural run job.yaml --dry-run
```

`--dry-run` resolves catalog entries, locks object hashes, checks
Agent–Environment compatibility, and expands Trials. It does not call a model
and does not need credentials.

A live run needs Plural or a bring-your-own key on the Job, not on the Agent:

```bash
plural auth login
plural run job.yaml
```

```python
Job(task, agents=[agent], client=Client())
Job(task, agents=[agent], api_key="sk-...")
```

`Agent.secret_names` is only for extra application secrets declared by a custom
Harness. Model authentication is injected by the Job.

After `plural auth login`, `Client()` reads the stored key. Export
`PLURAL_API_KEY` if you prefer the environment.
