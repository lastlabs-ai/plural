---
route: /docs/migration/projects
title: "Migrate to 0.15"
order: 510
description: "Breaking changes in 0.15: the standard project layout, one CLI shape for every resource, private pushes, and Jobs for every run."
audience: all
nav: false
---
# Migrate to 0.15

Plural 0.15 organizes everything around a project directory and one command shape.
Each resource lives in its own directory and is addressed by kind and name, as in
`plural task validate refund`. The SDK objects you author (`Environment`, `Task`, the
Verifiers, `Harness`, `Agent`, `Benchmark`, and `Job`) are unchanged. What changed is
how files are laid out, how the CLI finds them, and how they reach a hosted project.

## Breaking changes

### Project layout

A project is a directory that contains `project.yaml`. Commands walk up from the
current directory to find it, so they work from any subdirectory.

```text
project.yaml             name and description
plural.lock              hosted revisions, updated by push and pull; commit it
pyproject.toml           dependencies = ["plural>=0.15"]
.plural/                 local state: hosted binding, Jobs, backups (gitignored)
environments/<name>/     environment.yaml, environment.py, README.md
tasks/<name>/            task.yaml, instruction.md
verifiers/<name>/        verifier.yaml, verify.py
harnesses/<name>/        harness.yaml, harness.py
agents/<name>/           agent.yaml
benchmarks/<name>/       benchmark.yaml, README.md
```

A resource is named by its directory, and its manifest's `name` must match. Manifests
refer to one another by name, for example `environment: support-queue` in a
`task.yaml`. Single-file `job.yaml` and `job.py` projects are no longer read.

### Commands

| Before | Now |
| --- | --- |
| `plural init <dir>` | `plural project init <name>` |
| `plural validate <file>` | `plural <kind> validate <name>` |
| `plural inspect`, `plural export` | `plural <kind> show <name> --json` |
| `plural run job.yaml` | `plural run -b <benchmark> -a <agent>` |
| `plural run <file> --agent <file:attr>` | `plural run -t <task> -m <model>` or `-a <agent>` |
| `plural <kind> publish` | removed; `push` makes a revision available |
| `plural job submit`, `plural job watch` | `plural run --hosted --follow` |
| `plural trial list`, `plural trial watch` | `plural job show <job>`, `plural trial show <trial> --follow` |
| `plural benchmarks show\|export` | `plural benchmark show [--json]`; `benchmarks diff` is removed |
| `plural review hosted-list\|hosted-submit` | `plural review list\|submit` |
| `plural models show` | `plural models list [--provider]` |
| `plural schemas`, `plural harness schema` | `plural.project.manifest_schemas()` in Python, or download [project-schemas.json](../assets/project-schemas.json) |
| `plural login`, `plural logout`, `plural status` | `plural auth login`, `plural auth logout`, `plural auth status` |

Each resource kind (`env`, `task`, `verifier`, `harness`, `agent`, `benchmark`) has the
same verbs: `init`, `validate`, `push`, `pull`, `show`, and `list`. Omitting the name
uses the resource directory you are in.

Removed `plural run` options: `--mode`, `--per-runtime-concurrency`, `--watch` and
`--no-watch` (use `--follow`), `--idempotency-key`, `--api-key` (export
`OPENAI_API_KEY` instead), `--name`, `--format`, and `--catalog`. An Agent is named with
`-a`, or given inline with `-m` and an optional `-h`. Without `-h` the Agent uses
`native`, Plural's built-in tool loop.

### Every run is a Job

`plural run` always creates a Job. A local Job is recorded under
`.plural/jobs/<job-id>/` with the version and content hash of every input it used.
`plural job rerun` and `plural trial rerun` run those pinned inputs again as a new Job
linked to the original, even if the files on disk have changed since. Runs are local
unless you pass `--hosted`, which uses pushed revisions only and fails if a local
input differs from what was pushed.

### Revisions are no longer published

A push creates an immutable revision that is immediately available inside its project.
There is no `publish` step and no "published" status; hosted revisions that were
published before the upgrade are now reported as `available`.

Pushing never makes anything public. Listing a Benchmark on the Hub, or publishing its
results, is a separate action in the Plural web app.

Pushes are duplicate-free: unchanged content reuses the existing revision. Changing a
file without changing `version` is refused, so bump `version` when content changes.
Without `--with-deps`, every dependency must already be pushed with identical content.
Nothing is uploaded unless the whole push can succeed.

A push now uploads the resource's whole directory with the revision, and the revision
stays private to its project. Both the CLI and the service refuse files that look like
credentials (such as `.env` and private keys) and paths that point outside the
resource directory; list anything else you want to leave out in the resource's
`.pluralignore`. `plural <kind> pull` restores a revision's files. It refuses to
overwrite local files that differ unless you pass `--force`, which keeps the old copy
under `.plural/backups/`.

### Authentication and scope

- `plural login`, `logout`, and `status` are now `plural auth login`, `auth logout`, and
  `auth status`. Credentials are still stored in your user config directory or OS
  keyring, never in the project.
- `plural auth scope` chooses where hosted commands go: your account (`.` or
  `--account`) or one hosted project (`-p <name>`). The new scope is checked with the
  service before it is saved; a failed check keeps the previous scope. Scope selects a
  destination only. It never changes what your credential is allowed to do.
- `plural project init <name> --push` creates the hosted project privately, or connects
  to an existing one, records the binding in `.plural/project.json`, and selects
  project scope.
- A push is refused when your scope names a different project than the one the
  checkout is bound to.
- An API key limited to one project can only list, read, and write that project, and
  cannot create projects.

### Models

`plural models list` shows the models your organization allows. Organization admins
can restrict that list; runs, reruns, and gateway calls enforce it on the server.

### Python API

| Before | Now |
| --- | --- |
| `plural.project.Resolver(root=...).load("job.yaml")` | `Workspace(Project.find()).get("benchmark", "<name>")` |
| `plural.load`, `plural.dump`, `plural.dumps` | manifests in the standard layout, loaded with `Workspace` |
| `plural.cli.scaffold.load_harness(path)` | `plural.project.resources.load_harness_directory(path)` |
| `Studio.<kind>.publish(...)` | removed; `Studio.<kind>.push(...)` returns an available revision |

`Job(source, agents=[agent]).run()` still runs locally and is not recorded under
`.plural/jobs`, so `plural job list` does not show it. `Job(..., client=Client())`
still sends model calls through the Plural gateway with your login.

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support-triage")
agent = workspace.get("agent", "careful")
result = Job(benchmark, agents=[agent]).run()
```

## Migrate a project

1. Upgrade: `python -m pip install --upgrade "plural>=0.15"`, or `uv add "plural>=0.15"`
   in a uv-managed project.
2. Create the project: `plural project init <name>` makes `./<name>` with the standard
   files. Run the remaining commands inside it.
3. For each resource, run `plural <kind> init <name>` and move its definition into the
   generated directory. Until you fill a template in, `validate` reports what is still
   missing. A new Environment's template uses the `docker` runtime; set
   `runtime.provider` to what your old project used. Python behavior, such as an
   Environment class or a Verifier
   check, stays Python and is referenced from the manifest, for example
   `python: environment.py:SupportQueue` or `check: verify.py:verify`.
4. Replace object references with names: a Task lists `environment: <name>` and
   `verifiers: [<name>]`, and a Benchmark lists `tasks: [<name>, ...]`.
5. Check everything with `plural benchmark validate <name>`. It validates the
   Benchmark and everything it depends on, and reports every problem at once.
6. Run it: `plural run -b <benchmark> -a <agent> --dry-run`, then without `--dry-run`.
7. Delete `job.yaml`, `job.py`, and any script that called `Resolver`, `dump`, or
   `publish`.
8. To use a hosted project, run `plural auth login`, then
   `plural project init <name> --push` (with the name from `project.yaml`) and
   `plural benchmark push <name> --with-deps`. Commit `plural.lock`.

The [support queue](../tutorials/support-queue.md) and [Wordle](../tutorials/wordle.md)
tutorials are complete projects in this layout.
