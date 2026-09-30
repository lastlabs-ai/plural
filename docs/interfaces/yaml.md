---
route: /docs/interfaces/yaml
title: YAML and serialization
order: 125
description: Describe Environments, Tasks, Verifiers, Harnesses, Agents, and Benchmarks as short YAML files in a project, with Python files supplying any behavior.
audience: all
nav: true
nav_group: Interfaces
---
# YAML and serialization

Most of a Plural project is plain settings: which model an Agent uses, which Tasks a
Benchmark holds, which grader marks a Task. You write those settings in short YAML
files, a simple format of `key: value` lines that is easy to read and review. Anything
that has to *do* something, like the rules of a game, lives in a Python file beside it.

This page is for anyone who edits a project's files directly. The CLI and the Python
SDK read the same files and build the same Plural objects from them, so a project
works the same way from either.

The smallest useful file is an Agent, a model plus its instructions, in
`agents/careful/agent.yaml`:

```yaml
name: careful
model: openai/gpt-5.6-luna
instructions: Use the available actions and check the result before finishing.
```

## One manifest per resource

Each resource is a folder named after it, holding exactly one YAML file named after
its kind. That file is the resource's **manifest**. A project looks like this:

```text
project.yaml                  project name and description
plural.lock                   written by Plural and updated by push; commit it, do not edit it
environments/<name>/          environment.yaml, environment.py, README.md, optional resources/
tasks/<name>/                 task.yaml, instruction.md, optional resources/
verifiers/<name>/             verifier.yaml, verify.py
harnesses/<name>/             harness.yaml, harness.py
agents/<name>/                agent.yaml
benchmarks/<name>/            benchmark.yaml, README.md
```

You rarely start from a blank file. `plural <kind> init <name>` writes each folder from
a template, with a comment on every field and a `PLURAL-TODO` marker wherever you must
fill something in. Validation reports every marker that is left.

Every manifest follows the same rules:

- `name` must match the folder name.
- `version` is optional. It asks for a release version on the next push, and you
  never need to change it when you edit a resource: the hosted project numbers each
  pushed revision itself.
- Other resources are referenced by name within the project, such as
  `environment: support-queue`.
- Python behavior is referenced as `file.py:Object`, relative to the manifest.
- Files are referenced by paths relative to the manifest, and every path must stay
  inside the resource folder.
- Unknown keys are errors, not silently ignored. Optional fields use the same defaults
  as the Python SDK.

> **Tip:** Download the JSON Schema for every manifest from
> [project-schemas.json](../assets/project-schemas.json) to get completion and
> validation in your editor.

## Start with a small Agent

An `agent.yaml` can contain just the values you want to set, like the `careful` Agent
above. With no `harness`, the Agent uses `native`, Plural's built-in tool loop. A
**Harness** is the loop that decides what the model does next. To attach a built-in
Harness, name it and set its options:

```yaml
name: support-claude
model: anthropic/claude-sonnet-5
harness: claude-code
harness_kwargs:
  reasoning_effort: high
```

Custom Harness behavior stays in Python, in the project's `harnesses/` folder. The
Agent names that Harness:

```yaml
name: support-custom
model: openai/gpt-5.6-luna
harness: support-loop
```

Credentials never belong in a manifest. Supply them when the run starts; see
[Harnesses](../project/harnesses.md).

## Reference other resources by name

Resources point at each other by name. A **Task** (one assignment) names its one
Environment and its Verifiers (graders). `tasks/ticket-1/task.yaml`:

```yaml
name: ticket-1
version: 0.1.0
instructions: instruction.md
environment: support-queue
verifiers:
  - correct-category
info:
  ticket_id: ticket-1
initial_state:
  ticket_id: ticket-1
```

A **Benchmark** (the exam) lists its Tasks by name, with the rules for ranking
results. It also needs a `README.md` beside `benchmark.yaml`, and unset `scoring`
fields take their defaults:

```yaml
name: support-triage
version: 1.0.0
description: Categorize and resolve support tickets according to policy.
purpose: Measures whether an Agent routes a ticket to the right team and closes it.
tasks:
  - ticket-1
  - ticket-2
  - ticket-3
scoring:
  description: Share of tickets resolved with the expected category and a drafted reply.
```

A name that does not resolve is reported with the command that creates or restores
it.

There is no Job file. Choose what to run with [`plural run`](../cli/evaluation.md), or
construct a `Job` in Python. With three Tasks and one Agent,
`plural run --benchmark support-triage --agent careful --attempts 2` plans six Trials
(two attempts at each Task).

## Include Python behavior

An **Environment** (the world the Agent acts in) needs code as well as settings.
`environment.yaml` names the class beside it and the Runtime it runs in:

```yaml
name: support-queue
version: 1.0.0
python: environment.py:SupportQueue
readme: README.md
runtime:
  provider: local
```

A Harness names its subclass and supplies the configuration it reads from
`self.config`:

```yaml
name: support-loop
version: 1.0.0
python: harness.py:SupportHarness
config:
  max_turns: 12
```

A deterministic Verifier names its function:

```yaml
name: correct-category
version: 0.1.0
kind: deterministic
check: verify.py:verify
```

Plural imports the referenced object and hashes the whole resource folder, so helper
modules and data files beside it are part of the content hash. There is no command
or source block to keep in sync.

> **Good to know:** The `local` runtime is a trusted subprocess, not a sandbox. Use
> `docker` for code you do not trust.

The [Environments](../project/environments.md#save-the-environment-in-a-project) page
lists every Environment manifest field.

## Load manifests from Python

`plural.project` loads the same manifests the CLI reads, validates them with their
dependencies, and returns ordinary SDK objects:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support-triage")
agent = workspace.get("agent", "careful")
result = Job(benchmark, agents=[agent]).run()
```

- `Project.find()` walks up from the current folder to the nearest `project.yaml`.
- `workspace.get` takes a kind name or its CLI noun, so
  `workspace.get("env", "support-queue")` also works.
- An invalid resource raises `ProjectError` listing every problem.
- A Job built this way uses the same resources and content hashes as the equivalent
  `plural run`. It runs locally and is not recorded under `.plural/jobs/`, so
  `plural job list` does not show it.

Objects built directly in Python, such as a `Task(...)` in a script, run with `Job` as
well. Manifests are how the CLI and hosted projects exchange them.

## Inspect the resolved resource

To see exactly what Plural will use, after names are resolved and defaults filled in:

```bash
plural task validate ticket-1
plural task show ticket-1 --json
```

`validate` loads the resource and everything it depends on and prints its version and
content hash. `show --json` adds its dependencies and whether it has been pushed
(`"hosted": "not pushed"` until it is). The same verbs exist for `env`, `verifier`,
`harness`, `agent`, and `benchmark`.
