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

Install Plural and create a project:

```bash
pip install plural
plural init word-game
cd word-game
```

Plural has seven plain concepts: Environment, Runtime, Agent, Verifier, Task,
Benchmark, and Job. Python defines their semantics.

```python
from plural import Agent, Benchmark, Environment, Job, Task
from plural.verifiers import DeterministicVerifier

environment = Environment(name="word-game")
verifier = DeterministicVerifier(name="solved", check="python verify.py")
task = Task(
    name="easy",
    instructions="Solve the puzzle.",
    environment=environment,
    verifiers=[verifier],
)
benchmark = Benchmark(name="word-game", version="1.0.0", tasks=[task])
agent = Agent(model="openai/gpt-5.6-luna")
job = Job(benchmark, agents=[agent])
```

Export and reload the exact graph:

```python
from plural.project import dump, load

dump(job, "job.yaml")
assert load("job.yaml").plan == job.plan
```

Every CLI entry loads those same public objects:

```bash
plural validate job.yaml
plural inspect job.yaml
plural run job.yaml --dry-run
plural run job.yaml
```

The default run is local. Use `--hosted` only when you intend to synchronize
and submit the graph to hosted Plural.

Python object references are first-class:

```bash
plural validate project.py:job
plural export project.py:job --output job.yaml
```

Continue with the [Wordle tutorial](tutorials/wordle.md) or read each concept
under Project and Running.
