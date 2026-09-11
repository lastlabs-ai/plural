---
route: /docs/tutorials/wordle
title: "Wordle"
order: 110
description: "Walk a filled-in Plural scaffold: Environment, Verifiers, Tasks, an offline Harness, Agents, a Benchmark, and a Job you can run without an API key."
audience: all
nav: true
nav_group: Tutorial
outcome: You can run the Wordle Job and point at the file that owns each object.
---
# Wordle

This is the Getting started scaffold with the placeholders filled in. The filenames are the same. The world is a five-letter guessing game.

From the Last Labs repo:

```bash
pip install plural
cd examples/wordle
plural env validate environment
plural task validate tasks/easy-01.yaml
plural run job.yaml --offline
```

You should see a succeeded Trial. The constraint solver usually finishes `easy-01` in a handful of guesses. No account is required.

```
environment/     world: rules, reset, guess, hidden answers
verifiers/       solved.py and budget.py
tasks/           five puzzles; secrets are not here
harness/         offline player
agents/          wordle-solver and wordle-naive
benchmark.yaml   the five Tasks
job.yaml         one Task Job
```

## Follow one episode

`environment/environment.py` holds `SECRETS` and official marking. `commands.py` is the stdin/stdout adapter Jobs call. `environment.yaml` is the definition a Task pins.

`tasks/easy-01.yaml` asks the Agent to play Warm-up. It does not contain `slate`. `verifiers/solved.py` reads `environment_view` and checks the last guess against the hidden secret.

`harness/harness.py` calls `reset` and `guess`. If the Agent name contains `naive`, it walks a fixed list. Otherwise it keeps only words consistent with the board.

`job.yaml` is one Task and one Agent. The suite is:

```bash
plural run benchmark.yaml --agent agents/solver.yaml --agent agents/naive.yaml --offline
```

That is Agents × five Tasks. Each Trial gets its own Trace.

This page does not re-teach Environments or Jobs. If a file is confusing, open the matching project page: [Environments](../project/environments.md), [Tasks](../project/tasks.md), [Verifiers](../project/verifiers.md), [Agents](../project/agents.md), [Jobs](../running/jobs.md).
