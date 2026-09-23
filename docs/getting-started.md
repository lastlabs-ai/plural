---
route: /docs/getting-started
title: Getting started
order: 20
description: Install Plural, create a project, add and validate resources, run a Task locally, then sign in and push to run it on hosted infrastructure.
audience: all
nav: true
nav_group: Start
---
# Getting started

This page takes you from installing Plural to running a Task locally, then on hosted
infrastructure. Read [Core concepts](getting-started/concepts.md) first if the object
names are new. To see a finished project run before you write your own, start with the
[support queue tutorial](tutorials/support-queue.md); it runs offline with no account
or key.

## Install

Plural requires Python 3.10 or newer. With pip:

```bash
python -m pip install "plural>=0.15"
```

With uv, install the `plural` command as a tool:

```bash
uv tool install "plural>=0.15"
```

To use the Python SDK from a uv-managed project, also run `uv add "plural>=0.15"`
inside that project. Optional extras include `plural[daytona]` for the Daytona
Runtime and `plural[keyring]` to store credentials in your OS keyring. Run
`plural --help` to check the install.

## Create a project

A project is a directory that contains `project.yaml`. Creating one works offline and
needs no account:

```bash
plural project init my-eval
cd my-eval
```

That creates `project.yaml`, `plural.lock`, `pyproject.toml`, `README.md`, and a
`.gitignore` that excludes `.plural/`, the directory where Plural keeps local state
such as Job records. `plural.lock` records the hosted revisions your resources
depend on; Plural updates it when you push or pull. Commit it, and do not edit it by
hand.

Every resource is a directory named after it:

```text
project.yaml            name and description
plural.lock             hosted revisions; commit it
pyproject.toml          dependencies = ["plural>=0.15"]
.plural/                local state: hosted binding, jobs/, backups/ (gitignored)
environments/<name>/    environment.yaml, environment.py, README.md, resources/
tasks/<name>/           task.yaml, instruction.md, resources/
verifiers/<name>/       verifier.yaml, verify.py
harnesses/<name>/       harness.yaml, harness.py
agents/<name>/          agent.yaml
benchmarks/<name>/      benchmark.yaml, README.md
```

Commands walk up from the current directory to find `project.yaml`, so you can run
them from anywhere inside the project.

## Add resources

Every resource kind has the same verbs: `init`, `validate`, `show`, `list`, `push`,
and `pull`. `init` writes a template:

```bash
plural env init support-desk
plural verifier init resolved
plural task init refund --environment support-desk --verifier resolved
```

Fill in every place marked `PLURAL-TODO`:

- `environments/support-desk/environment.py`: the State fields, the Observation the
  Agent sees, and the `@action` methods. Keep answers on State, never on the
  Observation.
- `environments/support-desk/README.md`: what the world is and how to use it.
- `verifiers/resolved/verify.py`: compare the final State with what the Task asked
  for and return a score.
- `tasks/refund/instruction.md`: what the Agent must accomplish. Set the Task's
  starting State under `initial_state` in `task.yaml`.

Then validate:

```bash
plural task validate refund
```

```text
task/refund is valid: version 0.1.0, sha256:4c7c807a30fe...
```

`validate` checks a resource and everything it depends on, and lists any template
text you left unfinished. Inside a resource directory you can omit the name:
`plural task validate` in `tasks/refund/` validates `refund`. The same verbs work for
`env`, `task`, `verifier`, `harness`, `agent`, and `benchmark`.

A new Environment uses the `docker` runtime (`runtime.provider: docker` in
`environment.yaml`), so Docker must be running when you run it. The `local` runtime
avoids Docker, but it runs the Environment as a trusted subprocess on your machine and
is not a sandbox; use it only for code you trust.

## Run locally

Run the Task with a catalog model. Start with a dry run:

```bash
plural run --task refund --model openai/gpt-5.6-luna --dry-run
```

```text
Would run task/refund with gpt-5.6-luna (openai/gpt-5.6-luna, harness native) locally: 1 trial(s).
input                     version  content hash
environment/support-desk  0.1.0    sha256:d7b203421527
verifier/resolved         0.1.0    sha256:9f13af9d2534
task/refund               0.1.0    sha256:4c7c807a30fe
```

`--dry-run` shows the plan and the version and content hash of every input without
running anything, and needs no credential. `--model` without `--harness` uses
`native`, Plural's built-in tool loop. `plural models list` shows the model ids you
can use.

A real run calls the model and can incur charges, so it needs an API key. Store a
Plural API key with `plural auth login --api-key-stdin`, export `PLURAL_API_KEY`, or
bring your own OpenAI key for `openai/` models. A browser login is enough for hosted
commands, but the model gateway does not accept it. See [Sign in](#sign-in).

```bash
export OPENAI_API_KEY=...
plural run --task refund --model openai/gpt-5.6-luna
```

Without a credential, the run stops before calling the model and tells you how to add
one.

Every run is a new Job. Plural records it under `.plural/jobs/<job-id>/`, with every
input pinned by version and content hash. The run prints the Job id and one line per
Trial; use them to inspect the results:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
plural job rerun <job-id>
```

`job show` lists each Trial with its Task, status, and score. `trial show` prints the
score, each Verifier's evidence, and where the Trial's artifacts and logs are.
`job rerun` uses the exact pinned inputs, not your current files, and creates a new
Job linked to the original.

To compare Agents across many Tasks, group Tasks into a Benchmark and save an Agent:

```bash
plural benchmark init support
plural benchmark add refund --benchmark support
plural agent init careful --model openai/gpt-5.6-luna
```

Fill in the `PLURAL-TODO` places in `benchmarks/support/benchmark.yaml` (what the
Benchmark measures and what a score means) and `benchmarks/support/README.md`, and
write the Agent's `instructions` in `agents/careful/agent.yaml`. Then validate and
run:

```bash
plural benchmark validate support
plural run --benchmark support --agent careful
```

## Sign in

Hosted runs, pushes, and the Plural gateway need a Plural account. Device login opens
your browser and stores a credential in your user config directory (or your OS
keyring), never in project files:

```bash
plural auth login
plural auth status
```

To use an API key you created in the Plural web app instead, pipe it to
`plural auth login --api-key-stdin`, or set it in the environment:

```bash
export PLURAL_API_KEY=plural_...
```

A browser login acts as you and reaches every account and project your roles allow. It
is not accepted for model calls; use an API key for those. A project key, an API key
limited to one project, can only reach that project and cannot create new ones. Keep
keys out of source files, Agent instructions, and Task files.

Signed in, `plural models list` shows only the models your organization permits.
Organization admins can restrict that list, and the service enforces it when a run
starts.

## Push and run hosted

Pushing needs a hosted project. From inside your project, register it:

```bash
plural project init my-eval --push
```

The name must match `name` in `project.yaml`. The command creates a private hosted
project, or connects to an existing one, records the binding in
`.plural/project.json`, and selects the project as your scope. It does not change any
local file. Then push resources and run:

```bash
plural benchmark push support --with-deps
plural agent push careful --with-deps
plural run --benchmark support --agent careful --hosted --follow
```

`--with-deps` also pushes every resource the Benchmark or Agent depends on that is not
hosted yet. `--follow` streams progress until the Job finishes.

A push validates first and uploads nothing unless the whole push can succeed. Pushing
unchanged content reuses the existing revision; pushing changed content under the same
`version` is refused, so bump `version` when you edit a resource. Push refuses files
that look like credentials, such as `.env` or private keys, and manifest paths that
point outside the resource directory. To leave a file out of a push, list it in a
`.pluralignore` file in the resource directory. A pushed revision is immediately available in its
private project; pushing never makes anything public. Listing a project on the Hub or
publishing a Benchmark is a separate, explicit action in the Plural web app.

`--hosted` runs pushed revisions, and fails if anything the run uses is not pushed
with identical content.

## Scope

Scope is where hosted commands go by default: your account, or one hosted project.

```bash
plural auth scope
plural auth scope --project my-eval
plural auth scope --account
plural auth scope --org personal
```

The first command shows the current scope. `--project` selects an existing hosted
project, `--account` selects account scope, and `--org` switches between organization
accounts (`personal` selects your own). Changing scope changes the selected
destination, never what your credential may do. Plural checks the new scope with the
service before saving it; if the check fails, the previous scope stays in place. A
push is refused when your scope points at a different project than the one this
directory is registered with.

## Use the SDK

The Python SDK loads the same resources the CLI addresses by name:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support")
agent = workspace.get("agent", "careful")
result = Job(benchmark, agents=[agent]).run()
```

That runs locally, like `plural run`, except the Job is not recorded: it does not
appear in `plural job list`, and `plural job rerun` cannot repeat it. A Job that calls
a model reads `OPENAI_API_KEY` or `PLURAL_API_KEY` from the environment. To send model
calls through the Plural gateway, pass a `Client`; `Client()` reads `PLURAL_API_KEY`
or an API key stored with `plural auth login --api-key-stdin`. A browser login is not
accepted:

```python
from plural import Client, Job

job = Job(benchmark, agents=[agent], client=Client())
```

The Job still runs on your machine. The [Python SDK guide](sdk/evaluation.md) covers
the rest of the SDK.

Next, walk through a complete project in the [support queue tutorial](tutorials/support-queue.md),
or read the [CLI guide](cli/evaluation.md) for every command.
