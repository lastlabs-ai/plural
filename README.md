# Plural

Plural is a Python SDK for defining environments, evaluating agents, and
keeping reproducible evidence.

## Seven plain concepts

1. An **Environment** is the world an agent can act in.
2. A **Runtime** says where that world runs.
3. An **Agent** selects a catalog model and optional harness.
4. A **Verifier** scores a completed trial.
5. A **Task** combines instructions, one Environment, and Verifiers.
6. A **Benchmark** pins an ordered set of Tasks.
7. A **Job** runs Agents against a Task or Benchmark.

Python is the semantic source of truth. YAML serializes the same objects
losslessly, and the CLI loads those objects without a second configuration
model.

## Install

```bash
pip install plural
```

## First evaluation

```python
from plural import Agent, Benchmark, Environment, Job, Task
from plural.verifiers import DeterministicVerifier

environment = Environment(name="support")
verifier = DeterministicVerifier(name="complete", check="python verify.py")
task = Task(
    name="ticket-1",
    instructions="Resolve the support ticket.",
    environment=environment,
    verifiers=[verifier],
)
benchmark = Benchmark(name="support", version="1.0.0", tasks=[task])
agent = Agent(model="openai/gpt-5.6-luna")
job = Job(benchmark, agents=[agent])

print(job.plan.trial_count)
```

An `@action` Environment becomes executable with one packaging call:

```python
environment = SupportQueue(runtime=runtime).package(("python", "commands.py"))
```

No `Definition`, `Binding`, protocol version, or hand-built action manifest is
part of the beginner API.

## Python, YAML, and CLI

```python
from plural.project import dump, load

dump(job, "job.yaml")
assert load("job.yaml").content_hash == job.content_hash
```

```bash
plural init
plural validate job.py:job
plural inspect job.yaml
plural export job.py:job --output job.yaml
plural run job.yaml --dry-run
plural run job.yaml
```

Runs are local by default. Hosted submission is always explicit:

```bash
plural run job.yaml --hosted
```

Project model entries are explicit and never global:

```python
from plural import CatalogContext, ModelCatalog, ModelSpec

context = CatalogContext(ModelCatalog(entries=[ModelSpec(id="project/model")]))
agent = context.agent(model="project/model")
```

See the [getting started guide](docs/getting-started.md), the
[Wordle example](examples/wordle/), and the
[CLI reference](docs/reference/cli-commands.md).

## Development

```bash
uv sync --group dev --group docs
uv run ruff check .
uv run pytest
uv run python scripts/check_docs.py
```

## Clean break

The public evaluation API no longer uses `*Definition`, `*Binding`,
`WeightedVerifier`, `EnvironmentRuntime`, or `native_*_v1` names. Internal
execution specs remain implementation details. Migrate public code to the
seven concepts above; see [migration v1](docs/migration/v1.md).

## License

Apache-2.0
