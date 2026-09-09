# Install and authenticate

You need Python 3.10 or newer. Docker is optional until you run isolated package
jobs. You can complete the offline quickstart without any account or API key.
The terminal examples below use macOS/Linux shell syntax; in PowerShell, set
variables with `$env:PLURAL_API_KEY = "..."`.

## 1. Install in a project folder

```bash
mkdir plural-demo
cd plural-demo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install plural
plural --help
python -c "import plural; print(plural.__version__)"
```

On Windows, create the environment with `py -m venv .venv`, then activate
with `.venv\Scripts\Activate.ps1`. If you use `uv`,
`uv add plural` installs the dependency into an existing project; use
`uv run plural --help` to invoke its CLI.

Optional extras are `plural[keyring]` for OS credential storage,
`plural[daytona]` for the remote sandbox provider, `plural[otel]` for
OpenTelemetry, and `plural[all]` for all three.

## 2. Choose your credentials

There are two separate connections:

- **Plural Intel access** lets you fetch and update hosted project objects and
  use the Plural gateway. Use a Plural API key or the CLI's device login.
- **Model access** pays for and authenticates inference. The Python client can
  use a Plural gateway key or explicitly supplied upstream provider keys.
  External harnesses receive only the secrets granted to their AgentSpec.

A Docker runtime needs a running Docker daemon. Daytona additionally needs its
own `DAYTONA_API_KEY`; that key does not authenticate model calls.

### Recommended shared SDK/CLI setup: a Plural API key

Obtain a key and project identifier from your Plural Intel account or project
administrator. Use placeholders below only as a reminder to insert your values:

```bash
export PLURAL_API_KEY='REPLACE_WITH_YOUR_KEY'
export PLURAL_PROJECT='REPLACE_WITH_YOUR_PROJECT_ID'
plural auth whoami
```

A project-scoped key already identifies its project. An account-scoped key
needs `PLURAL_PROJECT`, SDK `project=`, or CLI `--project`. The SDK sends this
as `X-Project-Id`; use the identifier your deployment accepts.

Test hosted access separately from inference:

```python
from plural import Client

with Client() as client:
    print(client.environments.list())  # [] is valid for an empty project
```

This is a hosted read, not a model completion. `client.is_authenticated()`
probes configured model providers; it is not a substitute for checking project
access. Do not print the key itself.

### Interactive CLI login

```bash
plural auth login
plural auth status
plural auth whoami
plural project use YOUR_PROJECT_ID
plural project show
```

Follow the displayed verification URL and code in your browser. On a remote
machine use `plural auth login --no-browser`. The deployment must support the
device flow. With no credential, `auth status` reports unauthenticated locally;
with credentials it contacts the server. `whoami` returns the hosted identity. `plural auth logout` revokes stored credentials; it does
not unset an API key exported in your shell.

**CLI login does not configure `Client()` automatically.** The Python client
reads `PLURAL_API_KEY` or explicit `api_key=`, not CLI profiles or device tokens.
Likewise, a CLI login alone does not grant a model key to an external harness.
Use the API-key setup when following both SDK and CLI examples.

### Direct provider access (BYOK)

For model calls without the Plural gateway:

```bash
export OPENAI_API_KEY='REPLACE_WITH_YOUR_PROVIDER_KEY'
```

```python
import os
from plural import Client, Message

with Client(providers={"openai": os.environ["OPENAI_API_KEY"]}) as client:
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content="Say hello in one sentence.")],
    )
    print(response.text)
```

Explicit `providers={...}` makes the intended connection unambiguous.
When no gateway key or provider mapping is supplied, `Client()` can discover
supported provider environment keys, including `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and `GOOGLE_API_KEY`. It also recognizes the legacy gateway
variable `ENROUTE_API_KEY` after `PLURAL_API_KEY`. Prefer an explicit mapping
for predictable BYOK behavior across machines.

BYOK alone does not authorize hosted object calls. If you want direct inference
and Plural Intel object access in one application, use separate clients:

```python
import os
from plural import Client

with Client(providers={"openai": os.environ["OPENAI_API_KEY"]}) as inference:
    with Client(api_key=os.environ["PLURAL_API_KEY"], project=os.environ["PLURAL_PROJECT"]) as intel:
        print(intel.environments.list())
        # Use inference.chat(...) for direct provider calls.
```

Supplying a Plural `api_key` and provider keys to the same client enables gateway
routing: model calls go through the Plural gateway even when direct provider
adapters are also configured.

Model IDs in examples are illustrative; choose an ID supported by your account
and endpoint. Check the [model client guide](../sdk/client.md) for the bundled
catalog and routing controls.

## 3. Configure another deployment or profile

The SDK defaults to `https://api.pluralintel.com/v1`. Override it explicitly:

```python
with Client(base_url="https://api.example.test/v1", project="YOUR_PROJECT_ID") as client:
    print(client.environments.list())
```

For the CLI, global flags go **before** the subcommand:

```bash
plural --profile work --api-url https://api.example.test/v1 \
  --project YOUR_PROJECT_ID auth whoami
plural --profile work org use YOUR_ORGANIZATION
plural --profile work project use YOUR_PROJECT_ID
```

CLI flags override environment variables, then the selected profile, then
defaults. `org use` and `project use` save selections; a one-off `--api-url`
flag does not persist that URL. Set `PLURAL_API_URL` or the profile's `api_url`
in `config.toml` for subsequent commands. The SDK does not read `PLURAL_API_URL`;
pass `base_url=`. See [CLI configuration](../cli/index.md) for file locations.

For CI, inject `PLURAL_API_KEY` and `PLURAL_PROJECT` through your CI secret
settings. A fresh `PLURAL_PROFILE` avoids accidentally using a developer's
stored device credentials. Keys belong in the environment, not YAML manifests.

## 4. Grant model access to a package harness

The scaffolded harness uses an OpenAI-compatible chat-completions endpoint.
When using the Plural gateway, set both the key and the harness endpoint:

```bash
export PLURAL_GATEWAY_URL='https://api.pluralintel.com/v1'
```

Create the agent with `--secret PLURAL_API_KEY` as shown in the
[CLI walkthrough](../tutorials/cli-walkthrough.md). The flag grants the **name**;
the value is read from the process environment when the job executes.

For a direct OpenAI-compatible provider use `OPENAI_API_KEY` and, if needed,
`OPENAI_BASE_URL`, and grant `--secret OPENAI_API_KEY`. Use the model ID that
that endpoint accepts. Without a gateway/base override, the built-in harness
targets `https://api.openai.com/v1`. The built-in harness does not send the SDK's
`X-Project-Id` header: use a suitable project-scoped gateway key where required.

## Next

Run [your first evaluation](../quickstart.md), or go straight to the
[CLI walkthrough](../tutorials/cli-walkthrough.md). For authentication failures,
see [troubleshooting](../operations/troubleshooting.md).
