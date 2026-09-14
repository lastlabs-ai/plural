# Plural

Plural 0.13.0 is a Python SDK and CLI for building reproducible agent
evaluations and keeping the evidence behind every score.

## Evaluation in seven objects

1. **Environment** — world, actions, State, Observation, resources, and Runtime.
2. **Verifier** — deterministic, Agent, or Human scoring.
3. **Task** — instructions bound to one Environment and its Verifiers.
4. **Benchmark** — immutable versioned Task pins.
5. **Agent** — catalog model, instructions, and optional Harness.
6. **Harness** — optional custom model interaction loop.
7. **Job** — Agents × Tasks × attempts, with retries and evidence.

Python is the semantic source of truth. YAML serializes the same objects
losslessly, and the CLI uses the same resolver and defaults.

## Install

```bash
pip install "plural==0.13.0"
```

## First evaluation

```python
from pathlib import Path
from plural import Agent, Benchmark, Job, Task
from plural.verifiers import DeterministicVerifier

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
benchmark = Benchmark(name="support", version="1.0.0", tasks=(task,))
agent = Agent(model="openai/gpt-5.6-luna", instructions="Use the available actions.")
job = Job(benchmark, agents=(agent,))

print(job.plan.trial_count)
```

Here `environment` is a packaged `Environment` instance. Typed Python actions
become executable with one packaging call:

```python
environment = SupportQueue(runtime=runtime).package(
    ("python", "commands.py"),
    source="environment",
)
```

Validate and run the same graph:

```bash
plural init support-eval
cd support-eval
plural validate project.py:job
plural export project.py:job --output job.yaml
plural inspect job.yaml
plural run job.yaml --dry-run
```

After implementing the Environment and Verifier, `plural run job.yaml` uses
local orchestration by default. The Environment Runtime still selects trusted
local subprocess, Docker, Daytona, or an installed provider plugin. Hosted
submission is explicit:

```bash
plural run job.yaml --hosted
```

Start with the [documentation](docs/index.md), the executable
[support queue](examples/first-project/), and [Wordle](examples/wordle/).

## Development

```bash
uv sync --group dev --group docs
uv run ruff check .
uv run mypy --strict src/plural tests/typing/consumer.py
uv run pytest
uv run python scripts/check_docs.py
uv run mkdocs build --strict
```

## License

Apache-2.0
