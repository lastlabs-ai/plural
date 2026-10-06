---
route: /docs/project/runtimes
title: Runtimes
order: 35
description: "Choose where Environments run. Set up a sandbox provider once, reuse it across Environments, and let organization admins decide which providers members may use."
audience: all
nav: true
nav_group: Build
outcome: You can set up a Runtime, run an Environment on it, and, as an admin, control which Runtimes members use.
---
# Runtimes

A **Runtime** is where an [Environment](environments.md) runs: your own machine, a
Docker container, or a cloud sandbox. Every Environment has one. A project Runtime
lets you set one up once, with its provider, machine size, network access, and
credentials, and then reuse it across many Environments.

There are three layers:

| Layer | Who manages it | What it holds |
| --- | --- | --- |
| **Provider** | Plural | A place sandboxes can start, such as Daytona or Docker, and the settings and credentials it needs |
| **Runtime template** | Account owners and admins | An approved configuration of one provider, credentials included. Some settings can be locked |
| **Project Runtime** | Anyone who can edit the project | What Environments use. Starts from a template, or from a provider directly when the account allows it |

## Providers

| Provider | Runs on | Needs |
| --- | --- | --- |
| Daytona | Cloud sandbox | Nothing on Plural's account, or your own `DAYTONA_API_KEY` |
| Docker | The machine running the Job | Docker |
| Local | The machine running the Job | Nothing; no isolation |

E2B, Modal, Blaxel, and Cloudflare sandboxes are coming soon, as are deployments in
your own AWS, Google Cloud, or Azure account. They are listed so you can see what each
will need, but Runtimes can't be created on them yet.

See every setting a provider takes, with an explanation of each:

```bash
plural runtime providers
plural runtime provider daytona
```

## Create a Runtime

The quickest way is the guided setup. It asks for each setting, explains it, and
prompts for credentials without echoing them:

```bash
plural runtime create
```

In a script, name the provider or template and pass settings as `key=value`:

```bash
plural runtime create "Big box" --provider daytona --set cpus=4 --set memory_mb=8192 --no-input
```

### Plural's Daytona account or your own

A Daytona Runtime starts its sandboxes on Plural's Daytona account unless you give it
your own API key. You don't need a Daytona account, and sandboxes are billed to your
credits as compute usage, by the vCPU, memory, and disk they use for as long as they
run. The **Usage** page shows compute separately from model usage.

On Plural's account, `plural run` asks Plural to start each sandbox and relays commands
and files to it. The API key never reaches your machine. A sandbox that sits idle for
30 minutes is stopped, and one that runs for 6 hours is ended. Custom API URLs and
snapshots need your own key, because they belong to your Daytona organization.

To use your own Daytona account instead, pass credentials, or `--own-credentials`:

```bash
export DAYTONA_API_KEY=dtn_...
plural runtime create "Big box" --provider daytona --set cpus=4 --set memory_mb=8192 \
  --credentials-from-env --no-input
```

`plural runtime edit big-box --plural-credentials` switches back and deletes the saved
key.

`--credentials-from-env` reads every credential the provider needs from environment
variables of the same name. `--credential DAYTONA_API_KEY` prompts for one value
without echoing it.

To start from an organization's template instead, pass `--template`. The Runtime uses
the template's credentials, and you can change only the settings the template leaves
unlocked:

```bash
plural runtime create "Fast Daytona" --template daytona-us --set cpus=4
```

You can do the same from the **Runtimes** page of a project on pluralintel.com.
Credentials are encrypted when saved. Plural shows only their last few characters
afterwards, and never stores them in an Environment.

## Run an Environment on a Runtime

`plural runtime use` copies a Runtime's settings into an Environment's
`environment.yaml`:

```bash
plural runtime use big-box ticket-triage
plural env push ticket-triage
```

The `runtime` block then records which Runtime it came from:

```yaml
runtime:
  provider: daytona
  ref: big-box
  image: python:3.12-slim
  cpus: 4
  memory_mb: 8192
  network: public
  timeout_seconds: 300
```

The settings are copied, not linked. A saved Environment revision never changes, so
editing a Runtime later does not change Environments that already use it. Run
`plural runtime use` again, then push, to pick up the change. The Environment's
[Runtime variables](environments.md#runtime-variables-and-secrets) are kept.

On pluralintel.com, open an Environment, go to its **Runtime** tab, and choose a
project Runtime.

When a Runtime uses your own credentials and they are not already set in your shell, `plural run` fetches them from the project Runtime, if you are allowed
to use them. They are used only for that run and are never saved in the Job.

## Runtime templates and policy

Owners and admins of an account set up Runtime templates under **Runtimes** in the
organization's settings, or in personal settings for a personal account. A template
is a provider configuration that members can build project Runtimes from.

```bash
plural runtime template create "Daytona US" --provider daytona --set target=us \
  --lock target --lock network --credentials-from-env
```

- `--lock` stops project Runtimes from changing a setting, such as the region or
  network access.
- `--share-credentials` lets members' local runs use the template's credentials.
  Without it, members supply their own credentials for local runs.
- `plural runtime template disable <template>` stops new Jobs from using a template
  without deleting it. A template that project Runtimes still use cannot be deleted.

The organization's **Runtime policy** decides what members may do:

```bash
plural runtime policy
plural runtime policy set --mode templates-only --allow daytona
```

- `open`, the default, lets members configure any allowed provider directly.
- `templates-only` lets members create Runtimes only from the organization's
  templates. Hosted Jobs then run only on Environments whose Runtime comes from an
  active template.
- `--allow` limits which providers may be used at all. Leave it out to allow every
  provider.

Plural checks the policy when a Job is created, so an Environment that breaks it can
still be pushed but cannot run in the organization's projects.

## Commands

| Command | What it does |
| --- | --- |
| `plural runtime providers` | List providers and what each needs |
| `plural runtime provider <provider>` | Explain one provider's credentials and settings |
| `plural runtime list` | List the project's Runtimes |
| `plural runtime show <runtime>` | Show a Runtime's settings and where its credentials come from |
| `plural runtime create [name]` | Add a Runtime to the project |
| `plural runtime edit <runtime>` | Change settings or credentials |
| `plural runtime delete <runtime>` | Delete a Runtime and its saved credentials |
| `plural runtime use <runtime> <environment>...` | Copy a Runtime into Environments |
| `plural runtime template ...` | Manage the account's templates (admins) |
| `plural runtime policy [set]` | Show or set the organization's policy |

Every command takes `--json`. See the [CLI reference](../cli/evaluation.md) for all
options.
