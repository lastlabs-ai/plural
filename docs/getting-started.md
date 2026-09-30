---
route: /docs/getting-started
title: Getting started
order: 20
description: Go from a new account to your first scored run. Sign up, install Plural, sign in with your API key, build a small Task, run it on your computer, then push it and run it on Plural's servers.
audience: all
nav: true
nav_group: Start
---
# Getting started

By the end of this page you will have a Plural account, an API key, a project on your
computer with one working Task in it, and a scored result you can inspect and rerun.
If you want, you will also have run the same thing on Plural's servers.

Plan on about half an hour. The setup steps take a few minutes each; most of the time
goes into describing your first Task.

If words like Environment, Task, and Verifier are new, read
[Core concepts](getting-started/concepts.md) first. It takes about five minutes. If
you would rather watch a finished project run before building your own, try the
[support queue tutorial](tutorials/support-queue.md). It runs offline, with no account
or key.

## Create an account

Everything starts at [pluralintel.com](https://pluralintel.com).

1. **Sign up.** Use your email and a password, or continue with Google or GitHub.
2. **Confirm your email.** If you signed up with email, Plural sends you a link. Open
   it to verify your address.
3. **Take the short tour.** It shows you the project switcher at the top of the
   sidebar and the model Catalog in the top navigation.
4. **Create your first API key.** The tour ends by creating an account API key named
   `test_key`. An API key is a long secret string that lets the `plural` command on
   your computer act on your account and call models.

> **Good to know:** The key is shown only once. Copy it somewhere safe, such as a
> password manager, before you leave the page. If you lose it, create a new one; you
> can make and manage more keys under **Keys** in your account.

You will use this key in [Sign in](#sign-in), right after you install Plural.

## Install

Plural comes as a Python package. It gives you two things: the `plural` command, which
you type into a terminal, and a Python SDK for people who prefer to write code. You
need Python 3.10 or newer.

Install it with pip:

```bash
python -m pip install "plural>=0.17.2"
```

Or, if you use uv, install the `plural` command as a tool:

```bash
uv tool install "plural>=0.17.2"
```

To check that it worked, run `plural --help`. It prints the list of commands.

**Docker.** By default, Plural runs each AI's world inside Docker. Think of Docker as a
sealed box: the AI can do whatever the Task allows inside the box, but it cannot touch
the rest of your computer. Install [Docker](https://www.docker.com/) and make sure it
is running before you run anything that uses the default runtime.

For power users: to use the Python SDK from a uv-managed project, also run
`uv add "plural>=0.17.2"` inside that project. Optional extras include
`plural[daytona]` for the Daytona Runtime and `plural[keyring]` to store credentials in
your OS keyring.

## Sign in

Signing in connects the `plural` command on your computer to your Plural account. Do it
now with the `test_key` you created in the tour, and every step after this one just
works.

There are two ways to sign in, and they are good for different things:

- **An API key** is a secret you create in the web app. It works for everything,
  including model calls. Use it for any run that calls a model.
- **A browser login** opens pluralintel.com, you approve it, and the command acts as
  you. It works for hosted commands such as pushing and hosted runs, but the model
  gateway does not accept it.

If you only set up one, make it the API key.

:::tabs
:::tab API key
Paste the key when prompted (it is not shown as you type), or pipe it in. Plural
stores it for you:

```bash
plural auth login --api-key-stdin
```

Or keep it in an environment variable instead:

```bash
export PLURAL_API_KEY=plural_...
```

If the key is already in `PLURAL_API_KEY`, `plural auth login --from-env` stores it
without printing it.
:::tab Browser login
This opens your browser to approve the login:

```bash
plural auth login
plural auth status
```

`plural auth status` checks the credential with the service and shows where your
commands are pointed.
:::

Either way, the credential is stored in your user config folder (or your OS keyring),
never in your project files. Keep keys out of source files, Agent instructions, and
Task files.

For power users:

- A browser login acts as you and reaches every account and project your roles allow.
  It is not accepted for model calls; use an API key for those.
- A **project key** is an API key limited to one project. It can only reach that
  project and cannot create new ones.
- Signed in to an organization, `plural models list` shows the models your
  organization offers; add `--all` for the whole catalog. When a run starts, the
  service refuses any model your organization does not permit.

## Create a project

A project is a folder that holds everything you build: your worlds, assignments,
graders, and contestants. Creating one works offline and needs no account:

```bash
plural project init my-eval
cd my-eval
```

That creates a few starter files:

- `project.yaml`: the project's name and description. This file is what marks the
  folder as a Plural project.
- `plural.lock`: a record of the hosted versions your resources depend on. Plural
  updates it when you push or pull. Commit it to version control, and do not edit it by
  hand.
- `pyproject.toml` and `README.md`.
- A `.gitignore` that leaves out `.plural/`, the folder where Plural keeps local state
  such as the records of your runs.

Each thing you add later gets its own folder, named after it. Here is the full layout,
for reference:

```text
project.yaml            name and description
plural.lock             hosted revisions; commit it
pyproject.toml          dependencies = ["plural>=0.17.2"]
.plural/                local state: hosted binding, jobs/, backups/ (gitignored)
environments/<name>/    environment.yaml, environment.py, README.md, resources/
tasks/<name>/           task.yaml, instruction.md, resources/
verifiers/<name>/       verifier.yaml, verify.py
harnesses/<name>/       harness.yaml, harness.py
agents/<name>/          agent.yaml
benchmarks/<name>/      benchmark.yaml, README.md
```

Commands look upward from wherever you are to find `project.yaml`, so you can run them
from any folder inside the project.

## Add resources

A **resource** is any one of the building blocks from
[Core concepts](getting-started/concepts.md). For a first run you need three:

- an **Environment**, the world the AI works in (here, a support desk),
- a **Verifier**, the grader that scores the finished work, and
- a **Task**, one assignment in that world (here, a refund request).

Each `init` command writes a template for you to fill in:

```bash
plural env init support-desk
plural verifier init resolved
plural task init refund --environment support-desk --verifier resolved
```

The templates mark every place you need to fill in with `PLURAL-TODO`:

- `environments/support-desk/environment.py`: what the world holds (its State), what
  the AI is shown (its Observation), and the moves it can make (its `@action`
  methods). Keep the answers on State, never on the Observation, so the AI cannot
  read them.
- `environments/support-desk/README.md`: what the world is and how to use it.
- `verifiers/resolved/verify.py`: compare how things ended with what the Task asked
  for, and return a score.
- `tasks/refund/instruction.md`: what the AI must accomplish, in plain language. Set
  the Task's starting State under `initial_state` in `task.yaml`.

When you think you are done, ask Plural to check your work:

```bash
plural task validate refund
```

```text
task/refund is valid: version 0.1.0, sha256:4c7c807a30fe...
```

`validate` checks the resource and everything it depends on, and lists any template
text you left unfinished. Nothing runs until it passes, so it is a good habit to
validate after every edit.

A few details worth knowing:

- Inside a resource's folder you can leave off the name: `plural task validate` in
  `tasks/refund/` validates `refund`.
- Every resource kind has the same verbs: `init`, `validate`, `show`, `list`, `push`,
  and `pull`. They work for `env`, `task`, `verifier`, `harness`, `agent`, and
  `benchmark`.
- A new Environment uses the `docker` runtime (`runtime.provider: docker` in
  `environment.yaml`), so Docker must be running when you run it. The `local` runtime
  avoids Docker, but it runs the Environment as a trusted subprocess directly on your
  machine and is not a sandbox. Use it only for code you trust.

## Run locally

Now run your Task against a model from the catalog. Start with a **dry run**, which
shows what would happen without running anything or calling a model:

```bash
plural run --task refund --model openai/gpt-5.6-luna --dry-run
```

```text
Would run task/refund with gpt-5.6-luna (openai/gpt-5.6-luna, harness native) locally: 1 trial(s), 1 at a time (auto: every Trial at once).
input                     version  content hash
environment/support-desk  0.1.0    sha256:d7b203421527
verifier/resolved         0.1.0    sha256:9f13af9d2534
task/refund               0.1.0    sha256:4c7c807a30fe
```

The table lists every input with its version and a content hash, a fingerprint of the
exact files. A dry run needs no key. Using `--model` without `--harness` plays with
`native`, Plural's built-in loop. To see which model ids you can use, run
`plural models list` or browse the [model catalog](https://pluralintel.com/models).

A real run calls the model, which can cost money. Every model call goes through the
Plural gateway, which bills it at the exact provider price, using the API key you
signed in with:

```bash
plural run --task refund --model openai/gpt-5.6-luna
```

If you skipped [Sign in](#sign-in), the run stops before calling the model and tells
you how to add a key.

Every run is a new **Job**, and each attempt inside it is a **Trial**. The run prints
the Job id and one line per Trial with its score. Use those ids to look at the results:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
plural job rerun <job-id>
```

- `job show` lists each Trial with its Task, status, and score.
- `trial show` prints the score, each Verifier's evidence, and where the Trial's
  artifacts and logs are.
- `job rerun` runs the Job again with the exact inputs it used the first time, even if
  you have edited your files since, and creates a new Job linked to the original.

Plural records each local Job under `.plural/jobs/<job-id>/`, with every input pinned
by version and content hash.

### Compare Agents on a Benchmark

One Task is a start. To compare contestants across many Tasks, group the Tasks into a
**Benchmark** (the exam) and save an **Agent** (a model plus its instructions):

```bash
plural benchmark init support
plural benchmark add refund --benchmark support
plural agent init careful --model openai/gpt-5.6-luna
```

Fill in the `PLURAL-TODO` places in `benchmarks/support/benchmark.yaml` (what the
Benchmark measures and what a score means) and `benchmarks/support/README.md`, and
write the Agent's `instructions` in `agents/careful/agent.yaml`. Then validate and run:

```bash
plural benchmark validate support
plural run --benchmark support --agent careful
```

## Push and run hosted

So far everything ran on your computer. To have Plural run it for you on its servers,
you **push** your project to a private hosted project. Pushing never makes anything
public.

First, register the project. Run this from inside it:

```bash
plural project init my-eval --push
```

The name must match `name` in `project.yaml`. This creates a private hosted project
(or connects to an existing one), remembers the link in `.plural/project.json`, and
points your commands at that project. It does not change any of your local files.

Then push what the run uses and start a hosted run:

```bash
plural benchmark push support --with-deps
plural agent push careful --with-deps
plural run --benchmark support --agent careful --hosted --follow
```

- `--with-deps` also pushes everything the Benchmark or Agent depends on that is not
  hosted yet.
- `--hosted` runs on Plural's servers instead of your computer.
- `--follow` streams progress until the Job finishes.

You can also watch hosted runs in the web app under **Jobs**, in the project you pushed
to.

### How pushing works

This is the detail to read when a push is refused or you want to know exactly what
gets uploaded.

- Each push saves an unchangeable snapshot called a **revision**. A pushed revision is
  available in its private project immediately.
- A push validates first and uploads nothing unless the whole push can succeed.
- Pushing unchanged content reuses the existing revision. Changed content becomes the
  resource's next numbered revision, such as `#4`; you never bump a version. To give a
  revision a name people can cite, run `plural <kind> release NAME 1.0.0`.
- Push refuses files that look like credentials, such as `.env` or private keys, and
  manifest paths that point outside the resource folder. To leave a file out of a push,
  list it in a `.pluralignore` file in the resource folder.
- `--hosted` runs pushed revisions. If the hosted project is missing anything the run
  uses, `plural run --hosted` pushes it first, as a new numbered revision of any
  resource whose files changed. If someone else changed a resource
  in the hosted project since you last synced, the push stops so nothing is written on
  top of their work.
- Listing a project on the Hub or publishing a Benchmark is a separate, explicit action
  in the Plural web app.

## Scope

Scope is where hosted commands go by default: your account as a whole, or one hosted
project. Registering a project with `--push` already sets it, so most people never need
to change it.

```bash
plural auth scope
plural auth scope --project my-eval
plural auth scope --account
plural auth scope --org personal
```

- `plural auth scope` on its own shows the current scope.
- `--project` selects an existing hosted project.
- `--account` selects account scope.
- `--org` switches between organization accounts; `personal` selects your own.

Changing scope changes where commands go, never what your credential is allowed to do.
Plural checks the new scope with the service before saving it; if the check fails, the
previous scope stays in place. A push is refused when your scope points at a different
project than the one this folder is registered with.

## Use the SDK

If you prefer Python to the command line, the SDK loads the same resources by name:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support")
agent = workspace.get("agent", "careful")
result = Job(benchmark, agents=[agent]).run()
```

That runs on your computer, like `plural run`, with one difference: the Job is not
recorded. It does not appear in `plural job list`, and `plural job rerun` cannot repeat
it.

A Job that calls a model sends every call through the Plural gateway with your API key.
It finds the key in `PLURAL_API_KEY`, in `api_key=`, or through a `Client`.
`Client()` reads `PLURAL_API_KEY` or an API key stored with
`plural auth login --api-key-stdin`. A browser login is not accepted:

```python
from plural import Client, Job

job = Job(benchmark, agents=[agent], client=Client())
```

The Job still runs on your computer. The [Python SDK guide](sdk/evaluation.md) covers
the rest of the SDK.

## Where to go next

- Walk through a complete, finished project in the
  [support queue tutorial](tutorials/support-queue.md).
- Read the [CLI guide](cli/evaluation.md) for every command.
