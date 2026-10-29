---
route: /docs/cli/evaluation
title: CLI guide
order: 120
description: Create a project, validate and push its resources, run Tasks and Benchmarks, and inspect, rerun, and review the resulting Jobs.
audience: all
nav: true
nav_group: Interfaces
---
# CLI guide

The `plural` command-line tool (CLI) runs Plural from your terminal. With it you set
up a project, check your work, run models against your Tasks, and read back the
scores. This page is for anyone comfortable typing commands; it starts with the few
you need and ends with a complete reference for power users.

## What the CLI is

Everything you build in Plural lives in a **project**. On your computer, that is a
folder with a `project.yaml` file and one subfolder per resource, such as
`environments/wordle/` or `tasks/crane/`. The CLI reads and writes that folder.

Commands name a resource by its folder name. Most resource commands also work with no
name at all, and then act on the resource folder you are in. If words like Task,
Agent, or Benchmark are new, read [Core concepts](../getting-started/concepts.md)
first.

## The commands most people need

Most days you only need these:

```bash
plural project init support-eval
plural task validate ticket-1
plural run -t ticket-1 -m openai/gpt-5.6-luna
plural job list
plural job show JOB_ID
```

In order: create a project, check a Task is ready, run it with one model, list your
runs, and open one to see its scores. Every run is recorded as a **Job**, and each
attempt inside it is a **Trial**. A live run needs a Plural API key; see
[Run](#run).

Commands that print data, such as `validate`, `show`, `list`, and `run`, accept
`--json` for machine-readable output.

Projects written for Plural 0.14 or earlier use a different layout; see
[Migrate to 0.15](../migration/projects.md).

## Create a project

```bash
plural project init support-eval
cd support-eval
plural env init support-queue --python
plural verifier init correct-category
plural task init ticket-1 -e support-queue --verifier correct-category
plural benchmark init support-triage
plural benchmark add ticket-1 -b support-triage
plural agent init careful -m openai/gpt-5.6-luna
```

This builds the support queue example: a world (the Environment), a grader (the
Verifier), one ticket to work (the Task), an exam that holds it (the Benchmark), and a
contestant (the Agent).

`plural project init` works offline. Each resource `init` command writes a template
with places marked `PLURAL-TODO` for you to fill in. A new Environment and Verifier
need real behavior before a run means anything; the
[support queue tutorial](../tutorials/support-queue.md) provides both. `agent init`
needs a model: pass `-m`, or pick one when it asks. `plural model list` shows the
models you may use.

> **Good to know:** A new Environment uses the `docker` runtime, so Docker must be
> running when you run it. The `local` runtime avoids Docker, but it is a trusted
> subprocess on your machine, not a sandbox.

To check your work, use `validate` and `show`. `validate` checks a resource and
everything it depends on without uploading anything, and reports every `PLURAL-TODO`
that is still unfinished. `show` prints the local copy of a resource, or the hosted
one when there is no local copy. A local copy that is not valid yet is shown with its
problems listed under it, so you can see what is left right after `init`:

```bash
plural benchmark validate support-triage
plural task show ticket-1
plural project show support-eval
```

## Run

`plural run` answers two questions: *what* to run and *who* runs it. Pick exactly
one of each:

- **What:** one Task (`-t`) or a whole Benchmark (`-b`).
- **Who:** a catalog model (`-m`) or a saved Agent (`-a`).

```bash
plural run -t ticket-1 -m openai/gpt-5.6-luna
plural run -b support-triage -a careful
plural run -b support-triage -m openai/gpt-5.6-luna --harness codex
```

Every run is a new Job. A local run executes on this machine and records the Job
under `.plural/jobs/<job-id>/` in the project.

A run that calls a live model sends every call through the Plural gateway, so it
needs a Plural API key: the one `plural auth login` stores,
`plural auth login --api-key-stdin`, or `PLURAL_API_KEY`. `--dry-run` needs no key,
and neither does an Agent with `auth: none`.

### Run options

These options change what a run does. Most people only reach for `--dry-run` and
`--attempts`.

- **`-h HARNESS`** picks the Harness, the loop that decides what the model does next.
  `-m` without `-h` uses `native`, Plural's built-in tool loop. `-h` names a Harness
  in `harnesses/` or a built-in one such as `codex` or `claude-code`.
- **`--dry-run`** validates the inputs and prints the plan, including the version and
  content hash of every input, without running anything.
- **`--attempts N`** plans N independent Trials per Task. It defaults to 1.
- **`--concurrency N`** (or `-n N`) runs up to N Trials at once. It defaults to
  `auto`, which sizes it from this machine, the Runtime, and where the model runs;
  see [Attempts and concurrency](../guides/jobs.md#attempts-and-concurrency).
- **`--plural-version`** selects the Plural installed in Docker and remote sandboxes:
  a version, or `latest`. By default it is this CLI's own code; see
  [Plural inside Docker and remote sandboxes](../guides/jobs.md#plural-inside-docker-and-remote-sandboxes).
- **`--record`** also records the run in your hosted project. **`--evaluation-track ID`**
  runs a Benchmark under one of its evaluation tracks so the results can be
  published, and implies `--record`; see [Hosted projects](#hosted-projects).

Add `@` and a revision to a Task, Benchmark, or Agent to run that exact pushed
revision, such as `plural run -b support-triage@1.0.0 -a careful` or
`plural run -b support-triage@3 -a careful`, even after your files have moved on.
After `@`, give a revision number, a release version, or a content hash. The revision
is restored under `.plural/versions` without touching your files; see
[Calling a revision by name](../project/updating.md#calling-a-revision-by-name).

## Jobs, Trials, and reviews

After a run, these commands let you look back at what happened, run it again, or add
a human's score.

```bash
plural job list
plural job show JOB_ID
plural job rerun JOB_ID
plural trial show TRIAL_ID
plural trial rerun TRIAL_ID
plural review list
plural review submit TRIAL_ID --verifier policy-review --score 2 \
  --feedback "Meets policy."
```

- `job list` shows local and hosted Jobs, newest first, labeled by where they ran.
- `job show` and `trial show` look for a local record first and then ask the hosted
  project. `trial show` includes the Verifier's evidence and the Trial's artifacts.
  Add `--follow` to either to stream progress until it finishes.
- `job rerun` runs a Job again with the exact pinned inputs it used and creates a new
  Job linked to the original. `trial rerun` runs one Trial again as a new one-Trial
  Job. Add `--record` to either to record a local rerun in the hosted project as it
  runs.
- `review list` shows Trials waiting for a HumanVerifier score, and `review submit`
  records one. Use one `--score criterion=value` per rubric criterion, or a bare value
  for a one-criterion rubric. Add `--hosted` to either for hosted review assignments.
  Submissions are append-only.

See [Jobs](../running/jobs.md) and [Reviews](../running/reviews.md).

## Models

To see which models you can run, list them:

```bash
plural model list
plural model list --provider openai
plural model list --all
```

Outside an organization, and when you are signed out, it shows the whole catalog.
`--provider` narrows the list to one provider.

Signed in to an organization, `plural model list` shows the models your organization
offers: its own endpoints and private models, and any an admin has explicitly
allowed. `--all` shows the whole catalog and marks models your organization does not
permit, which the hosted service refuses on runs and gateway calls. The same list,
with prices, is in the model Catalog in the web app.

## Hosted projects

Local runs need no hosted project. A hosted project is a private copy of your project
on Plural, which lets your team share resources and see every run in the web app.
Plural never runs a Job itself; every Job runs from the machine that starts it. To use
one, sign in and push:

```bash
plural auth login
plural project init support-eval --push
plural benchmark push support-triage --with-deps
plural agent push careful
plural run -b support-triage -a careful --record
```

> **Good to know:** Pushing never makes anything public. The hosted project is
> private, and sharing is a separate action in the Plural web app.

`plural project init --push` creates the hosted project. If that name already exists,
pass `--connect` to bind to it or `--name` to create a different one. The command
records the binding in `.plural/project.json` and selects the project as your scope.
`plural project push` then uploads every local resource.

A push creates an immutable, private revision that is usable in that project
immediately. A push validates first, uploads nothing unless the whole push can
succeed, and refuses files that look like credentials, such as `.env` or private
keys. Changed content becomes the resource's next numbered revision, and
`plural <kind> release NAME VERSION` names one with a version people can cite. See
[Push and pull](../guides/studio-sync.md).

A run on this machine is recorded in the hosted project with `--record`, or after it
finishes with `job record`:

```bash
plural run -b support-triage -a careful --record
plural job record JOB_ID
```

`--record` records the Job while it runs. Before it starts, it pushes any input of the
run that the hosted project does not hold yet, as a new numbered revision of any input
whose files changed; an input someone else changed in the hosted project since you
last synced stops the push before anything is uploaded. `job record` records a local Job
that already finished; it pins the
revisions that Job ran, so push those first. Both produce the same hosted Job, so
recording a Job again uploads only what the hosted Job does not hold yet. The
Environment's Runtime still decides where Trials execute, so a recorded run against a
Daytona Environment runs remotely. See
[Record runs and run in the cloud](../platform/runs.md).

### Sign-in and scope

There are two ways to sign in. A browser login stores a 30-day API key for the
account selected in the browser that approves it. Or store an API key you created
under Keys:

```bash
plural auth login
plural auth login --api-key-stdin
plural auth login --from-env
plural auth status
```

`--api-key-stdin` reads the key from standard input, `--from-env` stores
`PLURAL_API_KEY` from your environment without printing it, and `--env-file PATH`
reads `PLURAL_API_KEY` from a file. `plural auth logout` revokes and removes the
stored credential. `plural auth status` shows which credential is in use, a browser
login or an API key, and the current scope.

`plural auth scope` shows or changes where hosted commands go:

```bash
plural auth scope
plural auth scope -p support-eval
plural auth scope --account
plural auth scope --org acme
```

`-p` selects an existing hosted project, `--account` selects account scope, and
`--org` switches between organization accounts (`personal` selects your own). A new
scope is checked with the service before it is saved; if the check fails, the
previous scope stays in place.

Scope selects a destination and never changes what your credential may do. An API key
limited to one project can only reach that project. Credentials are stored in your OS
keyring or a private file in your user config directory, never in the project.

## Portable sessions

`plural session export` bundles an Agent's session, from a hosted Trial
(`--trial TRIAL_ID`) or from local files (`--agent-file`, `--environment-file`,
`--state`), into a
directory you can move elsewhere. `plural session import BUNDLE` redeploys that bundle
as a separate instance directory. The reference below lists every option.

## Command reference

The rest of this page is for power users and scripts: the full help text of every
command and option, exactly as the CLI prints it. Renamed commands and options keep
their old names for one release, print a note naming the new form, and are left out
of this reference: `plural env add` and `env eject-files` (now `plural app add`),
`job push` (`job record`), `credential unset` (`credential delete`), `plural models`
and `plural rewards` (`model` and `reward`), `pull --revision` (`NAME@REF`),
`auth scope .` (`--account`), `app add --env` (`--server-env`), and `session export
--agent`/`--environment` and `session import --dest` (`--agent-file`,
`--environment-file`, and `--out`).

<!-- generated-cli-reference -->
This section is generated from the Typer application. Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.

### `plural`

```text

 Usage: plural [OPTIONS] COMMAND [ARGS]...

 Build, push, and run Plural projects.

 Start with `plural project init <name>`, add resources with `plural
 <env|task|verifier|harness|agent|benchmark> init <name>`, and run them with `plural run --task
 <name> --model <model>`.

 Objects:

   Environment  `plural env init`: Apps, where they run, and limits.
   App          `plural app add ENV`: one system the Agent works with.
   Task         `plural task init`: instructions, an Environment, Verifiers.
   Verifier     `plural verifier init`: decides what counts as good work.
   Harness      `plural harness init`: the loop that drives the model.
   Agent        `plural agent init --model`: model, instructions, Harness.
   Benchmark    `plural benchmark init`: Tasks to rank Agents on.
   Runtime      `plural runtime create`: where Environments run.
   secret       `plural secret set`: a project value for Apps and Verifiers.
   credential   `plural credential set`: your own value, carried by an Agent.
   external     `plural external init`: an agent that runs elsewhere, traced.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version                     Show the installed Plural version and exit.                        │
│ --install-completion          Install completion for the current shell.                          │
│ --show-completion             Show completion for the current shell, to copy it or customize the │
│                               installation.                                                      │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ run         Run one Task or Benchmark with a model or a saved Agent. Every run is a new Job.     │
│ auth        Sign in, sign out, and choose the hosted account or project commands use.            │
│ project     Create, register, and inspect projects.                                              │
│ credential  Save your own values for the credentials Agents carry, such as your CRM token.       │
│ app         Add, list, and remove the Apps in an Environment.                                    │
│ env         Create, validate, push, pull, and inspect Environments.                              │
│ verifier    Create, validate, push, pull, and inspect Verifiers.                                 │
│ harness     Create, validate, push, pull, and inspect Harnesses.                                 │
│ task        Create, validate, push, pull, and inspect Tasks.                                     │
│ agent       Create, validate, push, pull, and inspect Agents.                                    │
│ benchmark   Create, validate, push, pull, and inspect Benchmarks.                                │
│ job         List, inspect, and rerun Jobs.                                                       │
│ trial       Inspect and rerun Trials.                                                            │
│ review      List and submit human reviews.                                                       │
│ reward      Show a Trial's rewards and export training data. Add rewards with `plural verifier   │
│             apply`.                                                                              │
│ model       List the models you may run.                                                         │
│ runtime     Choose where Environments run.                                                       │
│ secret      Set the project's setup values, stored encrypted in the hosted project.              │
│ session     Export and redeploy portable agent sessions.                                         │
│ external    Register an agent that runs as its own service, and trace its runs to Plural.        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent`

```text

 Usage: plural agent [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Agents.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a saved Agent: a model, instructions, and an optional Harness.                  │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ release   Label the revision matching your files with a release version, pushing it first.       │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ delete    Delete a resource's local folder, refusing while other local resources use it.         │
│ key       Print a new signing key for an external Agent.                                         │
│ test      Send an external Agent a signed ping, and report how it answered.                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent delete`

```text

 Usage: plural agent delete [OPTIONS] {name}

 Delete a resource's local folder, refusing while other local resources use it.

 Without --hosted this is a local edit: the hosted project keeps the
 resource until you add --hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Agent to delete. [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted            Also delete it from the hosted project. Jobs and Trials that pinned its      │
│                     revisions can still read them.                                               │
│ --yes     -y        Delete without asking.                                                       │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent init`

```text

 Usage: plural agent init [OPTIONS] {name}

 Create a saved Agent: a model, instructions, and an optional Harness.

 With --external, the Agent is a service you run elsewhere; --model is
 then the label it reports, such as acme/takeoff-v3.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Agent name. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --model     -m      <str>  Catalog model id, from `plural model list`. Asked for when omitted in │
│                            a terminal.                                                           │
│ --harness           <str>  Harness name.                                                         │
│ --external          <str>  The https URL of an agent service of your own, which the Job calls    │
│                            for each episode instead of running a Harness.                        │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent key`

```text

 Usage: plural agent key [OPTIONS]

 Print a new signing key for an external Agent.

 Store it as the Agent's signing_key secret here, and as
 PLURAL_SIGNING_KEY in the agent's service. Plural never keeps it.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent list`

```text

 Usage: plural agent list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent pull`

```text

 Usage: plural agent pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

 Name a retained revision as NAME@REF.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also replace dependencies you already have with the exact revisions it      │
│                      pins. Missing dependencies are always restored.                             │
│ --force              Replace local files that differ. The old copy is kept under                 │
│                      .plural/backups.                                                            │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent push`

```text

 Usage: plural agent push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps               Also push local dependencies that are not hosted yet.                  │
│ --force                   Add a revision even though the hosted resource moved since you last    │
│                           synced.                                                                │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent release`

```text

 Usage: plural agent release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource to release. [required]                                         │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent show`

```text

 Usage: plural agent show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is shown with its problems, never swapped for the
 hosted one.
 NAME@REF shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent test`

```text

 Usage: plural agent test [OPTIONS] [name]

 Send an external Agent a signed ping, and report how it answered.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent validate`

```text

 Usage: plural agent validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural app`

```text

 Usage: plural app [OPTIONS] COMMAND [ARGS]...

 Add, list, and remove the Apps in an Environment.

 An App is one system the Agent works with: an MCP server, an HTTP API, recorded traces, Plural's
 files server, or a Python App class.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ add     Add a system to an Environment as an App, creating the Environment if it is new.         │
│ list    List the Apps an Environment's environment.yaml declares.                                │
│ remove  Remove an App from an Environment (a local edit until you push).                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural app add`

```text

 Usage: plural app add [OPTIONS] {name}

 Add a system to an Environment as an App, creating the Environment if it is new.

 Give one source per call: --mcp, --openapi, --traces, or --files-server.
 Run it again to add another system. With --traces it also drafts Tasks and
 a Benchmark, and running it again with newer traces adds their calls,
 tools, systems, and Tasks; existing Tasks are kept.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Environment to add to; created if it does not exist. [required]            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --mcp                 <str>               An MCP server: its Streamable HTTP URL, or the command │
│                                           that starts it over stdio, such as 'npx -y             │
│                                           @modelcontextprotocol/server-memory'.                  │
│ --openapi             <str>               An HTTP API's OpenAPI document: a file or a URL.       │
│ --traces              <str>               Recorded conversations: JSON or JSONL of {"messages":  │
│                                           [...]}, or Plural Traces. Each system they call        │
│                                           becomes a replay App, and Tasks and a Benchmark are    │
│                                           drafted from them.                                     │
│ --files-server                            Plural's ready-made files server: the Environment's    │
│                                           and the Task's files, read-only, with search and       │
│                                           read-only SQL over CSV, JSON, JSONL, and SQLite.       │
│ --copy                                    With --files-server: copy the server into the          │
│                                           Environment as APP_server.py, to change what it        │
│                                           offers.                                                │
│ --app                 <str>               The App's name. It prefixes an action only when        │
│                                           another App offers the same name. Default: from the    │
│                                           source, such as linear for https://mcp.linear.app/mcp. │
│                                           With --traces, the App for tool calls whose names      │
│                                           carry no app__ prefix (default: tools).                │
│ --header              <str>               An HTTP header, KEY=VALUE. Repeatable. Use ${NAME}.    │
│ --server-env          <str>               An environment variable for the MCP server, KEY=VALUE. │
│                                           Repeatable. Use ${NAME}.                               │
│ --tool                <str>               Only offer this MCP tool. Repeatable. Default: every   │
│                                           tool.                                                  │
│ --base-url            <str>               Where to send API requests. Default: the document's    │
│                                           servers.                                               │
│ --operation           <str>               Only offer this API operationId. Repeatable.           │
│ --secret              <str>               A setup secret the project supplies, for reset and     │
│                                           snapshot hooks. Repeatable. Without it, ${NAME} in a   │
│                                           header or variable is a credential the Agent supplies. │
│ --credential          <str>               A credential the running Agent supplies, such as its   │
│                                           own API token. Repeatable. ${NAME} in a header or      │
│                                           variable is added for you.                             │
│ --judge-model         <str>               Model for the drafted judge Verifier.                  │
│                                           [default: openai/gpt-5.6-luna]                         │
│ --max-tasks           <int range> [x>=1]  With --traces: draft at most this many Tasks,          │
│                                           preferring traces that call different tools.           │
│                                           [default: 50]                                          │
│ --runtime             <str>               Where a new Environment runs: local (a trusted         │
│                                           subprocess), docker, or daytona. Default: local.       │
│ --json                                    Print machine-readable JSON.                           │
│ --help                                    Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural app list`

```text

 Usage: plural app list [OPTIONS] {environment}

 List the Apps an Environment's environment.yaml declares.

 This reads the file only. `plural env validate ENV` loads each App and lists
 the actions the Agent is offered.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    environment      <str>  The Environment. [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural app remove`

```text

 Usage: plural app remove [OPTIONS] {environment} {app}

 Remove an App from an Environment (a local edit until you push).

 Only the App's entry under apps: in environment.yaml is removed. Files it
 used, such as a server, an OpenAPI document, or recordings, stay in place.
 A Python App class is yours to remove by hand.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    environment      <str>  The Environment. [required]                                         │
│ *    app              <str>  The App to remove, by its name in environment.yaml. [required]      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth`

```text

 Usage: plural auth [OPTIONS] COMMAND [ARGS]...

 Sign in, sign out, and choose the hosted account or project commands use.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ login   Sign in with your browser (or store an API key).                                         │
│ logout  Revoke and remove the stored credential for this profile.                                │
│ status  Check the credential with the service and show the current scope.                        │
│ scope   Show or change where hosted commands go by default.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth login`

```text

 Usage: plural auth login [OPTIONS]

 Sign in with your browser (or store an API key).

 A browser login mints a 30-day API key for the account (personal or an
 organization) selected in the browser that approves it. Credentials are
 stored in your OS keyring or a private file in your user config
 directory, never in a project.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --no-browser                   Print the URL only.                                               │
│ --api-key-stdin                Store an API key read from standard input instead.                │
│ --from-env                     Store PLURAL_API_KEY from the environment. The value is not       │
│                                printed.                                                          │
│ --env-file             <path>  Read PLURAL_API_KEY from this file. Other variables in the file   │
│                                are ignored.                                                      │
│ --api-url              <str>   Hosted service URL.                                               │
│ --help                         Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth logout`

```text

 Usage: plural auth logout [OPTIONS]

 Revoke and remove the stored credential for this profile.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth scope`

```text

 Usage: plural auth scope [OPTIONS] [target]

 Show or change where hosted commands go by default.

 With no options, show the current scope. Scope selects a destination; it
 never changes what your credential may do. The new scope is checked with
 the service before it is saved, and a failed check leaves the previous
 scope in place.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --account                 Select account scope.                                                  │
│ --project  -p      <str>  Select an existing hosted project by name.                             │
│ --org              <str>  Switch to an organization account (slug or id), or `personal`.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth status`

```text

 Usage: plural auth status [OPTIONS]

 Check the credential with the service and show the current scope.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark`

```text

 Usage: plural benchmark [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Benchmarks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Benchmark from the standard template.                                     │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ release   Label the revision matching your files with a release version, pushing it first.       │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ delete    Delete a resource's local folder, refusing while other local resources use it.         │
│ add       Add Tasks to a Benchmark (a local edit until you push).                                │
│ remove    Remove Tasks from a Benchmark (a local edit until you push).                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark add`

```text

 Usage: plural benchmark add [OPTIONS] {tasks}...

 Add Tasks to a Benchmark (a local edit until you push).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    tasks      <str>  Tasks to add, by name or a pattern such as 'refund-*'. [required]         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --benchmark  -b      <str>  Benchmark to edit. Defaults to the one you are in.                   │
│ --push                      Push the Benchmark afterwards.                                       │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark delete`

```text

 Usage: plural benchmark delete [OPTIONS] {name}

 Delete a resource's local folder, refusing while other local resources use it.

 Without --hosted this is a local edit: the hosted project keeps the
 resource until you add --hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Benchmark to delete. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted            Also delete it from the hosted project. Jobs and Trials that pinned its      │
│                     revisions can still read them.                                               │
│ --yes     -y        Delete without asking.                                                       │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark init`

```text

 Usage: plural benchmark init [OPTIONS] {name}

 Create a new Benchmark from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Benchmark name. [required]                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark list`

```text

 Usage: plural benchmark list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark pull`

```text

 Usage: plural benchmark pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

 Name a retained revision as NAME@REF.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also replace dependencies you already have with the exact revisions it      │
│                      pins. Missing dependencies are always restored.                             │
│ --force              Replace local files that differ. The old copy is kept under                 │
│                      .plural/backups.                                                            │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark push`

```text

 Usage: plural benchmark push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps               Also push local dependencies that are not hosted yet.                  │
│ --force                   Add a revision even though the hosted resource moved since you last    │
│                           synced.                                                                │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark release`

```text

 Usage: plural benchmark release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource to release. [required]                                         │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark remove`

```text

 Usage: plural benchmark remove [OPTIONS] {tasks}...

 Remove Tasks from a Benchmark (a local edit until you push).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    tasks      <str>  Tasks to remove, by name or a pattern such as 'refund-*'. [required]      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --benchmark  -b      <str>  Benchmark to edit. Defaults to the one you are in.                   │
│ --push                      Push the Benchmark afterwards.                                       │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark show`

```text

 Usage: plural benchmark show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is shown with its problems, never swapped for the
 hosted one.
 NAME@REF shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark validate`

```text

 Usage: plural benchmark validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural credential`

```text

 Usage: plural credential [OPTIONS] COMMAND [ARGS]...

 Save your own values for the credentials Agents carry, such as your CRM token.

 Credentials are yours, not the project's. An App declares the credentials it needs; the Agent that
 runs supplies them, with the scopes it lists under credentials: in its agent.yaml. Save your value
 once with `plural credential set NAME`; every Agent you run that carries NAME uses it, and your
 coworkers save their own. For project setup values, use `plural secret`.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list    List the credentials you saved, never their values.                                      │
│ set     Save your value for a credential. Prompts without echoing.                               │
│ delete  Delete one of your saved credentials.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural credential delete`

```text

 Usage: plural credential delete [OPTIONS] {name}

 Delete one of your saved credentials.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The credential to delete. [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural credential list`

```text

 Usage: plural credential list [OPTIONS]

 List the credentials you saved, never their values.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural credential set`

```text

 Usage: plural credential set [OPTIONS] {name}

 Save your value for a credential. Prompts without echoing.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The credential's name, as the App declares it. [required]                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --from-env          Read the value from the environment variable of that name.                   │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env`

```text

 Usage: plural env [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Environments.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create an Environment whose App is a FastMCP server you write.                         │
│ serve     Serve an App's FastMCP server over HTTP, to try its tools in any MCP client.           │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ release   Label the revision matching your files with a release version, pushing it first.       │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ delete    Delete a resource's local folder, refusing while other local resources use it.         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env delete`

```text

 Usage: plural env delete [OPTIONS] {name}

 Delete a resource's local folder, refusing while other local resources use it.

 Without --hosted this is a local edit: the hosted project keeps the
 resource until you add --hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Environment to delete. [required]                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted            Also delete it from the hosted project. Jobs and Trials that pinned its      │
│                     revisions can still read them.                                               │
│ --yes     -y        Delete without asking.                                                       │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env init`

```text

 Usage: plural env init [OPTIONS] {name}

 Create an Environment whose App is a FastMCP server you write.

 A starter Task and Verifier come with it, so the example runs and
 scores at once: `plural run --task NAME-first --model MODEL`.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Environment name. [required]                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --python          Start from a Python App class instead of a FastMCP server.                     │
│ --bare            Create only the Environment, without the starter Task and Verifier.            │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env list`

```text

 Usage: plural env list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env pull`

```text

 Usage: plural env pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

 Name a retained revision as NAME@REF.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also replace dependencies you already have with the exact revisions it      │
│                      pins. Missing dependencies are always restored.                             │
│ --force              Replace local files that differ. The old copy is kept under                 │
│                      .plural/backups.                                                            │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env push`

```text

 Usage: plural env push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps               Also push local dependencies that are not hosted yet.                  │
│ --force                   Add a revision even though the hosted resource moved since you last    │
│                           synced.                                                                │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env release`

```text

 Usage: plural env release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource to release. [required]                                         │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env serve`

```text

 Usage: plural env serve [OPTIONS] {name}

 Serve an App's FastMCP server over HTTP, to try its tools in any MCP client.

 Trials don't use this: they talk to the server over stdin and stdout.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Environment whose FastMCP server to serve. [required]                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --app         <str>  App to serve, when the Environment has several servers.                     │
│ --port        <int>  Port on 127.0.0.1. [default: 3825]                                          │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env show`

```text

 Usage: plural env show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is shown with its problems, never swapped for the
 hosted one.
 NAME@REF shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env validate`

```text

 Usage: plural env validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural external`

```text

 Usage: plural external [OPTIONS] COMMAND [ARGS]...

 Register an agent that runs as its own service, and trace its runs to Plural.

 In the agent's repository, `plural external init` writes plural-agent.yaml. Edit it, then `plural
 external register` adds the Agent to Plural, and `plural external check` confirms the keys and the
 service work. In the agent's code, `plural.external.Tracer` and the adapters for OpenTelemetry,
 LangChain, and the OpenAI Agents SDK trace each run.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Write a plural-agent.yaml with every field explained.                                  │
│ register  Add the Agent to Plural, or a new revision when its url or version changed.            │
│ check     Check the config, the API key, the Agent's registration, and a signed ping.            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural external check`

```text

 Usage: plural external check [OPTIONS]

 Check the config, the API key, the Agent's registration, and a signed ping.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --config  -c      <path>  The config file. Defaults to ./plural-agent.yaml.                      │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural external init`

```text

 Usage: plural external init [OPTIONS] {name}

 Write a plural-agent.yaml with every field explained.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Agent's name in Plural. [required]                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version        <str>   Your release label. [default: 0.1.0]                                    │
│ --model          <str>   The label runs report as their model.                                   │
│ --url            <str>   Where Plural Jobs send episodes, over https.                            │
│ --path           <path>  Where to write the file. [default: plural-agent.yaml]                   │
│ --force                  Replace an existing file.                                               │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural external register`

```text

 Usage: plural external register [OPTIONS]

 Add the Agent to Plural, or a new revision when its url or version changed.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --config  -c      <path>  The config file. Defaults to ./plural-agent.yaml.                      │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness`

```text

 Usage: plural harness [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Harnesses.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Harness from the standard template.                                       │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ release   Label the revision matching your files with a release version, pushing it first.       │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ delete    Delete a resource's local folder, refusing while other local resources use it.         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness delete`

```text

 Usage: plural harness delete [OPTIONS] {name}

 Delete a resource's local folder, refusing while other local resources use it.

 Without --hosted this is a local edit: the hosted project keeps the
 resource until you add --hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Harness to delete. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted            Also delete it from the hosted project. Jobs and Trials that pinned its      │
│                     revisions can still read them.                                               │
│ --yes     -y        Delete without asking.                                                       │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness init`

```text

 Usage: plural harness init [OPTIONS] {name}

 Create a new Harness from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Harness name. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness list`

```text

 Usage: plural harness list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness pull`

```text

 Usage: plural harness pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

 Name a retained revision as NAME@REF.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also replace dependencies you already have with the exact revisions it      │
│                      pins. Missing dependencies are always restored.                             │
│ --force              Replace local files that differ. The old copy is kept under                 │
│                      .plural/backups.                                                            │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness push`

```text

 Usage: plural harness push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps               Also push local dependencies that are not hosted yet.                  │
│ --force                   Add a revision even though the hosted resource moved since you last    │
│                           synced.                                                                │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness release`

```text

 Usage: plural harness release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource to release. [required]                                         │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness show`

```text

 Usage: plural harness show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is shown with its problems, never swapped for the
 hosted one.
 NAME@REF shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness validate`

```text

 Usage: plural harness validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job`

```text

 Usage: plural job [OPTIONS] COMMAND [ARGS]...

 List, inspect, and rerun Jobs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list    List Jobs, newest first, labeled local or hosted.                                        │
│ show    Show a Job and its Trials (local first, then hosted).                                    │
│ record  Record a finished local Job in the hosted project, with every Trial execution.           │
│ rerun   Run a Job again with the exact inputs it used. Creates a new, linked Job.                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job list`

```text

 Usage: plural job list [OPTIONS]

 List Jobs, newest first, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only local Jobs.                                                               │
│ --hosted          Only hosted Jobs.                                                              │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job record`

```text

 Usage: plural job record [OPTIONS] {job_id}

 Record a finished local Job in the hosted project, with every Trial execution.

 The hosted Job pins the pushed revisions the local Job ran, so push those
 first, or pass --push-pinned when your files changed since the run.
 Recording again, or recording a Job that ran with --record, uploads only
 what the hosted Job does not hold yet.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Finished local Job to record in the hosted project. [required]           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --push-pinned          First push the exact inputs the Job ran that are not hosted yet, from the │
│                        copies the run kept, as unversioned revisions that do not become current. │
│                        Your files are not touched.                                               │
│ --json                 Print machine-readable JSON.                                              │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job rerun`

```text

 Usage: plural job rerun [OPTIONS] {job_id}

 Run a Job again with the exact inputs it used. Creates a new, linked Job.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job to run again with its original pinned inputs. [required]             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --record          Record the rerun in the hosted project as it runs.                             │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job show`

```text

 Usage: plural job show [OPTIONS] {job_id}

 Show a Job and its Trials (local first, then hosted).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job id. [required]                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --follow          Stream progress until it finishes.                                             │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural model`

```text

 Usage: plural model [OPTIONS] COMMAND [ARGS]...

 List the models you may run.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list  List models your account may use.                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural model list`

```text

 Usage: plural model list [OPTIONS]

 List models your account may use.

 Signed in to an organization, this lists the models the organization offers:
 its own endpoints and private models, and any it explicitly allows. `--all`
 lists the whole catalog and marks models the organization does not permit.
 Outside an organization, or signed out, it lists the whole catalog.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --provider        <str>  Only this provider.                                                     │
│ --all                    Every catalog model, not only the ones your organization offers.        │
│ --json                   Print machine-readable JSON.                                            │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project`

```text

 Usage: plural project [OPTIONS] COMMAND [ARGS]...

 Create, register, and inspect projects.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init  Create a project in ./<name>, or register the project you are in.                          │
│ show  Show a project, local copy first, then hosted.                                             │
│ push  Push every local resource to the bound hosted project.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project init`

```text

 Usage: plural project init [OPTIONS] {name}

 Create a project in ./<name>, or register the project you are in.

 Without --push this works offline. With --push, an existing local project
 is registered as it is; no local file is overwritten. A hosted project
 that already has this name is left alone unless --connect is set.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Project name: lowercase letters, digits, and hyphens. [required]           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --push                  Create a hosted project with this name and select it as your scope.      │
│ --connect               Bind to the hosted project that already has this name. Requires --push.  │
│ --name           <str>  Hosted project name, when it should differ from the local project.       │
│                         Requires --push.                                                         │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project push`

```text

 Usage: plural project push [OPTIONS]

 Push every local resource to the bound hosted project.

 Each changed resource becomes a new numbered revision, dependencies first.
 Existing revisions are never overwritten or deleted, and versions never
 block a push. Label a revision with `plural <kind> release NAME VERSION`.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --yes      -y             Push without asking.                                                   │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --force                   Add revisions even if the hosted copy changed since this checkout last │
│                           synced.                                                                │
│ --connect                 Bind to the hosted project that already has this name.                 │
│ --name             <str>  Hosted project name, when this checkout is not bound yet.              │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project show`

```text

 Usage: plural project show [OPTIONS] {name}

 Show a project, local copy first, then hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Project name. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only look at local files.                                                      │
│ --hosted          Only look at the hosted project.                                               │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review`

```text

 Usage: plural review [OPTIONS] COMMAND [ARGS]...

 List and submit human reviews.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list    List Trials waiting for a human score.                                                   │
│ submit  Record a human score. Submissions are append-only.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review list`

```text

 Usage: plural review list [OPTIONS]

 List Trials waiting for a human score.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted          Hosted review assignments.                                                     │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review submit`

```text

 Usage: plural review submit [OPTIONS] {target}

 Record a human score. Submissions are append-only.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    target      <str>  Trial id, or a review assignment id with --hosted. [required]            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --score           <str>  `criterion=value`, or a bare value for a one-criterion rubric.       │
│                             [required]                                                           │
│    --verifier        <str>  Human Verifier (local).                                              │
│    --feedback        <str>  Notes for the record.                                                │
│    --hosted                 Submit a hosted assignment.                                          │
│    --help                   Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural reward`

```text

 Usage: plural reward [OPTIONS] COMMAND [ARGS]...

 Show a Trial's rewards and export training data. Add rewards with `plural verifier apply`.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ show    List a Trial's reward ledger.                                                            │
│ export  Write one training record per Trial: model turns with TITO tokens and their rewards.     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural reward export`

```text

 Usage: plural reward export [OPTIONS]

 Write one training record per Trial: model turns with TITO tokens and their rewards.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --trial                                                  <str>   A local Trial id. Repeatable.   │
│ --job                                                    <str>   Every Trial of this local Job.  │
│ --verifier                                               <str>   Use only this verifier, as name │
│                                                                  or name@version. Repeatable.    │
│ --aggregate                                              <str>   Combine rewards on one target:  │
│                                                                  sum, mean, last.                │
│                                                                  [default: sum]                  │
│ --include-off-recording    --no-include-off-recording            Keep rewards on steps a         │
│                                                                  replayed App answered off its   │
│                                                                  recording.                      │
│                                                                  [default:                       │
│                                                                  no-include-off-recording]       │
│ --out                                                    <path>  Where to write JSONL.           │
│                                                                  [default: training.jsonl]       │
│ --help                                                           Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural reward show`

```text

 Usage: plural reward show [OPTIONS] {trial_id}

 List a Trial's reward ledger.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  A local Trial id. [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural run`

```text

 Usage: plural run [OPTIONS]

 Run one Task or Benchmark with a model or a saved Agent. Every run is a new Job.

 The Job runs from this machine. Its Trials execute in the Runtime each
 Environment declares: local, docker, or a cloud sandbox such as daytona.
 It stays local unless you pass --record.

 NAME@REF runs that exact pushed revision even after your files have
 moved on. It is restored under .plural/versions without touching them.

 For an Agent with its own endpoint, the run first asks the server what
 model it is running and shows it with a fingerprint. Accept it once and
 later runs of the same model go ahead; if the fingerprint changes, you
 are asked again.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --task              -t      <str>               Task to run: NAME[@REF], where REF is a revision │
│                                                 number (@3), a release version (@1.0.0), or a    │
│                                                 content hash.                                    │
│ --benchmark         -b      <str>               Benchmark to run: NAME[@REF], where REF is a     │
│                                                 revision number (@3), a release version          │
│                                                 (@1.0.0), or a content hash.                     │
│ --model             -m      <str>               Catalog model id.                                │
│ --harness                   <str>               Harness for --model. Default: native (Plural's   │
│                                                 built-in tool loop).                             │
│ --agent             -a      <str>               Saved Agent to run: NAME[@REF], where REF is a   │
│                                                 revision number (@3), a release version          │
│                                                 (@1.0.0), or a content hash.                     │
│ --record                                        Run here, and record the Job in the hosted       │
│                                                 project as it runs. Inputs the hosted project    │
│                                                 lacks are pushed first.                          │
│ --evaluation-track          <str>               Run a Benchmark under one of its evaluation      │
│                                                 tracks, by id, so the results can be published.  │
│                                                 Implies --record, and uses the track's attempts. │
│ --attempts                  <int range> [x>=1]  Advanced: Trials per Task (default 1).           │
│ --concurrency       -n      <str>               Trials to run at once: a number, or auto to size │
│                                                 it from this machine, the runtime, and where the │
│                                                 model runs.                                      │
│                                                 [default: auto]                                  │
│ --plural-version            <str>               Plural to install in Docker and remote           │
│                                                 sandboxes: a version, or latest. Default: this   │
│                                                 CLI's own code.                                  │
│ --dry-run                                       Advanced: validate and show the plan without     │
│                                                 running.                                         │
│ --listen                    <str>               For an external Agent: HOST:PORT where this run  │
│                                                 serves its episodes.                             │
│                                                 [default: 127.0.0.1:0]                           │
│ --public-url                <str>               For an external Agent: the https base URL it     │
│                                                 reaches this run at, when that differs from      │
│                                                 --listen, such as behind a proxy.                │
│ --tls-cert                  <path>              For an external Agent: the certificate to serve  │
│                                                 https with.                                      │
│ --tls-key                   <path>              For an external Agent: the key of --tls-cert.    │
│ --yes               -y                          Use an endpoint Agent's model without asking,    │
│                                                 even one you have not accepted.                  │
│ --json                                          Print machine-readable JSON.                     │
│ --help                                          Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime`

```text

 Usage: plural runtime [OPTIONS] COMMAND [ARGS]...

 Choose where Environments run.

 Start with `plural runtime providers` to see what each provider needs, then `plural runtime
 create` to add a Runtime to your project and `plural runtime use <runtime> <environment>` to run
 an Environment on it.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ providers  List the providers a Runtime can use and what each needs.                             │
│ provider   Explain one provider: its credentials and every setting.                              │
│ list       List the current project's Runtimes.                                                  │
│ show       Show one project Runtime and the settings Environments copy from it.                  │
│ create     Add a Runtime to the current project.                                                 │
│ edit       Change a project Runtime's settings or credentials.                                   │
│ delete     Delete a project Runtime and its saved credentials.                                   │
│ use        Run Environments on a project Runtime by copying its settings into environment.yaml.  │
│ template   Runtime templates: an account's approved provider configurations. Admins only.        │
│ policy     Which Runtimes an organization's members may create and run on.                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime create`

```text

 Usage: plural runtime create [OPTIONS] [name]

 Add a Runtime to the current project.

 Run it with no options for a guided setup that explains each setting. In a
 script, pass --template or --provider with --set and --credentials-from-env.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Runtime name, such as 'GPU sandbox'.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --template                                     <str>  Start from this Runtime template (slug or  │
│                                                       id).                                       │
│ --provider                                     <str>  Configure a provider directly instead of a │
│                                                       template.                                  │
│ --set                                          <str>  A setting as key=value, such as --set      │
│                                                       cpus=2. Repeat for more; repeat a list     │
│                                                       setting to add items, such as --set        │
│                                                       python_packages=duckdb --set               │
│                                                       python_packages=polars. See `plural        │
│                                                       runtime provider <id>` for every key.      │
│ --credential                                   <str>  A credential name, such as                 │
│                                                       DAYTONA_API_KEY, to be prompted for        │
│                                                       without echoing; KEY=VALUE also works but  │
│                                                       leaves the value in your shell history.    │
│ --credentials-from-env                                Read every credential the provider needs   │
│                                                       from environment variables of the same     │
│                                                       name.                                      │
│ --plural-credentials      --own-credentials           Start sandboxes on Plural's account,       │
│                                                       billed to your credits as compute usage,   │
│                                                       or with your own provider credentials.     │
│                                                       Defaults to Plural's account where the     │
│                                                       provider offers it, unless you pass        │
│                                                       credentials.                               │
│ --description                                  <str>  What this Runtime is for.                  │
│ --advanced                                            Also prompt for advanced settings.         │
│ --no-input                                            Never prompt; fail when something required │
│                                                       is missing.                                │
│ --json                                                Print machine-readable JSON.               │
│ --help                                                Show this message and exit.                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime delete`

```text

 Usage: plural runtime delete [OPTIONS] {runtime}

 Delete a project Runtime and its saved credentials.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    runtime      <str>  Runtime slug or id. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --yes   -y        Do not ask for confirmation.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime edit`

```text

 Usage: plural runtime edit [OPTIONS] {runtime}

 Change a project Runtime's settings or credentials.

 Environments keep the settings they copied. Run `plural runtime use` again
 to update them.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    runtime      <str>  Runtime slug or id. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --set                                          <str>  A setting as key=value, such as --set      │
│                                                       cpus=2. Repeat for more; repeat a list     │
│                                                       setting to add items, such as --set        │
│                                                       python_packages=duckdb --set               │
│                                                       python_packages=polars. See `plural        │
│                                                       runtime provider <id>` for every key.      │
│ --unset                                        <str>  Return a setting to its default.           │
│ --credential                                   <str>  A credential name, such as                 │
│                                                       DAYTONA_API_KEY, to be prompted for        │
│                                                       without echoing; KEY=VALUE also works but  │
│                                                       leaves the value in your shell history.    │
│ --credentials-from-env                                Read every credential the provider needs   │
│                                                       from environment variables of the same     │
│                                                       name.                                      │
│ --plural-credentials      --own-credentials           Start sandboxes on Plural's account,       │
│                                                       billed to your credits as compute usage,   │
│                                                       or with your own provider credentials.     │
│                                                       Defaults to Plural's account where the     │
│                                                       provider offers it, unless you pass        │
│                                                       credentials.                               │
│ --name                                         <str>  A new name.                                │
│ --description                                  <str>  A new description.                         │
│ --advanced                                            Also prompt for advanced settings.         │
│ --no-input                                            Never prompt; fail when something required │
│                                                       is missing.                                │
│ --json                                                Print machine-readable JSON.               │
│ --help                                                Show this message and exit.                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime list`

```text

 Usage: plural runtime list [OPTIONS]

 List the current project's Runtimes.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime policy`

```text

 Usage: plural runtime policy [OPTIONS] COMMAND [ARGS]...

 Which Runtimes an organization's members may create and run on.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ set  Set the organization's Runtime policy. Owners and admins only.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime policy set`

```text

 Usage: plural runtime policy set [OPTIONS]

 Set the organization's Runtime policy. Owners and admins only.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --mode         <str>  open lets members configure any allowed provider; templates-only limits │
│                          them to the account's templates.                                        │
│                          [required]                                                              │
│    --allow        <str>  A provider members may use. Repeat for more. Omit for all.              │
│    --json                Print machine-readable JSON.                                            │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime provider`

```text

 Usage: plural runtime provider [OPTIONS] {provider}

 Explain one provider: its credentials and every setting.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    provider      <str>  Provider id, such as daytona or docker. [required]                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime providers`

```text

 Usage: plural runtime providers [OPTIONS]

 List the providers a Runtime can use and what each needs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime show`

```text

 Usage: plural runtime show [OPTIONS] {runtime}

 Show one project Runtime and the settings Environments copy from it.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    runtime      <str>  Runtime slug or id. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template`

```text

 Usage: plural runtime template [OPTIONS] COMMAND [ARGS]...

 Runtime templates: an account's approved provider configurations. Admins only.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list     List the account's Runtime templates.                                                   │
│ show     Show one Runtime template.                                                              │
│ create   Add a Runtime template to the account. Organization owners and admins only.             │
│ edit     Change a Runtime template. Project Runtimes made from it follow the change.             │
│ disable  Stop a template from being used, without deleting it.                                   │
│ enable   Allow a disabled template to be used again.                                             │
│ delete   Delete a template and its credentials. Refused while project Runtimes use it.           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template create`

```text

 Usage: plural runtime template create [OPTIONS] [name]

 Add a Runtime template to the account. Organization owners and admins only.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Template name, such as 'Daytona US'.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --provider                                          <str>  Provider id.                          │
│ --set                                               <str>  A setting as key=value, such as --set │
│                                                            cpus=2. Repeat for more; repeat a     │
│                                                            list setting to add items, such as    │
│                                                            --set python_packages=duckdb --set    │
│                                                            python_packages=polars. See `plural   │
│                                                            runtime provider <id>` for every key. │
│ --credential                                        <str>  A credential name, such as            │
│                                                            DAYTONA_API_KEY, to be prompted for   │
│                                                            without echoing; KEY=VALUE also works │
│                                                            but leaves the value in your shell    │
│                                                            history.                              │
│ --credentials-from-env                                     Read every credential the provider    │
│                                                            needs from environment variables of   │
│                                                            the same name.                        │
│ --lock                                              <str>  A setting project Runtimes may not    │
│                                                            change. Repeat for more.              │
│ --share-credentials       --no-share-credentials           Let members' local runs use this      │
│                                                            template's credentials.               │
│                                                            [default: no-share-credentials]       │
│ --plural-credentials      --own-credentials                Start sandboxes on Plural's account,  │
│                                                            billed to your credits as compute     │
│                                                            usage, or with your own provider      │
│                                                            credentials. Defaults to Plural's     │
│                                                            account where the provider offers it, │
│                                                            unless you pass credentials.          │
│ --description                                       <str>  What this template is for.            │
│ --advanced                                                 Also prompt for advanced settings.    │
│ --no-input                                                 Never prompt; fail when something     │
│                                                            required is missing.                  │
│ --json                                                     Print machine-readable JSON.          │
│ --help                                                     Show this message and exit.           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template delete`

```text

 Usage: plural runtime template delete [OPTIONS] {template}

 Delete a template and its credentials. Refused while project Runtimes use it.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    template      <str>  Template slug or id. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --yes   -y        Do not ask for confirmation.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template disable`

```text

 Usage: plural runtime template disable [OPTIONS] {template}

 Stop a template from being used, without deleting it.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    template      <str>  Template slug or id. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template edit`

```text

 Usage: plural runtime template edit [OPTIONS] {template}

 Change a Runtime template. Project Runtimes made from it follow the change.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    template      <str>  Template slug or id. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --set                                               <str>  A setting as key=value, such as --set │
│                                                            cpus=2. Repeat for more; repeat a     │
│                                                            list setting to add items, such as    │
│                                                            --set python_packages=duckdb --set    │
│                                                            python_packages=polars. See `plural   │
│                                                            runtime provider <id>` for every key. │
│ --unset                                             <str>  Return a setting to its default.      │
│ --credential                                        <str>  A credential name, such as            │
│                                                            DAYTONA_API_KEY, to be prompted for   │
│                                                            without echoing; KEY=VALUE also works │
│                                                            but leaves the value in your shell    │
│                                                            history.                              │
│ --credentials-from-env                                     Read every credential the provider    │
│                                                            needs from environment variables of   │
│                                                            the same name.                        │
│ --lock                                              <str>  Replace the locked settings.          │
│ --share-credentials       --no-share-credentials           Whether members' local runs may use   │
│                                                            this template's credentials.          │
│ --plural-credentials      --own-credentials                Start sandboxes on Plural's account,  │
│                                                            billed to your credits as compute     │
│                                                            usage, or with your own provider      │
│                                                            credentials. Defaults to Plural's     │
│                                                            account where the provider offers it, │
│                                                            unless you pass credentials.          │
│ --name                                              <str>  A new name.                           │
│ --description                                       <str>  A new description.                    │
│ --json                                                     Print machine-readable JSON.          │
│ --help                                                     Show this message and exit.           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template enable`

```text

 Usage: plural runtime template enable [OPTIONS] {template}

 Allow a disabled template to be used again.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    template      <str>  Template slug or id. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template list`

```text

 Usage: plural runtime template list [OPTIONS]

 List the account's Runtime templates.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime template show`

```text

 Usage: plural runtime template show [OPTIONS] {template}

 Show one Runtime template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    template      <str>  Template slug or id. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural runtime use`

```text

 Usage: plural runtime use [OPTIONS] {runtime} [environments]...

 Run Environments on a project Runtime by copying its settings into environment.yaml.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    runtime           <str>  Runtime slug or id. [required]                                     │
│      environments      <str>  Environments to run on it. Defaults to the only Environment, if    │
│                               there is one.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --all           Every Environment in the project.                                                │
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural secret`

```text

 Usage: plural secret [OPTIONS] COMMAND [ARGS]...

 Set the project's setup values, stored encrypted in the hosted project.

 Apps' reset and snapshot commands and Verifiers use secrets; the model never sees them. `plural
 env validate` lists the secrets each App needs. Set one with `plural secret set NAME`; `plural
 run` then supplies it to the App. For your own values, such as your API token, use `plural
 credential`.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list    List the secrets set in the project, never their values.                                 │
│ set     Set a secret's value in the hosted project. Prompts without echoing.                     │
│ delete  Remove a secret's value from the hosted project.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural secret delete`

```text

 Usage: plural secret delete [OPTIONS] {name}

 Remove a secret's value from the hosted project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The secret to remove. [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural secret list`

```text

 Usage: plural secret list [OPTIONS]

 List the secrets set in the project, never their values.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural secret set`

```text

 Usage: plural secret set [OPTIONS] {name}

 Set a secret's value in the hosted project. Prompts without echoing.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The secret's name, as the App declares it. [required]                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --from-env          Read the value from the environment variable of that name.                   │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session`

```text

 Usage: plural session [OPTIONS] COMMAND [ARGS]...

 Export and redeploy portable agent sessions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ export  Export a session bundle from a hosted Trial or local files.                              │
│ import  Redeploy a bundle as a separate instance directory.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session export`

```text

 Usage: plural session export [OPTIONS]

 Export a session bundle from a hosted Trial or local files.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --trial                   <str>   Hosted Trial id.                                               │
│ --agent-file              <path>  Agent YAML or JSON file.                                       │
│ --environment-file        <path>  Environment YAML or JSON file.                                 │
│ --state                   <path>  State JSON file.                                               │
│ --data                    <str>   Data reference to record.                                      │
│ --data-dir                <path>  Directory bundled into data/.                                  │
│ --name                    <str>   Snapshot name.                                                 │
│ --out                     <path>  Bundle directory. [default: sessions]                          │
│ --help                            Show this message and exit.                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session import`

```text

 Usage: plural session import [OPTIONS] {bundle}

 Redeploy a bundle as a separate instance directory.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    bundle      <path>  Session bundle directory. [required]                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --out         <path>  Parent directory for the new instance.                                     │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task`

```text

 Usage: plural task [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Tasks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a Task with instructions, one Environment, and its Verifiers.                   │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ release   Label the revision matching your files with a release version, pushing it first.       │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ delete    Delete a resource's local folder, refusing while other local resources use it.         │
│ cases     Write one Task per case, each a copy of TASK with the case's fields.                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task cases`

```text

 Usage: plural task cases [OPTIONS] {task} {path}

 Write one Task per case, each a copy of TASK with the case's fields.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <str>   Task to copy for each case. [required]                                    │
│ *    path      <path>  Cases, as a .jsonl file or a .json or .yaml list. Each names its Task and │
│                        may set instructions, initial_state, expected, info, metadata, and goals. │
│                        [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --replace                   Write over Tasks that already exist, such as on a rerun.             │
│ --benchmark  -b      <str>  Also add the Tasks to this Benchmark.                                │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task delete`

```text

 Usage: plural task delete [OPTIONS] {name}

 Delete a resource's local folder, refusing while other local resources use it.

 Without --hosted this is a local edit: the hosted project keeps the
 resource until you add --hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Task to delete. [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted            Also delete it from the hosted project. Jobs and Trials that pinned its      │
│                     revisions can still read them.                                               │
│ --yes     -y        Delete without asking.                                                       │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task init`

```text

 Usage: plural task init [OPTIONS] {name}

 Create a Task with instructions, one Environment, and its Verifiers.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Task name. [required]                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <str>  Environment the Task runs in.                                      │
│ --verifier             <str>  Verifier that scores it. Repeat for more.                          │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task list`

```text

 Usage: plural task list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task pull`

```text

 Usage: plural task pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

 Name a retained revision as NAME@REF.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also replace dependencies you already have with the exact revisions it      │
│                      pins. Missing dependencies are always restored.                             │
│ --force              Replace local files that differ. The old copy is kept under                 │
│                      .plural/backups.                                                            │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task push`

```text

 Usage: plural task push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps               Also push local dependencies that are not hosted yet.                  │
│ --force                   Add a revision even though the hosted resource moved since you last    │
│                           synced.                                                                │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task release`

```text

 Usage: plural task release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource to release. [required]                                         │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task show`

```text

 Usage: plural task show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is shown with its problems, never swapped for the
 hosted one.
 NAME@REF shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task validate`

```text

 Usage: plural task validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial`

```text

 Usage: plural trial [OPTIONS] COMMAND [ARGS]...

 Inspect and rerun Trials.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ show   Show a Trial's result, Verifier evidence, and artifacts (local first, then hosted).       │
│ rerun  Run one Trial again with its pinned inputs, as a new one-Trial Job.                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial rerun`

```text

 Usage: plural trial rerun [OPTIONS] {trial_id}

 Run one Trial again with its pinned inputs, as a new one-Trial Job.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  Trial to run again. [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --record          Record the rerun in the hosted project as it runs.                             │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial show`

```text

 Usage: plural trial show [OPTIONS] {trial_id}

 Show a Trial's result, Verifier evidence, and artifacts (local first, then hosted).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  Trial id. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --follow          Stream progress until it finishes.                                             │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier`

```text

 Usage: plural verifier [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Verifiers.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Verifier from the standard template.                                      │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ release   Label the revision matching your files with a release version, pushing it first.       │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ delete    Delete a resource's local folder, refusing while other local resources use it.         │
│ try       Run a Verifier on stored Trials and print what it gives, without saving anything.      │
│ apply     Run a Verifier on stored Trials and add its rewards to their ledgers.                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier apply`

```text

 Usage: plural verifier apply [OPTIONS] {name}

 Run a Verifier on stored Trials and add its rewards to their ledgers.

 Records are kept under the Verifier's name and version. A Trial that already
 has rewards from this version is left as it is: bump the Verifier's version
 when its logic changes, so an export can choose which labels to use. Pushed
 Jobs get the new records in the hosted project too.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Verifier, by name. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --trial        <str>  A local Trial id. Repeatable.                                              │
│ --job          <str>  Every Trial of this local Job.                                             │
│ --json                Print machine-readable JSON.                                               │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier delete`

```text

 Usage: plural verifier delete [OPTIONS] {name}

 Delete a resource's local folder, refusing while other local resources use it.

 Without --hosted this is a local edit: the hosted project keeps the
 resource until you add --hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Verifier to delete. [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted            Also delete it from the hosted project. Jobs and Trials that pinned its      │
│                     revisions can still read them.                                               │
│ --yes     -y        Delete without asking.                                                       │
│ --json              Print machine-readable JSON.                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier init`

```text

 Usage: plural verifier init [OPTIONS] {name}

 Create a new Verifier from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Verifier name. [required]                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier list`

```text

 Usage: plural verifier list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier pull`

```text

 Usage: plural verifier pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

 Name a retained revision as NAME@REF.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also replace dependencies you already have with the exact revisions it      │
│                      pins. Missing dependencies are always restored.                             │
│ --force              Replace local files that differ. The old copy is kept under                 │
│                      .plural/backups.                                                            │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier push`

```text

 Usage: plural verifier push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps               Also push local dependencies that are not hosted yet.                  │
│ --force                   Add a revision even though the hosted resource moved since you last    │
│                           synced.                                                                │
│ --bump             <str>  patch: when a manifest's version already names a revision, label the   │
│                           new revision with the next free patch version instead of none.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier release`

```text

 Usage: plural verifier release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource to release. [required]                                         │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier show`

```text

 Usage: plural verifier show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is shown with its problems, never swapped for the
 hosted one.
 NAME@REF shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  The resource: NAME[@REF], where REF is a revision number (@3), a release      │
│                    version (@1.0.0), or a content hash. Defaults to the resource directory you   │
│                    are in.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier try`

```text

 Usage: plural verifier try [OPTIONS] {name}

 Run a Verifier on stored Trials and print what it gives, without saving anything.

 Its reward runs again on each recorded step, its hindsight on the finished
 trajectory, and a Python check on the stored episode. Edit the Verifier and
 run this again to see the difference; the Agent is not run.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  The Verifier, by name. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --trial        <str>  A local Trial id. Repeatable.                                              │
│ --job          <str>  Every Trial of this local Job.                                             │
│ --json                Print machine-readable JSON.                                               │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier validate`

```text

 Usage: plural verifier validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
<!-- /generated-cli-reference -->
