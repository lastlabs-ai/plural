# Plural

Plural is a Python SDK and CLI for building reproducible agent evaluations and
keeping the evidence behind every score.

## Evaluation in eight objects

1. **Environment**: the world, its actions, private State, the Observation the
   Agent sees, resources, and Runtime.
2. **Verifier**: deterministic, Agent, or Human scoring of a finished episode.
3. **Task**: instructions bound to one Environment and its Verifiers.
4. **Benchmark**: a versioned collection of Tasks and the rules for ranking results.
5. **Agent**: a catalog model, instructions, and an optional Harness.
6. **Harness**: the loop that connects an Agent to an Environment. An Agent with
   no Harness uses `native`, Plural's built-in tool loop.
7. **Job**: one run of a Task or Benchmark with one or more Agents and attempts.
8. **Trial**: one Agent on one Task for one attempt, with its trajectory, artifacts,
   and score.

A score is what a Verifier produces, and it is the only thing a Benchmark ranks on.
Per-step rewards from an Environment are recorded for training and never contribute
to a score. Only the Observation is ever shown to the model; scores, rewards, and
private Verifier data never reach it.

## Install

Plural requires Python 3.10 or newer.

```bash
pip install "plural>=0.15"
```

## Try a finished project

The [support queue](examples/first-project/) project includes an Agent that follows
keyword rules instead of calling a model, so it runs offline with no account or key.
From a copy of `examples/first-project`:

```bash
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted
plural job show <job-id>
```

The run prints the Job id and one line per Trial with its score.

## Start your own project

A project is a directory with a `project.yaml`. Each resource is a directory named
after it, and commands find the project by walking up from wherever you run them.

```bash
plural project init my-eval
cd my-eval
plural env init support-desk
plural verifier init resolved
plural task init refund --environment support-desk --verifier resolved
```

Each `init` writes a template. Fill in the places marked `PLURAL-TODO`, then validate.
`validate` checks the resource and everything it depends on, and lists any template
text you left unfinished.

```bash
plural task validate refund
plural run --task refund --model openai/gpt-5.6-luna --dry-run
plural run --task refund --model openai/gpt-5.6-luna
```

`--dry-run` shows the plan and the version of every input without running anything.
`--model` without `--harness` uses `native`. A model call needs an API key:
`plural auth login --api-key-stdin`, `PLURAL_API_KEY`, or `OPENAI_API_KEY` for
OpenAI models. A browser login is not accepted for model calls. Every run is a new
Job, recorded under
`.plural/jobs/<job-id>/` with every input pinned by version and content hash.

## Push to Plural

Runs are local by default. To run on hosted infrastructure, register the project with
a private hosted project, push what the run uses, and add `--hosted`:

```bash
plural auth login
plural project init my-eval --push
plural task push refund --with-deps
plural run --task refund --model openai/gpt-5.6-luna --hosted --follow
```

Credentials are stored in your user config directory or OS keyring, never in project
files. Pushing never makes anything public; sharing is a separate, explicit action in
the Plural web app. The `local` runtime runs code as a trusted subprocess on your
machine; it is not a sandbox.

## Python

The CLI and the SDK load the same resources. From inside the support queue project:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support-triage")
agent = workspace.get("agent", "scripted")
result = Job(benchmark, agents=[agent]).run()
```

Read the [documentation](docs/index.md), starting with
[Getting started](docs/getting-started.md), then the [support queue](docs/tutorials/support-queue.md)
and [Wordle](docs/tutorials/wordle.md) tutorials. Coming from 0.14? Read
[Migrate to 0.15](docs/migration/projects.md).

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
