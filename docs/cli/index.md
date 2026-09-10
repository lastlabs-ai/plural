# Command-line interface

Start with [installation and authentication](../getting-started/setup.md), then
follow the [complete CLI walkthrough](../tutorials/cli-walkthrough.md). This page
explains configuration and command conventions.

The `plural` executable is installed with the base package:

```bash
pip install plural
plural --help
```

The CLI is an alpha, local-first package and execution client. It can scaffold,
validate, build, inspect, and run packages; persist jobs; and inspect runtime
availability. Environment publication and client-orchestrated Job result upload
require a compatible hosted API. Runs make no external writes unless `--sync`
is passed; completed results can be replayed with `plural job upload`.

New foundation commands: `plural env action`, `plural env resource`,
`plural env capabilities`, `plural env harness stamp|unstamp|capabilities`,
`plural runtime doctor --env`, `plural agent template`, and
`plural agent instance`. See the [command reference](../reference/cli-commands.md).

## Authentication and device flow

`plural auth login` starts `POST /api/v1/auth/device/start`, prints the
verification URL and user code, optionally opens a browser, and polls the device
endpoint until approved or expired. Use `--no-browser` on remote hosts.

```bash
plural auth login --no-browser
plural auth status
plural auth whoami
plural auth logout
```

These commands require a compatible hosted authentication backend. Passwords
never pass through the CLI. Logout retains local credentials if remote
revocation fails, allowing the user to retry safely.

For non-interactive CI, use a scoped API key:

```bash
export PLURAL_API_KEY='plural-...'
export PLURAL_PROJECT='project-slug-or-id'
plural auth whoami
plural run job.yaml --dry-run --format json
```

Do not put keys in `config.toml`, manifests, command arguments, logs, or source
control.

## Profiles, organization, and project

Global options are accepted before the command:

```bash
plural --profile ci --api-url https://api.example.test \
  --org acme --project evals auth status
```

Resolution is deterministic:

1. command-line flags (`--profile`, `--api-url`, `--org`, `--project`);
2. `PLURAL_PROFILE`, `PLURAL_API_URL`, `PLURAL_ORG`, `PLURAL_PROJECT`;
3. the selected profile in `config.toml`;
4. built-in defaults.

`PLURAL_API_KEY` takes precedence over a stored API key. Auth status/whoami use a stored device access token when present. Hosted
publication/sync prefer an API key, otherwise refresh a stored refresh token
when available and use the resulting access token. `plural org use NAME` and `plural project use NAME` update the active
profile; `show` only prints resolved context. `list` is not implemented yet.

Configuration lives under `PLURAL_CONFIG_HOME`, then
`$XDG_CONFIG_HOME/plural`, then `~/.config/plural`. Non-secret profile data is
stored in `config.toml`. Credentials use the optional OS keyring when available
and otherwise a mode-`0600` `credentials.json` in that directory.

Supported environment variables are:

- `PLURAL_CONFIG_HOME`, `XDG_CONFIG_HOME`, and `PLURAL_PROFILE`;
- `PLURAL_API_URL`, `PLURAL_ORG`, `PLURAL_PROJECT`, and `PLURAL_API_KEY`;
- declared harness secret/environment names;
- `DAYTONA_API_KEY`, optionally `DAYTONA_API_URL` and `DAYTONA_TARGET`.

## Output and exit status

Most commands emit deterministic JSON. `plural run` additionally accepts
`--format json|yaml|text`; progress lines go to stderr and the final document to
stdout. JSON is the stable choice for scripts. There is no global format flag
and no promise that human help text is a stable parsing interface.

- `0`: command completed (including a dry run or `auth status` with no credentials);
- `1`: execution completed but at least one trial did not succeed;
- `2`: usage, validation, configuration, unsupported backend, or other handled error;
- `130`: interrupted with Ctrl-C.

Provider and harness failures are also represented by stable `ErrorCode` values
inside trial results and receipts; the process-level status intentionally stays
small.

## Command coverage

The generated [command reference](../reference/cli-commands.md) contains every
command, argument, option, and Typer-provided completion flag from the actual
application. CI fails if that checked-in reference drifts.
