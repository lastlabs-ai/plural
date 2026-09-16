---
route: /docs/getting-started
title: Getting started
order: 20
description: Install Plural with pip or uv, create an account, choose a project or account API key, and authenticate the CLI and SDK.
audience: all
nav: true
nav_group: Start
---
# Getting started

Plural requires Python 3.10 or newer. Read [Core concepts](getting-started/concepts.md)
first if the object names are new.

## Install

With pip:

```bash
python -m pip install "plural>=0.13.3"
```

With uv:

```bash
uv add "plural>=0.13.3"
```

Optional extras include `plural[daytona]` when you want the Daytona Runtime.

## Create an account and an API key

1. Create an account at [pluralintel.com/signup](https://pluralintel.com/signup).
2. Create a project for the Environments, Tasks, and Jobs you are about to run.
3. Create an API key. Keys start with `plural_`. Copy the secret once; Plural
   does not show it again.

### Project key vs account key

A **project key** is bound to one project. Use it for a script or CI job that
should only touch that project. The Client does not need a separate project
id.

An **account key** can reach any project your account may access. Pass the
project every time: `Client(..., project="<project_id>")` or
`PLURAL_PROJECT`. Do not use an account key in a shared runner if a project
key will do.

Keep keys out of source, Agent instructions, and Task metadata.

## Authenticate the CLI

Device login stores a credential on your machine. After this, `plural run`
builds `Client()` for you:

```bash
plural auth login
```

Follow the browser prompt, then confirm:

```bash
plural auth status
```

To use a key you created in the app instead of device login:

```bash
export PLURAL_API_KEY=plural_...
# account keys also need the project
export PLURAL_PROJECT=<project_id>
```

`plural run --api-key` is a bring-your-own OpenAI-compatible key for the
model, not a Plural key. Prefer `plural auth login` or `PLURAL_API_KEY` for
the hosted catalog.

## Authenticate the SDK

`Client()` reads the login store or `PLURAL_API_KEY`:

```python
from plural import Client

client = Client()
```

An account key must name the project:

```python
client = Client(api_key="plural_...", project="<project_id>")
```

Pass that Client into a live Job. Dry-run does not need credentials:

```python
from plural import Job

job = Job(task, agents=[agent], client=client)
```
