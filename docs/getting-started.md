---
route: /docs/getting-started
title: Getting started
order: 20
description: Go from a new account to your first scored run. Sign up, install Plural, sign in, build a small Task, run it on your computer, then run it on Plural's servers.
audience: all
nav: true
nav_group: Start
---
# Getting started

By the end of this page you'll have built one small Task, run a model on it, and
looked at its score. It takes about half an hour, and most of that is writing the Task.

New to words like Environment, Task, and Verifier? Read
[Core concepts](getting-started/concepts.md) first; it takes five minutes. Want to see
a finished project run before building your own? The
[support queue tutorial](tutorials/support-queue.md) runs offline, with no account.

## Create an account

1. Sign up at [pluralintel.com](https://pluralintel.com) with email, Google, or GitHub.
2. Take the short tour. It ends by creating your first **API key**, a secret string
   that lets the `plural` command act on your account and call models.
3. Copy the key somewhere safe, such as a password manager. It is shown only once. If
   you lose it, make a new one under **Keys**.

## Install

You need Python 3.10 or newer.

:::tabs
:::tab pip
```bash
python -m pip install "plural[mcp]>=0.21.0"
```
:::tab uv
```bash
uv tool install "plural[mcp]>=0.21.0"
```
:::

Check it worked with `plural --help`.

Then install [Docker](https://www.docker.com/) and start it. Plural runs each
attempt inside a Docker container, a sealed box: the AI can do whatever the Task
allows inside it, and nothing outside it.

:::details Optional extras
- `plural[mcp]` (above) lets Plural run MCP servers, which new projects use.
- `plural[daytona]` adds the Daytona Runtime.
- `plural[keyring]` stores your credentials in your OS keyring.

To use the Python SDK from a uv project, run `uv add "plural[mcp]>=0.21.0"` inside it.
:::

## Sign in

Connect the `plural` command to your account with the key from the tour. It asks for
the key without showing it as you type:

```bash
plural auth login --api-key-stdin
```

That's it. The key is stored in your user config folder (or OS keyring), never in your
project, so it can't be committed by accident.

:::details Other ways to sign in
- **Browser login.** `plural auth login` opens pluralintel.com, you approve it there,
  and Plural stores a 30-day key for the account you picked. Check it with
  `plural auth status`.
- **Environment variable.** `export PLURAL_API_KEY=plural_...` works anywhere, which
  is handy in CI. `plural auth login --from-env` stores a key from that variable
  without printing it.
- **Project keys.** A project key is an API key limited to one project. It can reach
  only that project and can't create new ones.
- **Organizations.** A login acts for one account. To work in another organization,
  select it in the web app and run `plural auth login` again. Signed in to an
  organization, `plural models list` shows the models it allows.
:::

## Create a project

A project is a folder that holds everything you build. Creating one works offline:

```bash
plural project init my-eval
cd my-eval
```

You can run every `plural` command from anywhere inside this folder.

:::details What's in a project
```text
project.yaml            name and description; marks the folder as a project
plural.lock             hosted revisions; commit it, never edit it
pyproject.toml          the project's Python dependencies
.plural/                local state and run records (gitignored)
environments/<name>/    environment.yaml, server.py or environment.py, README.md
tasks/<name>/           task.yaml, instruction.md
verifiers/<name>/       verifier.yaml, verify.py
harnesses/<name>/       harness.yaml, harness.py
agents/<name>/          agent.yaml
benchmarks/<name>/      benchmark.yaml, README.md
```

Each resource gets its own folder, named after it, and resources refer to each other
by name.
:::

## Add resources

For a first run you need three things: an **Environment** (here, a support desk), a
**Verifier** to grade the work, and a **Task** (here, a refund request).

```bash
plural env init support-desk --python
plural verifier init resolved
plural task init refund --environment support-desk --verifier resolved
```

Each command writes a template. Search for `PLURAL-TODO` and fill in each one:

| File | What to write |
| --- | --- |
| `environments/support-desk/environment.py` | The App: its State (the hidden facts) and its `@action` methods (the moves). What an action returns is all the AI sees, so keep answers on State. |
| `verifiers/resolved/verify.py` | Compare how things ended with what the Task asked for, and return a score. |
| `tasks/refund/instruction.md` | What the AI must do, in plain language. |
| `tasks/refund/task.yaml` | The starting State, under `initial_state`. |

Then ask Plural to check your work:

```bash
plural task validate refund
```

```text
task/refund is valid: version 0.1.0, sha256:4c7c807a30fe...
```

`validate` checks the Task and everything it uses, and points at any `PLURAL-TODO`
you missed. Nothing runs until it passes, so validate after every edit.

:::details Handy details
- Inside a resource's folder you can leave off the name: `plural task validate` in
  `tasks/refund/` validates `refund`.
- Every kind of resource has the same verbs: `init`, `validate`, `show`, `list`,
  `push`, and `pull`.
- Without `--python`, `plural env init` writes an MCP server (`server.py`) instead of
  a Python App. Both work the same way in a run.
- The `local` Runtime skips Docker and runs the Environment directly on your machine.
  It is not a sandbox, so use it only for code you trust.
:::

## Run locally

Start with a **dry run**. It shows what would run without calling a model, and needs
no key:

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

Every input is pinned by version and a content hash, a fingerprint of the exact files.
That's how Plural can rerun this months from now and get the same experiment.

Now run it for real. This calls the model, billed at the provider's price:

```bash
plural run --task refund --model openai/gpt-5.6-luna
```

The run prints a **Job** id and one line per **Trial** with its score. Dig in:

```bash
plural job show <job-id>      # each Trial, its status and score
plural trial show <trial-id>  # the score, the Verifier's evidence, and the logs
plural job rerun <job-id>     # run again with exactly the same inputs
```

Browse model ids with `plural models list` or the
[model catalog](https://pluralintel.com/models).

### Compare Agents on a Benchmark

One Task is a start. To compare models across many Tasks, group them into a
**Benchmark** and save an **Agent**, a model plus its instructions:

```bash
plural benchmark init support
plural benchmark add refund --benchmark support
plural agent init careful --model openai/gpt-5.6-luna
```

Fill in the `PLURAL-TODO`s in `benchmarks/support/` and write the Agent's
`instructions` in `agents/careful/agent.yaml`. Then:

```bash
plural benchmark validate support
plural run --benchmark support --agent careful
```

Make a second Agent with a different model or instructions, run it too, and compare.

## Push and run hosted

So far everything ran on your computer. To have Plural run it for you, connect the
folder to a private hosted project, then add `--hosted`:

```bash
plural project init my-eval --push
plural run --benchmark support --agent careful --hosted --follow
```

`--hosted` pushes anything the run needs that isn't on Plural yet, then runs it on
Plural's servers. `--follow` streams progress until the Job finishes. You can also
watch it in the web app under **Jobs**.

Pushing never makes anything public. Sharing on the Hub is a separate step you take in
the web app.

:::details How pushing works
- Each push saves an unchangeable snapshot called a **revision**, such as `#4`.
  Pushing unchanged content reuses the existing revision, so you never bump a version
  by hand. To give a revision a name people can cite, run
  `plural <kind> release NAME 1.0.0`.
- You can push explicitly too: `plural benchmark push support --with-deps` pushes the
  Benchmark and everything it uses.
- A push validates first and uploads nothing unless all of it can succeed.
- A push refuses files that look like credentials, such as `.env` or private keys.
  List any other file to leave out in a `.pluralignore` in the resource's folder.
- If someone else changed a resource in the hosted project since you last synced, the
  push stops rather than write over their work.
:::

:::details Scope: where hosted commands go
`plural project init --push` points your commands at that hosted project, so most
people never touch scope. To change it:

```bash
plural auth scope                  # show the current scope
plural auth scope --project my-eval
plural auth scope --account        # your account as a whole
plural auth scope --org personal   # switch organization
```

Scope changes where commands go, never what your key may do. A push is refused when
the scope points at a different project than the folder is connected to.
:::

## Prefer Python?

Everything above works from the SDK too. It reads the same project folder:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "support")
agent = workspace.get("agent", "careful")
result = Job(benchmark, agents=[agent]).run()
```

:::details How an SDK run differs from plural run
It runs on your computer, like `plural run`, but the Job isn't recorded, so it doesn't
appear in `plural job list` and `plural job rerun` can't repeat it. It finds your key
in `PLURAL_API_KEY`, in `api_key=`, or through `Client()`, which also reads the key
`plural auth login` stored.
:::

See the [Python SDK guide](sdk/evaluation.md).

## Where to go next

- **[Start here](start/index.md)** picks up from what you already have: traces from an
  agent you run, a system like an MCP server, or nothing yet.
- **[Several Agents in one Task](project/multi-agent.md)** sets Agents to cooperate or
  compete.
- **[The support queue tutorial](tutorials/support-queue.md)** walks through a finished
  project.
- **[The CLI guide](cli/evaluation.md)** has every command.
