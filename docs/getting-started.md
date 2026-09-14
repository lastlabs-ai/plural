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

Plural 0.12.1 requires Python 3.10 or newer:

```bash
python -m pip install "plural==0.12.1"
plural init support-eval
cd support-eval
```

Open the generated Python project. Its essential graph is:

```python
from pathlib import Path
from plural import Agent, Benchmark, Environment, ExecutionTarget, Job, Runtime, Task
from plural import NetworkMode
from plural.verifiers import DeterministicVerifier

environment = Environment(
    name="support-queue",
    runtime=Runtime(
        provider="docker",
        image="python:3.12-slim",
        network=NetworkMode.FULL,
        targets=frozenset({ExecutionTarget.DOCKER}),
    ),
)
verify = Path("verify.py").read_text(encoding="utf-8")
verifier = DeterministicVerifier(
    name="resolved",
    check=("python", "-c", verify),
)
task = Task(
    name="ticket-1",
    instructions="Resolve the support ticket.",
    environment=environment,
    verifiers=[verifier],
)
benchmark = Benchmark(name="support", version="1.0.0", tasks=[task])
agent = Agent(
    model="openai/gpt-5.6-luna",
    secret_names=("OPENAI_API_KEY",),
)
job = Job(benchmark, agents=[agent])
```

This is the golden flow throughout the docs: Environment → Verifier → Task →
Benchmark → Agent → Job. Python constructors define field names, defaults, and
validation. YAML stores the same objects and the CLI resolves them.

## Validate before execution

```bash
plural validate project.py:job
plural inspect project.py:job
plural export project.py:job --output job.yaml
plural run job.yaml --dry-run
```

`--dry-run` resolves catalog entries, locks object hashes, checks
Agent–Environment compatibility, and expands Trials. It does not call a model.

The scaffold is a planning skeleton, not a complete scorer. Add executable
Environment and Verifier implementations before removing `--dry-run`. A live
native run also needs an OpenAI-compatible endpoint credential explicitly
granted by the Agent:

```bash
export OPENAI_API_KEY=...
plural run job.yaml
```

That command calls a model and may incur provider charges. The Docker Runtime
above permits network access; use a more restrictive policy when your endpoint
supports it. To use Plural Gateway instead, grant `PLURAL_API_KEY`, set
`PLURAL_GATEWAY_URL`, and supply that value in the execution environment.

Local is the orchestration default; it does not mean offline networking or
unsafe local processes. The Environment's `runtime.provider` decides where
execution happens. Hosted synchronization is always explicit:

```bash
plural run job.yaml --hosted
```

## Use the complete starter

The repository's support project contains an executable Environment adapter,
deterministic Verifier, three Tasks, two Agents, and generated YAML:

```bash
cd examples/first-project
python build.py
plural validate job.yaml
plural run benchmark.yaml \
  --agent agents/careful.yaml \
  --agent agents/concise.yaml \
  --dry-run
```

Continue with [Core concepts](getting-started/concepts.md), then the
[support queue tutorial](tutorials/support-queue.md).
