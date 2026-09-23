---
route: /docs/interfaces/yaml
title: YAML and serialization
order: 125
description: Configure Environments, Tasks, Verifiers, Harnesses, Agents, and Benchmarks as YAML manifests in a project, with Python files supplying executable behavior.
audience: all
nav: true
nav_group: Interfaces
---
# YAML and serialization

Use Python to define behavior and YAML to organize reusable configuration. In a project, every resource is a directory named after it, holding exactly one YAML manifest named after its kind. The CLI and the Python SDK read the same manifests and build the same Plural objects from them.

## One manifest per resource

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

`plural <kind> init <name>` writes each directory from a template, with a comment on every field and a `PLURAL-TODO` marker wherever you must fill something in. Validation reports every marker that is left.

Every manifest follows the same rules:

- `name` must match the directory name.
- `version` defaults to `0.1.0`. Bump it whenever you change a resource you have pushed.
- Other resources are referenced by name within the project, such as `environment: support-queue`.
- Python behavior is referenced as `file.py:Object`, relative to the manifest.
- Files are referenced by paths relative to the manifest, and every path must stay inside the resource directory.
- Unknown keys are errors, not silently ignored. Optional fields use the same defaults as the Python SDK.

Download the JSON Schema for every manifest from [project-schemas.json](../assets/project-schemas.json) to get completion and validation in your editor.

## Start with a small Agent

An `agent.yaml` can contain just the values you want to set:

```yaml
name: careful
model: openai/gpt-5.6-luna
instructions: Use the available actions and check the result before finishing.
```

With no `harness`, the Agent uses `native`, Plural's built-in tool loop. To attach a built-in Harness, name it and set its options:

```yaml
name: support-claude
model: anthropic/claude-sonnet-5
harness: claude-code
harness_kwargs:
  reasoning_effort: high
```

Custom Harness behavior stays in Python, in the project's `harnesses/` directory. The Agent names that Harness:

```yaml
name: support-custom
model: openai/gpt-5.6-luna
harness: support-loop
```

Credentials never belong in a manifest. Supply them when the run starts; see [Harnesses](../project/harnesses.md).

## Reference other resources by name

A Task names its one Environment and its Verifiers. `tasks/ticket-1/task.yaml`:

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

A Benchmark lists its Tasks by name, with the rules for ranking results. It also needs a `README.md` beside `benchmark.yaml`, and unset `scoring` fields take their defaults:

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

A name that does not resolve is reported with the command that creates or restores it. There is no Job file: choose what to run with [`plural run`](../cli/evaluation.md), or construct a `Job` in Python. With three Tasks and one Agent, `plural run --benchmark support-triage --agent careful --attempts 2` plans six Trials.

## Include Python behavior

An Environment needs executable code as well as configuration. `environment.yaml` names the class beside it and the Runtime it runs in:

```yaml
name: support-queue
version: 1.0.0
python: environment.py:SupportQueue
readme: README.md
runtime:
  provider: local
```

A Harness names its subclass and supplies the configuration it reads from `self.config`:

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

Plural imports the referenced object and hashes the resource directory, so helper modules and data files beside it are part of the content hash. There is no command or source block to keep in sync. The `local` runtime is a trusted subprocess, not a sandbox; use `docker` for code you do not trust. The [Environments](../project/environments.md#save-the-environment-in-a-project) page lists every Environment manifest field.

## Load manifests from Python

`plural.project` loads the same manifests the CLI reads, validates them with their dependencies, and returns ordinary SDK objects:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support-triage")
agent = workspace.get("agent", "careful")
result = Job(benchmark, agents=[agent]).run()
```

`Project.find()` walks up from the current directory to the nearest `project.yaml`. `workspace.get` takes a kind name or its CLI noun, so `workspace.get("env", "support-queue")` also works. An invalid resource raises `ProjectError` listing every problem. A Job built this way uses the same resources and content hashes as the equivalent `plural run`; it runs locally and is not recorded under `.plural/jobs/`, so `plural job list` does not show it.

Objects built directly in Python, such as a `Task(...)` in a script, run with `Job` as well. Manifests are how the CLI and hosted projects exchange them.

## Inspect the resolved resource

```bash
plural task validate ticket-1
plural task show ticket-1 --json
```

`validate` loads the resource and everything it depends on and prints its version and content hash. `show --json` adds its dependencies and whether it has been pushed (`"hosted": "not pushed"` until it is). The same verbs exist for `env`, `verifier`, `harness`, `agent`, and `benchmark`.
