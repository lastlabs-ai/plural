# Plural

Plural is a Python SDK and CLI for finding out which AI is good at *your* work. You
describe the work once, run any model against it, and keep the evidence behind every
score.

## The idea, in eight words

1. **App**: one system the AI works with, such as a game written in Python, an MCP
   server, or an HTTP API. What its actions return is all the AI sees; its State stays
   hidden.
2. **Environment**: the world, made of Apps, plus where it runs and its limits.
3. **Task**: one assignment in an Environment, in plain language.
4. **Verifier**: the grader. Its `check` scores the finished work, and it can give
   rewards along the way for training.
5. **Agent**: a model plus its instructions.
6. **Benchmark**: a versioned set of Tasks, ranked by score.
7. **Job**: one run of Agents on a Task or Benchmark.
8. **Trial**: one Agent on one Task, once, with its full record.

Several Agents can also share one Task, to cooperate or compete: give the Environment
a `party`, and each Agent plays from its own seat with its own view and score.

Only what an action returns ever reaches the model. Scores, rewards, App State,
credentials, and secrets never do.

## Install

Plural requires Python 3.10 or newer.

```bash
pip install "plural[mcp]>=0.21.0"
```

## Try a finished project

The [support queue](examples/first-project/) includes an Agent that follows keyword
rules instead of calling a model, so it runs offline with no account. From a copy of
`examples/first-project`:

```bash
plural benchmark validate support-triage
plural run --benchmark support-triage --agent scripted
plural job show <job-id>
```

## Start your own

```bash
plural project init my-eval
cd my-eval
plural env init support-desk
plural auth login --api-key-stdin
plural run --task support-desk-first --model openai/gpt-5.6-luna
```

`plural env init` writes an Environment with a working example Task and Verifier, so
the first run scores straight away. Replace each place marked `PLURAL-TODO` with your
own work; `plural task validate support-desk-first` lists the ones left. To start from
an MCP server, an API, or traces instead, use `plural app add`; see
[Create an Environment](docs/start/index.md).

Every model call goes through the Plural gateway, billed at the provider's price, so a
real run needs a Plural API key from [pluralintel.com](https://pluralintel.com). Every
run is a Job, recorded under `.plural/jobs/` with each input pinned by version and
content hash, so `plural job rerun` repeats it exactly.

Every Job runs from your machine. To see it in the web app as well, connect the folder
to a private hosted project and add `--record`:

```bash
plural project init my-eval --push
plural run --task refund --model openai/gpt-5.6-luna --record
```

To run Trials in cloud sandboxes, set the Environment's `runtime` to a provider such as
`daytona`. Pushing never makes anything public.

## Python

The CLI and the SDK load the same resources:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support-triage")
agent = workspace.get("agent", "scripted")
result = Job(benchmark, agents=[agent]).run()
```

## Learn more

Start with the [Quickstart](docs/getting-started.md), or read
[Core concepts](docs/getting-started/concepts.md) first. Coming from 0.20? The
[changelog](CHANGELOG.md) lists every breaking change and what to write instead.

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
