# wordle

Wordle as a Plural project in the standard layout. The Environment keeps the secret
word on State, so the Agent only ever sees the board.

```
environments/wordle/     environment.yaml, environment.py, README.md
tasks/{crane,slate,point}/  task.yaml, instruction.md   (one secret word each)
verifiers/solved/        verifier.yaml, verify.py
harnesses/word-list/     harness.yaml, harness.py       (guesses a fixed list, no model)
agents/word-list/        agent.yaml                     (runs the word-list Harness)
agents/luna/             agent.yaml                     (a model on the native harness)
benchmarks/wordle/       benchmark.yaml, README.md
run.py                   the same run from the Python SDK
```

## Run it offline

The `word-list` Agent calls no model, so this needs no account or key:

```bash
plural benchmark validate wordle
plural run --benchmark wordle --agent word-list
plural job show <job-id>
```

The same run from Python loads the same resources by name:

```bash
python run.py
```

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "wordle")
agent = workspace.get("agent", "word-list")
result = Job(benchmark, agents=[agent]).run()
```

## Run it with a model

This calls a model and can incur charges:

```bash
plural auth login                      # or: export OPENAI_API_KEY=...
plural run --task crane --model openai/gpt-5.6-luna
plural run --benchmark wordle --agent luna
```

## Push it to Plural

```bash
plural project init wordle --push      # creates a private hosted project
plural benchmark push wordle --with-deps
plural run --benchmark wordle --agent luna --hosted
```

Pushing never makes anything public.
