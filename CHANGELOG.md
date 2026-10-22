# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Every Trial has a seed, derived from the Task and the attempt, so every Agent on one attempt faces the same world and a rerun faces it again. Apps read it as `self.seed` and draw from `self.rng`; a State with a `seed` field gets it too. The Trial records it as `TrialResult.seed`. Until now a Job always reset Apps without a seed.
- `plural task cases TASK FILE` writes one Task per case, each a copy of TASK with the case's `instructions`, `initial_state`, `info`, `metadata`, or `goals`, and `--benchmark` adds them all. Cases are a `.jsonl` file or a `.json` or `.yaml` list.
- `plural benchmark add` and `remove` take several Tasks, by name or by a pattern such as `'refund-*'`.

### Removed

- `reset_options` on a Task, which Plural stored but never passed to `reset`. A Task or `task.yaml` that sets them is refused with a pointer to `initial_state` and `info`; an empty one is still accepted, stored revisions still load, and no Task's hash changes.

### Fixed

- A gateway failure the built-in Harness could not recover from is now recorded as the provider's, not as a harness failure scored zero. 0.22.1 lost the failure kind when the runner exited non-zero, which is how it always exits on an error.
- The README's examples run as shown, and the package's Documentation link points at pluralintel.com/docs.

## [0.22.1] - 2026-10-21

### Added

- `plural --version` prints the installed version.
- `plural trial show` shows how the episode stopped, its turns, and its cost.
- `plural run` prints each Agent's coverage, the share of Tasks with a score.
- `BenchmarkScoring.harness_timeout` decides how an attempt whose Harness was killed for running past its time is scored: `agent_failure` counts it against the Agent, and `infrastructure_error`, the default, leaves it out, so existing Benchmarks keep their digests and results. New Benchmarks from `plural benchmark init` set `agent_failure`. Such a Trial now has the stop reason `harness_timeout`.
- Every Harness is told the seconds it has before it is killed in `PLURAL_STOP_SECONDS`.

### Changed

- `plural run`, `plural job rerun`, and `plural trial rerun` exit with status 1 when a Trial failed or the Job was cancelled.
- `plural run` refuses `--model` or `--agent` given twice, instead of running only the last one.
- `success_threshold` defaults to the top of `score_range`, not to 1.0 whatever the range.
- `--dry-run --record` reports the unfinished places `--record` would refuse, instead of showing a plan the real run would refuse.
- A Benchmark whose README, `purpose`, or `scoring.description` still carries the template's `PLURAL-TODO` lines runs locally, as the docs say; pushing and `--record` still refuse it.

### Fixed

- A model gateway that is rate-limited or unavailable no longer scores the Agent zero. The built-in Harness retries it up to three times, without spending the episode's `max_seconds`, and an attempt it still cannot finish is an infrastructure error, as is a rejected API key. Only the built-in Harness can report a failure as the gateway's; a Harness of your own cannot excuse its own.
- A Verifier score outside the Benchmark's `score_range` is an infrastructure error instead of counting toward the mean.
- Job aggregates count a Trial that ran out of budget without a score as an Agent failure, as Benchmark results do.

- Verifiers see the Trial's model cost in `episode.usage.cost_usd`; it was always `None`.
- Plural's built-in Harness ends an episode itself at `max_seconds`, or 30 seconds before the Runtime's `timeout_seconds` when that comes first, so the Trial is verified with the stop reason `max_seconds` instead of being killed and counted as an infrastructure error. A model call still running at that deadline ends the episode the same way instead of failing the Trial.
- The Benchmarks guide no longer suggests `primary_metric` can name another Verifier score; it accepts only `score`.

## [0.22.0] - 2026-10-21

### Added

- Runs pause instead of failing when credits run out. A Trial on Plural's built-in Harness waits where it is, retrying every 30 seconds, and resumes within a minute of credits being added; the wait does not count against its time limits. It waits up to an hour, set by `PLURAL_CREDIT_PAUSE_SECONDS` (`0` fails at once). Starting a hosted sandbox waits the same way.
- `plural run`, `plural job rerun`, and `plural trial rerun` say when the account's credits are low, when they run out, and when they are added again, with the page to add them on.
- `TrialResult` has `stop_reason`, `step_reward_total`, and `turns`, read from the App host's episode outcome and reward ledger.
- `OpenAICompatible` and `AzureOpenAIProvider` accept `http_transport` and `async_http_transport`.
- `plural app add|list|remove ENV` manages an Environment's Apps. `add` takes what `plural env add` took, plus `--files-server` for Plural's files server (`--copy` copies it into the Environment to edit). `remove` takes one App's entry out of `environment.yaml`, leaves its files, and refuses a Python App, naming the file to edit.
- `plural <env|task|verifier|harness|agent|benchmark> delete NAME [--hosted] [-y]` deletes a resource's folder, and with `--hosted` the hosted resource, refusing while another local resource uses it.
- `plural --help` lists each kind of object, what it is, and the command that creates it.

### Changed

- `--track` is now `--record`, on `plural run`, `plural job rerun`, and `plural trial rerun`: it records a local run in the hosted project. "Track" now means only a Benchmark's evaluation tracks, and `--evaluation-track` implies `--record`. `--track` still works for one release and prints a note.
- Renamed, with the old name accepted for one release and a `DeprecationWarning`: Agent `harness_kwargs`, `auth_mode`, and `secret_names` to `harness_config`, `auth`, and `secrets`; Harness `environment` to `env_vars`; Runtime `network_allowlist`, `build_timeout_sec`, and `resources` to `allowed_hosts`, `build_timeout_seconds`, and `compute`; `Plural` to `Client`, `TimeoutError` to `PluralTimeoutError`, `Capability` to `SandboxCapability`, `Outcome` to `TraceOutcome`, and the engine's `Trial` to `TrialRunner`. Files and schemas are written with the new names, and content hashes are unchanged.
- An unknown model names the closest model ids and `plural model list`, instead of a validation link.
- A Task whose files cannot be shared with its Runtime is refused before any Trial runs.
- Inside an unregistered project whose name differs from the selected scope's project, hosted commands refuse and say how to register it.
- Renamed, with the old name kept for one release as a hidden alias that prints a note: `plural env add` and `plural env eject-files` to `plural app add` (`--files-server --copy`), `app add --env` to `--server-env`, `plural job push` to `plural job record`, `plural credential unset` to `plural credential delete`, `plural models` and `plural rewards` to `plural model` and `plural reward`, `pull --revision`/`-r` to `NAME@REF`, `plural auth scope .` to `--account`, `session export --agent`/`--environment` to `--agent-file`/`--environment-file`, and `session import --dest` to `--out`.
- Short flags mean one thing: `task init` drops `-v`, `runtime create` drops `-t` and `-p`, and `runtime template create` drops `-p`; `-p` is `--project` only.
- `plural agent init` needs `--model`, and asks for one in a terminal.
- `plural <kind> show` on a local resource that is not valid yet shows it with its problems instead of failing.
- Counts in CLI output read `1 Trial` and `2 Trials` instead of `trial(s)`, and messages capitalize object names.

### Removed

- `plural trial rescore` and `plural agent serve`, which did nothing, and `-h` as a short flag for `--harness`.

## [0.21.0] - 2026-10-13

### Added

- `trajectory.json` is written for every run in the same chat-message format. A Harness that calls no model gets its steps as tool calls and the observations they returned.
- `HarnessEnvironment.seated` says whether a Harness is playing one seat of a party, so one Harness can play alone or in a party.
- The Wordle example is rebuilt to use every core concept once: five games in a Benchmark, a Verifier with `check`, `reward`, and `hindsight`, and a model Agent on the built-in loop, so each run records the model's messages in `trajectory.json`.
- `plural secret list|set|delete` stores the values Apps' secrets need in the hosted project. `plural run` and local reruns fill any secret you have not exported from it, into the Job's environment only.
- `plural verifier apply` adds new records to the hosted ledgers of a pushed Job. `Studio.secrets` and `Studio.trials.rewards` / `add_rewards` expose both.
- Apps. An Environment is now a set of Apps, each one system the Agent works with: a Python class (`App`), an MCP server (`App.mcp`), an HTTP API with an OpenAPI document (`App.openapi`), or recorded traces (`App.replay`). `environment.yaml` lists them under `apps`.
- What the Agent sees. Each action is offered to the model under its own name, made safe for every provider (letters, digits, `_` and `-`, at most 64 characters). Only a name two Apps share, or one Plural reserves, is prefixed with the App's name, such as `crm__search`. With several Apps each description starts with its App. Tool schemas are normalized for every provider. `plural env validate` prints the tools exactly as the model sees them, and warns above 40.
- FastMCP servers. `mcp: {server: server.py:mcp}` starts a FastMCP server you wrote, fresh in the Runtime for each Trial, so it is `owned`. Install with `plural[mcp]`; Docker and remote Runtimes install the extra when an App needs it. `plural.mcp.reset` and `plural.mcp.snapshot` register a server's starting state and its snapshot for Verifiers, hidden from the Agent. `plural.mcp.environment_resources()`, `task_resources()`, and `scratch()` locate the Trial's files.
- Plural's files server, `plural.mcp.files:server`: lists, reads, and searches the Environment's and the Task's files, and runs read-only SQL over every CSV, JSON, JSONL, and SQLite file in them. `plural.mcp.files:writable` adds writes to a scratch folder. `plural env eject-files` copies it into an Environment to edit.
- `plural env serve NAME` serves an Environment's FastMCP server over HTTP at `http://127.0.0.1:3825/mcp` (3825 spells EVAL), to try it in any MCP client; `--port` picks another. `python -m plural.mcp.serve file.py:name --http` does the same for one server. Trials still talk to servers over stdio and open no port.
- `remote: true` on an MCP App marks a server started in the Runtime that works on an outside system, such as a data lake. It is then `live`, or `sandboxed` with a reset hook, instead of `owned`.
- `Environment.on_step` for effects that span Apps. It can call any App, and gives no reward.
- Control levels. Each App is `owned`, `sandboxed`, `live`, or `replayed`, derived from its kind and settings. A Benchmark refuses a `live` App that can change state and marks one with only read-only actions not reproducible; a train Job refuses every `live` App.
- Agent credentials. An App lists the credentials it needs under `credentials`, and references them as `${NAME}` in headers and server environment. The Agent that runs declares them: it lists each under `credentials:` in its `agent.yaml` with the scopes the token grants. Each person who runs it saves their own value, encrypted in their hosted account, with `plural credential set|list|unset` or under Credentials on their Profile, so coworkers running the same Agent each act as themselves. Only that person's own sign-in can read a value back; a project API key cannot, so CI exports values instead. `Job(credentials={agent: {name: value}})` passes them from Python. A Job checks before it starts that the Agent declares every credential and has a value for each; a `--model` run declares none. Values go only to the process that runs the Apps and to Verifier queries, never to the model or its Harness.
- Credential audit. Every Trial records, per credential, the App, the Agent and its revision, the declared scopes, where the value came from and, for a saved value, whose it was, and a short fingerprint of the value, never the value. `plural trial show` prints it, and a pushed Trial carries it.
- App secrets are for setup only: an App's `secrets` are supplied by the project, for `reset` and `snapshot` commands and Verifiers. Those commands never see an Agent's credentials.
- `episode.apps` gives Verifiers each App's initial and final snapshot and control level, and `query(...)` calls a read-only action while the Trial's Runtime is still running.
- The reward ledger, `rewards.jsonl`, records every reward a Trial earns with its source, verifier, version, and target: a step, a model call, or a span of text or tokens. A Verifier's `hindsight` function credits a finished Trial's steps and model calls after `check`, on every Trial of a Task that lists it. `plural rewards show` lists a ledger, and `plural rewards export` writes training data joining each model turn with its rewards and TITO record.
- `plural verifier try NAME --trial ID | --job ID` runs a Verifier on stored Trials and prints the score, step rewards, and hindsight credit it gives now, without saving anything or running the Agent. `plural verifier apply` records them in each Trial's ledger under the Verifier's version, and leaves a Trial that already has that version's records as it is.
- Each Trial records the State of every App after each step, as the `states.jsonl` artifact, so a Verifier's `reward` can run again on a stored Trial. Python Apps and `mcp` Apps with a `snapshot` command are recorded. `info["step"]` numbers each step. In a Runtime this State is held in the App host and collected over its control socket, never written to the workspace the Harness shares.
- Agents with their own model server: `endpoint` and `endpoint_key` send an Agent's model calls to any OpenAI-compatible endpoint instead of the gateway. A Job whose Agents all do so needs no Plural API key.
- `plural env add ENV --mcp URL_OR_COMMAND | --openapi SPEC | --traces FILE` adds a system you already have to an Environment as an App, creating the Environment the first time and appending to its `environment.yaml` and README after that, so one Environment can hold several systems. The App is named from the source, such as `linear` for `https://mcp.linear.app/mcp` or `memory` for `npx -y @modelcontextprotocol/server-memory`; `--app` picks another. Every `${NAME}` in a header or server variable is added as an Agent credential unless `--secret NAME` marks it a setup secret. `--traces` also drafts Tasks, a model-judge Verifier, and a Benchmark. It offers the agent's tools with their own descriptions and parameters, read from each trace's `tools`, and drafts at most `--max-tasks` (default 50) Tasks, first choosing traces that call tools no other chosen trace calls. Run it again with newer traces to update the Environment: new tools, systems, recorded calls, and Tasks are added, and traces already imported are skipped. Traces may be a JSON array, JSONL, or pretty-printed objects.
- Runtime packages. `runtime.packages.python` in `environment.yaml`, or `python_packages` in a Runtime's settings and its Software step in the web app, lists requirements such as `duckdb>=1.1` that are installed alongside Plural in the Runtime and baked into Docker images. A local Runtime installs nothing; a Job names the packages it lacks before it starts. `plural runtime create --set python_packages=X` may repeat.
- `plural env validate` lists each App's kind, control level, actions, credentials, and secrets, and `plural agent validate` which credentials an Agent has values for.
- Documentation: [Apps](docs/concepts/apps.md), [Build an MCP server](docs/guides/build-mcp-server.md), and [Connect an MCP server](docs/guides/connect-mcp-server.md). [Start from traces](docs/start/from-traces.md) opens with the trace format Plural reads and how drafting, comparing, and updating work. [Start from a system](docs/start/from-a-system.md) covers several systems in one Environment, and [Build an MCP server](docs/guides/build-mcp-server.md) covers data lakes and warehouses. Pages can fold detail into `:::details Title` blocks that readers expand.
- Documentation: [Start here](docs/start/index.md), with a path from traces, from a system, and from scratch, each ending at a Benchmark you can rerun.
- Step rewards from Verifiers. A `DeterministicVerifier` takes a `reward` function beside its `check`: `reward: verify.py:progress` in `verifier.yaml`, or `DeterministicVerifier(..., reward=progress)`. It is a function of a `Step`: the Task, the action, its observation or error, the acting App's state before and after, and read-only access to every App. It runs after each action, beside the Apps in the Runtime, and its rewards go to the reward ledger with source `step` and the Verifier's name and version. A Verifier needs at least one of `check`, `reward`, and `hindsight`, and a Task at least one Verifier with `check`. `Environment.reset(verifiers=[...])` runs `reward` functions in process. `check` now also takes a command, as `command` did, which still works.
- `check: total_reward` (`plural.total_reward` in Python) scores an attempt by the sum of that Verifier's own rewards, to make the reward the score. Otherwise rewards never change a score.
- The App host is kept from the Harness. On Docker and Daytona it runs as its own OS user, with its files, its secrets, and the Verifier code that rewards steps in a folder only it can read; Plural removes them from the shared workspace once it starts. It signs what it reports with a key made for each Trial, so a process posing as the host fails the Trial. `TrialResult.app_isolation` records `os_user`, or `none` on the local Runtime and on a Daytona image without `sudo` and `useradd`. See [Security](docs/operations/security.md#separate-information).
- `steps.jsonl`, the App host's record of every action it ran. Rewards, observations, and whether the episode ended come from it, not from what the Harness writes: a step the Harness reports that the host never ran earns nothing and is marked `unverified`, and a Harness that writes no episode still gets its steps. `plural verifier try|apply` replays from it.
- An App can name the scopes it needs a credential to grant, as `credentials: [{name: CRM_TOKEN, scopes: [write:opportunities]}]`. A Job refuses an Agent whose declared scopes for it lack one.
- Several Agents in one Task. `party` on an Environment (`Party(min=2, max=8)`, or `party:` in `environment.yaml`) says how many Agents share one episode; a party of N sits in seats `seat_1` to `seat_N`, and the Apps assign them roles. One Trial is one game: one Environment, one episode, a score for each seat, and each seat's own trace under `seats/<seat>/`. A Task's `seat_instructions` gives one seat instructions of its own. An App decides whose turn it is with `turn()`, which returns one seat, several for moves made at once, or `None` for any; it gives each seat its own view with `observe(seat)`, and reads the acting seat as `self.seat`. An action out of turn is refused before it runs. A `reward` function sees `step.seat` and may return a mapping of seat to value; a `check` returns each seat's score in `VerifierOutput.seats`, and `total_reward` scores each seat by its own rewards. A Job names its party, `Job(task, agents=[...], party=[...])`, in seat order and with repeats for self-play; each attempt plays that party once, and each Agent ranks by the mean of its seats' scores. `plural run` refuses a Task with a party. Each seat's Harness runs as its own OS user, in a folder no other seat can open, with its own seat token, and every file it creates is private to it; the Environment's files are shared read-only. An isolated party, the default, needs Docker or Daytona: it refuses `Runtime.local()`, and a Trial whose Runtime cannot keep the seats apart fails rather than play. `Party(isolation="shared")` instead runs every seat as one user that can see the others' files, for a team working on the same files or a party on the local Runtime. `TrialResult.seat_isolation` records `os_user` or, for a shared party, `none`. Benchmarks for several Agents are coming soon: a Benchmark refuses a Task with a party for now. Plural's Harness waits for its seat's turn, and a custom Harness calls `environment.wait_for_turn()`, which returns a `SeatTurn`. See [Several Agents in one Task](docs/project/multi-agent.md).

### Changed

- **Breaking:** Apps no longer give rewards; Verifiers do. The `@rewarder` decorator on App methods, `AppDefinition.rewarders`, and rewards returned from `Environment.on_step` are removed; move each into a Verifier's `reward` function. An Environment that lists `rewarders` is refused. Environment content hashes change.
- **Breaking:** `plural env from-mcp`, `from-openapi`, and `from-traces` are replaced by `plural env add`.
- **Breaking:** `Environment[Observation, State]` subclasses are replaced by Apps. Write `class Game(App[State])` with `@action` methods; what an action returns is what the Agent sees. Pass Apps to `Environment(apps=[...], runtime=...)`, or name the App class in `environment.yaml` with `python:`. The Environment-level `reward()` and `secrets` are gone.
- **Breaking:** a Task's `initial_state` is keyed by App name. With one App it may still give that App's fields directly.
- **Breaking:** resources are read-only volumes the Trial references. The Environment's files are staged under `/workspace/resources/environment-resources/` and the Task's under `task-resources/`, replacing `shared/` and `task/`; the manifest is schema version 2.
- `plural env init` writes a FastMCP server, `server.py`. `plural env init --python` writes the Python App template as before. New projects depend on `plural[mcp]`.
- Native actions are now called actions; the page moved to `concepts/actions`.
- A crashed MCP server's error includes the end of its output and the path of its log.
- A command MCP server gets a fresh, empty folder for each episode as `PLURAL_APP_DIR` (also its `TMPDIR`). Point the server's data file there, as in `MEMORY_FILE_PATH: ${PLURAL_APP_DIR}/memory.jsonl`, so one Trial's data never reaches the next.
- `plural env validate`, `plural run`, and `plural env add` use a secret stored with `plural secret set` when you have not exported it, including to start an App's server, and say where each secret comes from.
- `plural benchmark validate` says when a Benchmark is not reproducible and which live Apps make it so.
- `plural job show` prints why each failed Trial failed.
- A Verifier that exits with an error reports the end of its error output.
- **Breaking:** an action's result no longer carries its reward, even to the Harness; only its observation and step number. Rewards are in the ledger and `steps.jsonl` once the Trial ends.
- **Breaking:** `HarnessStep.reward` is removed, and the native Harness no longer reports `total_reward` or a `rewards` list in its episode document. A step's bare `reward` total no longer becomes an `environment` ledger record; every reward comes from a Verifier.
- **Breaking:** the unused `TraceDataset.from_sink` and `plural.client.start_trace` are removed. Build a dataset with `TraceDataset.from_traces`.
- **Breaking:** `check: {reward: NAME}` and `check: {reward: total}` are removed; write `check: total_reward` with the Verifier's own `reward` function. A `verifier.yaml` that still uses them says so.
- **Breaking:** the Verifiers a Task lists must have different names.
- **Breaking:** a declared control level is raised to what the App's settings allow. An App with credentials, or an MCP or OpenAPI App that reaches an outside system, is `live` unless it has a reset (`sandboxed`), whatever it declares, so it can't slip past the Benchmark and train Job checks.
- Each App's server and hooks get only the credentials and secrets that App declares. A remote MCP server that redirects is refused, so a credential header never follows the redirect.
- When a Task has a `HumanVerifier`, `hindsight` runs once the review is in, with the reviewed score.
- An App host started by an older Plural is refused rather than trusted.

### Fixed

- On Docker, the App host could not read the Environment and Task files staged for it, so an Environment with Apps failed to start; and a party's seat output could not be collected from its folder.
- The App host's private folder took the shared workspace's permissions when it was copied, so the Harness could list it. It is now readable by the App host only.
- A Harness's `setup` commands, which run as root, now run before the App host starts and before any secret or seat token is in the Runtime. Built-in Harnesses install their tools system-wide outside the local Runtime, instead of failing to write the workspace.
- `task.info` reaches `reward` functions and the App host as the Task gave it.
- A `reward` function that returns NaN or infinity records an error and 0 instead of corrupting totals.
- Replayed Apps return each repeated identical call's recordings in order rather than always the first.
- An OpenAPI App escapes path parameters, so an argument can't reach another route.
- The files server no longer follows a link out of its folders, and refuses very long search patterns.
- Reward totals count only the latest version of each Verifier, per source, so applying a new version no longer adds its records to the old version's.
- Model-judge Verifiers (`kind: agent`) failed on every run: the judge read a field Verifiers no longer have, and its structured-output schema was one OpenAI rejects.
- `Job(..., client=Client())` with `PLURAL_API_URL` set sent Harness model calls to the API root instead of its `/v1` gateway.
- Applying a Verifier again no longer duplicates its records, locally or in the hosted ledger; each record's id comes from the Trial, verifier, version, and target. `plural verifier apply` no longer warns about the hosted project for a Job that was never pushed.
- `plural run` with an endpoint Agent no longer asks for a Plural API key, and a missing `endpoint_key` value stops the run before it starts.
- An App's `close()` runs before the App host answers `stop`, so it is no longer cut off when the Runtime is torn down.
- Built-in App kinds no longer use their own class docstring as an App's description.
- An MCP tool with an argument named `tool` or `self` can be called.
- `timeout_seconds` applies to MCP servers reached by `url`, so a server that never answers no longer stalls the Trial.
- A `.jsonl` recording with one line loads as one recording rather than none.
- New projects require the Plural release that reads Apps, `plural[mcp]>=0.21`, rather than 0.15.

### Security

- The App host keeps the Apps' secrets, the Task's hidden initial State, and each step's App State to itself, so a Harness sharing the Runtime cannot read them. The initial State now reaches the host on its start pipe instead of a workspace file, per-step State is collected over the host's control socket, and the host marks itself non-dumpable so its memory and environment are not readable through `/proc`. A random per-Trial token, sent to the host out of band, gates the operations only the Job may run: reading App State (`query`, `finish`, `states`), ending the episode (`stop`), and restarting it (`reset` after the first). A Harness may start and act, but cannot read State or control the episode.
- An OpenAPI App refuses a path parameter of `.` or `..`, or one with a control character, so an Agent can't reach an operation the App doesn't offer, and refuses control characters in header parameters.
- A credential or secret with a stray carriage return or newline no longer reaches the Agent in an HTTP error. The App host also masks values as an error message quotes them, stripped or escaped.
- An OpenAPI document fetched from a URL no longer chooses where credentials go: an App whose headers carry a secret or credential needs `base_url`, and `plural env add --openapi` pins it from the document. A document that redirects to another host, or from `https` to `http`, is refused.
- **Breaking:** an MCP server started in the Runtime that holds project secrets is taken to reach an outside system, so it is `sandboxed` with a reset and `live` without one, and the Benchmark and train Job checks apply. Set `remote: false` for one whose secret only unlocks something in the Runtime.
- OpenAPI reset and snapshot hooks never receive the Agent's credentials, in process as in the App host.
- `plural pull` refuses a resource name from the hosted project that is not one folder name.
- The files server stops a query after 20 seconds and refuses a write larger than 5 MiB.
- Once the Job reads the episode back, the App host refuses every `step`, `reset`, and `turn`, and on Docker and Daytona the Job first kills every process the Harness's users left running, so nothing the Harness started can act while the Verifiers run.
- On Daytona, a file a Harness declares is downloaded only when, checked as the Harness's user, it is a regular file inside the Harness's folder rather than a symlink or a path leading out of it, as on Docker and the local Runtime.
- `episode.jsonl` takes each step's action and arguments from the App host as well as its observation and rewards, and numbers every record afresh, so a Harness cannot relabel a step or make two steps share one reward target.
- Under a Job, the App host stops only on the Job's signed `stop` or its idle timer, not when the shared Environment folder, which the Harness can delete, disappears.
- A Trial whose Harness timed out is no longer retried once the App host ran any action, or when the host can't say, so a Harness can't re-roll an episode that was going badly.
- With Apps, the Verifiers and stored artifacts take the observation, State, and step totals only from the App host: a Harness's own `observation.json`, `final-observation.json`, `state.json`, `final-state.json`, or `view.json` is dropped, `steps.jsonl` is written even when no action ran, and `plural verifier try` reads only the host's observation.
- Secret values the Job holds, Verifier secrets included, are masked in the App host's stored steps, States, and snapshots, in Verifier output, and in a Trial's error message, so an App error or a reward hook's exception that quotes one no longer stores it.

## [0.20.1] - 2026-10-07

### Fixed

- Daytona commands with a timeout no longer fail: timeouts are sent to Daytona in whole seconds, which is all its API accepts. Every Job passes the Runtime's command timeout, so Environments on Daytona could not run before this.
- A Daytona command that runs past its timeout now reports `timed_out` like the local and Docker providers, so a run records a timeout instead of a provider error, and the sandbox stays usable. This holds on your own Daytona account and on Plural's.

## [0.20.0] - 2026-10-06

### Added

- Runtimes: a reusable sandbox configuration a project's Environments run on. `plural runtime providers` and `plural runtime provider <provider>` explain every provider's settings and credentials; `plural runtime create`, `edit`, `show`, `list`, and `delete` manage a project's Runtimes, guided or with `--set key=value --no-input`; `plural runtime use <runtime> <environment>` copies one into an Environment's `runtime` block, recording its `ref`.
- Runtime templates and policy for accounts: `plural runtime template` saves approved provider configurations, credentials included, with settings members can't change, and `plural runtime policy set --mode templates-only` keeps members on them.
- Daytona Runtimes start their sandboxes on Plural's Daytona account by default, billed to your credits as compute usage, so no Daytona account is needed. `plural run` asks Plural to start each sandbox and relays commands and files to it; the API key never reaches your machine. Pass credentials or `--own-credentials` to use your own Daytona account, and `plural runtime edit <runtime> --plural-credentials` to switch back.
- When a Runtime uses your own credentials and they aren't set in your shell, `plural run` fetches them from the project Runtime for that run only.

### Changed

- Machine sizes come in whole steps: whole CPU cores, and memory in GiB on Daytona.
- E2B, Modal, Blaxel, and Cloudflare are listed as coming soon, as are AWS, Google Cloud, and Azure deployments. Runtimes can't be created on them yet.

## [0.19.0] - 2026-10-01

### Changed

- `trajectory.json` is now the plain chat transcript: `messages` with `role`, `content`, `reasoning_content`, and `tool_calls`, beside `status`, `time_elapsed`, and `finalized`. It is exactly what the model was sent, followed by its final reply. The ATIF document moves to `atif-trajectory.json`; a command-based Harness that writes ATIF should set its `trajectory` field to that name.
- The native loop sends the model each Observation's `render()` text instead of every Observation field as JSON, and the first prompt is the instructions, Task info, and the first rendered Observation. Empty fields are never sent. Prompts are much smaller, so token counts are not comparable with earlier runs.
- `plural auth login` stores a 30-day API key for the account selected in the browser that approves it, and says which account and when it expires. `plural auth scope --org` explains how to switch accounts when the credential acts for one.
- Action parameter schemas keep their constraints and nested models, so `Annotated[str, Field(min_length=5)]`, Pydantic models, and typed dictionaries reach the model as written. The Wordle tutorial's `guess` declares a five-letter lowercase word.

## [0.18.1] - 2026-09-30

### Changed

- `project push` and `<kind> push` look up hosted resources in parallel, push resources whose dependencies are in place together, and reuse one connection, so a project with a few dozen resources plans and pushes in seconds rather than most of a minute. When one resource fails to push, `plural.lock` still records every revision pushed alongside it.

### Security

- The Google provider and catalog sync send the API key in the `x-goog-api-key` header instead of the URL, so it no longer appears in request logs.

## [0.18.0] - 2026-09-29

### Changed

- The hosted project numbers revisions (`#1`, `#2`, `#3`) in push order, so you never bump a version to push a change. Pushing content a resource already holds makes that revision current again. `project push --bump` is no longer needed and is ignored.
- A content hash covers only what a revision contains: names, titles, and versions are left out, and dependencies are included by their own hashes. The rules and shared test vectors are in [Revision identity](docs/architecture/revision-identity.md). Existing revisions were rehashed and keep their earlier hash, so old pins still resolve.
- `version:` in a manifest is an optional release label. It is applied on push when no other revision already has it, and otherwise the push says which revision does.
- A push is refused when someone pushed a newer revision after the one you edited. Pull theirs, or pass `--force` to add yours on top.
- In a Job, an Agent's identity includes its name, so two identically configured Agents under different names can run side by side.
- Upgrade the SDK and CLI with this release: earlier versions compute the old hashes and the service refuses their pushes.

### Added

- `plural <kind> release NAME VERSION` gives the current revision a version people can cite, pushing it first if needed. Publishing a Benchmark requires one.
- `name@3`, `name@1.0.0`, and `name@sha256:61d8a0c` select a revision by number, release version, or content hash in `run`, `show`, `pull`, web links, and the API. `pull --revision` takes the same values.
- The hosted project records lineage for every revision, as `edited_from`, `forked_from`, and `derived_from` links, and marks each resource as sealed or referenced.

## [0.17.2] - 2026-09-28

### Changed

- Every model call goes through the Plural gateway, with the exact billed cost, a request id on each call, and project attribution for account keys.
- A tracked or hosted run pushes what it needs before it starts, bumping the patch version of anything that changed.
- Prompt caching is billed correctly. Every adapter reports cache reads and writes inside the prompt count, and `plural.catalog.billing` prices cache reads, 5-minute and 1-hour writes, and long-prompt tiers. Anthropic and Bedrock cached tokens and Gemini thinking tokens were previously unbilled.
- `plural models list` shows the organization's configured models by default. `--all` lists the whole catalog.
- Hosted projects are always private, and project roles are manager, contributor, and viewer. `plural project show` no longer prints a visibility.
- The documentation is rewritten for readers who are not engineers, and Getting started follows the web app's first-run tour.

### Added

- A Task, Benchmark, or Agent can be named as `name@version`, so `run`, `show`, and `pull` use that exact pushed version.
- `pull` fetches hosted Tasks, Agents, and Benchmarks that the local project lacks, including revisions made in the web app.
- Each catalog model has a full model card: description, release date, knowledge cutoff, max output, cache prices, and per-host limits and quantization.
- `Usage.reasoning_tokens` records how many completion tokens each provider spent on reasoning.

### Fixed

- Gemini tool calls carry their thought signature, so a replayed call is accepted on the next turn.
- Wordle checks guesses against the full Wordle word list.

## [0.15.0] - 2026-09-23

**0.15.0 break.** Plural is organized around a project directory and one command shape
for every resource. See [Migrate to 0.15](docs/migration/projects.md) for every removed
command and API and how to move a project.

### Changed

- A project is a directory with `project.yaml`, and each resource lives in its own directory under `environments/`, `tasks/`, `verifiers/`, `harnesses/`, `agents/`, or `benchmarks/`, named by that directory. Manifests refer to one another by name. Commands find the project by walking up from the current directory.
- Every resource kind has the same commands: `plural <kind> init|validate|push|pull|show|list`. `list` labels results local or hosted and filters with `--local` or `--hosted`. `plural benchmark add|remove` edits membership locally.
- `plural run -t <task>|-b <benchmark>` with `-m <model> [-h <harness>]` or `-a <agent>`. The default Harness is `native`. Every run is a Job, local by default, recorded under `.plural/jobs/` with the version and content hash of every input. `--hosted` runs pushed revisions only.
- A push creates an immutable, private revision that is available immediately. Pushes are validated first, all-or-nothing, and duplicate-free; `--with-deps` pushes the dependency graph. Each revision carries a content-addressed package of its files, which `pull` restores. `pull` refuses to overwrite differing local files unless `--force`, which keeps a backup.
- `plural auth login|logout|status|scope`. `plural auth scope` selects account or project scope after checking it with the service, keeps the organization context, and never changes what the credential may do. A push is refused when the scope and the checkout's project binding disagree.
- `plural project init <name>` works offline. `--push` creates or connects the private hosted project and selects it.
- `plural models list [--provider]` lists the models the organization allows.
- The server rejects a package whose bytes do not match its digest, or that contains a file that looks like a credential or a path that escapes the archive, using the same rules as the CLI.
- An API key limited to one project can reach only that project and cannot create projects.
- A Verifier with the default runtime scores inside the Task Environment. A runtime that sets its own provider, image, network, resources, or timeout uses that sandbox instead.
- Saving a version from the UI, the CLI, or the SDK makes it current. Files on disk are the working copy until they are pushed. The UI increments the last version number.
- Missing Agent keys and vendor model credentials name the environment variables that are absent and leave their values out of the error.

### Added

- `initial()` marks the State fields a Task may set before an episode, including constraints such as length and pattern. Unmarked fields stay episode progress and cannot be supplied as `initial_state`.
- Harbor ATIF documents normalize into the same trajectory events as native traces. Reward and verifier scores stay beside the trajectory.
- `score_from_rewards` turns a named rewarder, or the episode reward total, into a Verifier score.
- `plural job rerun` and `plural trial rerun` run the pinned inputs again as a new Job linked to the original. A hosted rerun is refused if the model catalog would resolve the Agent's model differently.
- `Workspace.get(kind, name)` loads a project resource from Python the way the CLI addresses it.
- Organizations can restrict which models their members run. Runs, reruns, and gateway calls enforce the restriction.
- `plural trial rescore` and `plural agent serve` are reserved.

### Removed

- `plural init`, `plural validate <file>`, `plural inspect`, `plural export`, `plural schemas`, `plural <kind> publish`, `plural benchmarks`, `plural job init|submit|watch`, `plural trial list|watch`, `plural review hosted-list|hosted-submit`, `plural models show`, and `plural harness schema`.
- `job.yaml` and `job.py` projects, `plural.project.Resolver`, `plural.load`, `plural.dump`, `plural.dumps`, and the Studio `publish` methods. Revisions no longer have a published status.

### Fixed

- A Python-authored Job with a deterministic Verifier can resume its own store. Its stored configuration was compared with a live callable and always reported `lock_incompatible`.
- A provider API key is never sent to the Plural gateway. The gateway URL is set only when a Plural API key is present.

## [0.14.0] - 2026-09-21

### Changed

- **0.14.0 break.** A Verifier produces a `score`. A step `reward` stays on the episode and never becomes that score. `VerifierOutput` and `VerifierResult` take `score`.
- `HarnessDefinition` is the public flattened schema. `Harness` stays the authoring base class. The internal wire model is `HarnessProtocol`.
- An episode ends with a declared stop reason. `Environment.step` returns the observation, reward, terminated flag, truncated flag, and info. Only the observation is shown to the Agent.

### Added

- `Task.definition()`, `Task.push()`, and `Task.delete()` publish a local Task the same way an Environment does. Push resolves each bound Environment and Verifier to its current published revision.
- `plural task init` writes `instruction.md`, `task.yaml`, and `resources/`, and asks before reusing a slug that already exists in the project.
- Session snapshots can be saved and redeployed as a directory bundle.

## [0.13.3] - 2026-09-16

### Changed

- **0.13.3 break.** Custom Harnesses are Python subclasses with one
  `run(task, agent, environment)` method. Plural discovers and hashes the class
  directory and writes standard result, trajectory, log, and TITO artifacts.
  Manual command, source, output, and transport declarations are removed.
- **0.13.2.** Hermes, Claude Code, and Codex attach with `Agent(harness="...")`
  and optional `harness_kwargs`. Plural installs the pinned CLI in the
  Environment Runtime and maps Job credentials. Custom Harnesses remain the
  escape hatch. Declared-only vendor recipes are rejected.
- **0.13.1.** Environment subclasses are Job-ready from the class file. Pass
  `runtime=`. Plural hashes that directory and runs `reset` and `@action`
  methods. `.package()` and user-written command adapters are gone.
- **0.13.0 break.** `Environment.runtime` is required. The defaults are a
  public network and `python:3.12-slim`. Use `Runtime.docker()`,
  `Runtime.local()`, or `Runtime.daytona()`.
- Deterministic verifiers are functions over an `Episode`. `EvidenceContract`
  is removed. State is always agent-invisible; `hidden()` is gone.
- Live Jobs require `client=Client()` or `api_key=`. Model auth is not
  `Agent.secret_names`. CLI live runs need `plural auth login` or `--api-key`.

### Added

- Reorganize documentation into a concise path from the first evaluation
  through Runtime providers, versioning, and RL data capture.
- Add end-to-end support queue and Wordle tutorials plus dedicated Python,
  CLI, and YAML guides.

### Fixed

- Pass resolved model identifiers to native Harness execution.
- Reject Agent secret grants that are not declared by the selected Harness.
- Fail-closed Task, Runtime, Agent, and Job errors name the object, the rule,
  and the fix.

## [0.12.1] - 2026-09-13

### Fixed

- Replace leaked advanced Harness internals with one plain public `Harness`
  value whose executable source is locked and compiled only inside execution.
- Keep Harness and Agent YAML, CLI scaffolds, generated schemas, and current
  documentation free of internal transport and content-lock structures.

## [0.12.0] - 2026-09-13

### Added

- Plain public `Environment`, `Runtime`, `Agent`, `Task`, `Benchmark`, `Job`,
  and `Verifier` APIs with one catalog-backed model field and one optional
  Agent harness.
- Lossless Python/YAML project serialization, explicit project model catalogs,
  and local-first `init`, `validate`, `inspect`, `export`, `run`, `models`, and
  `benchmarks` CLI workflows.
- Immutable semantic Benchmark versions, ordered Task pins, structured diffs,
  dependency exports, and per-Agent leaderboard aggregates.
- Normalized Job/Trial/execution bundles with artifact manifests, model and
  Benchmark provenance, provider-neutral trajectories, and Mercor imports.

### Changed

- Python SDK objects now define all field names, defaults, validation, YAML,
  generated schemas, CLI behavior, and hosted payloads.
- Runtime retries are stored under `trials/{trial_id}/executions/{id}` while
  preserving read-only support for existing local `attempts` directories.
- Native chat/action harness selection is inferred when an Agent omits its
  harness; protocol versions remain internal.

### Removed

- Public `*Definition`, `*Binding`, `WeightedVerifier`, `TaskFile`,
  `BenchmarkFile`, `JobFile`, and `native_*_v1` authoring APIs.
- Hosted-by-default beginner execution and the parallel SDK/YAML/CLI domain
  models.

## [0.11.0] - 2026-09-11

### Added

- `EvidenceContract` on every Verifier kind. `TaskDefinition` and hosted task
  revision create fail closed when observation or state paths are absent from
  the Environment schemas. Verifier sandboxes receive a filtered
  `environment_view`.
- `HarnessGrant` (formerly `HarnessStamp`) records the Environment ceiling on
  harness tools for one Trial. Denied tools are injected before the first turn
  and soft-denied at runtime.

### Changed

- Schema-v2 `EnvironmentManifest` / `HarnessManifest` are now
  `EnvironmentDefinition` / `HarnessDefinition`. `Environment.definition()`
  replaces `.manifest()`. Harness packages dump the `definition` key and still
  load the 0.10 `manifest` key.
- A Harness wraps the Agent-side LLM. Environment native actions stay on the
  Trial request. The Environment may only subtract harness tools; restricted or
  unknown harness tools return feedback and the Trial continues.

### Migration

- Rename `manifest:` to `definition:` in `harness.yaml` and hosted harness
  payloads. The loader warns once on the old key.
- Replace `resolve_trial_harness_stamp` / `HarnessStamp` with
  `resolve_trial_harness_grant` / `HarnessGrant`.
- Move deterministic `required_artifacts` into `evidence.artifacts` (the old
  field remains a load alias).

## [0.10.0] - 2026-09-10

### Added

- Schema-v2 `Environment`, `Task`, deterministic/agent/human `Verifier`,
  `AgentDefinition`, cross-environment `BenchmarkDefinition`, `Job`, `Trial`,
  and retrying `TrialExecution` contracts with immutable revision hashes.
- Environment-directed bounded execution, append-only live progress events,
  human-review waits, train-only Rewarders, and artifact-backed exact TITO
  records.
- Canonical parent/revision publishing APIs and CLI workflows for authoring,
  validating, running, watching, reviewing, and publishing the complete graph.

### Changed

- Environments now own actions, hidden state and observations, resources,
  runtime/network/secrets policy, and train-only Rewarders. Tasks inject one
  Environment revision and weighted Verifier revisions.
- Jobs select either a Task or Benchmark and expand Agents × Tasks × attempts;
  Environment placement remains authoritative while Job concurrency and retry
  settings control scheduling.
- `plural run` now validates and synchronizes the complete canonical revision
  graph, submits a hosted Job with stable idempotency, and watches hosted events
  by default. `--offline` and `--private` explicitly retain local execution.
- Trace schema v3 records exact provenance, run mode, verifier/review outcomes,
  reward events, and artifact references.

### Removed

- Environment-owned tasks/final scorers, `AgentTemplate`/`AgentInstance`,
  `TaskData`/`TaskDataset`, the legacy Benchmark runner, and parallel v1/v2
  execution paths.

## [0.9.0] - 2026-09-09

### Changed

- Foundation rewrite: environments own native actions and runtime; harnesses
  are stamped and capability-restricted; agents split into templates and
  instances; traces are schema 2.0.0 (`Turn` / `ActionStep`).
- `@tool` is `@action`. `AgentSpec` and `EnvironmentCommand` are deleted.
- Secure defaults: `network=none`, local excluded. Unsatisfiable requirements
  fail in `resolve_effective_policy()` before launch.
- Declared harnesses (`hermes`, `claude-code`, `codex`, `cursor`) cannot run.
  The native runner (`native.chat.v1`, `native.actions.v1`) is the only
  runnable executor.

### Removed

- Backward-compatible aliases, `_migrate_legacy_trace`, and v1 trace schema.

## [0.8.0] - 2026-09-09

### Added

- `hidden()` marks a `State` field as agent-invisible. The flag is stored on
  the JSON Schema as `x-plural-hidden` so studio can show visibility.
- Alpha v1 package domain for immutable Environment, Harness, Agent, Benchmark,
  Job, Trial, lock, receipt, verifier, artifact, retry, and runtime contracts.
- `plural` Typer CLI for device auth/context, package scaffolding and
  validation, deterministic dry runs, local job persistence/control, and
  runtime inspection. Job registration and result upload are opt-in
  (`--sync` / `plural job upload`). Organization and project listing are
  not implemented yet.
- Provider-neutral Harness JSONL protocol, built-in chat/tool/code profiles,
  narrow ACP v1 and separately installed Claude Code/Codex/Hermes adapters,
  deterministic archive retrieval, and exact artifact contracts.
- Local development, Docker, Daytona, and entry-point sandbox providers with
  capability preflight, cancellation, cleanup, isolated verifier regrade, and
  self-reported execution receipts.
- Generated package/CLI JSON Schemas, generated CLI command reference, drift
  checks, security/operations/migration documentation, and offline execution
  examples.

### Changed

- `Observation` is the per-action view returned by `reset` / `step`.
  `State` is the persistent environment object; durable structures live there.
- `Benchmark` is a reusable definition (`name`, `primary_metric`). Each
  `.run()` is a report attached as a hosted run. Win rates compare the
  chosen metric. Pushing a report uploads episode traces with `run_group_id`.
- Legacy `Benchmark.repeats` and `TaskDataset` remain compatible. New
  `JobSpec.n_attempts` names independent Trial repetitions; execution retries
  are tracked separately without changing Trial identity.

## [0.7.4] - 2026-09-02

### Added

- Environment `description`, `readme`, `guardrails`, and `skills` with empty
  defaults. Observation and state JSON schemas come from the generic models.
- Hosted environment manifests now include those schemas, guardrails, skills,
  overridden hooks, and the default context policy.

## [0.7.3] - 2026-09-02

### Added

- `Client.create(x)` and `Client.update(x)` for environments, traces, and
  benchmarks. Environments, agents, and benchmarks are addressed by
  project-unique slug; traces stay id-based.
- `env.create(client)` and `env.update(client)` aliases.

### Changed

- Duplicate environment, agent, or benchmark slugs now conflict instead of
  being uniquified with a suffix.
- `client.push` / `env.push` upsert by slug instead of creating a new row
  when the name already exists.

## [0.7.2] - 2026-09-02

### Added

- `Client.push(x)` syncs a local `Environment`, `Trace`, `Benchmark` (after
  `run()`), or `Report` to the hosted project. Agents are created with
  `client.agents.create(...)` and are not pushable.
- `env.push(client)` remains as an alias for `client.push(env)`.

## [0.7.1] - 2026-09-02

### Added

- Studio APIs on `Client` for hosted environments, agents, benchmarks, and
  traces. Account API keys require `project=` or `PLURAL_PROJECT`; project
  keys already know the project.
- `Environment.push(client)` creates or updates a local environment on a
  Plural project.
- `client.agents.get(...).invoke(prompt)` reads a hosted agent and calls it
  through the gateway.

## [0.6.1] - 2026-08-26

### Added

- `Client.is_authenticated()` probes each configured provider and reports
  whether credentials are accepted.

### Changed

- The high-level client is now `Client`. Import it with
  `from plural import Client`. `Plural` remains as a backward-compatible alias.

## [0.6.0] - 2026-08-25

### Changed

- Rename the library, GitHub repository, and PyPI project from `enroute` to
  `plural`. The project now lives at `lastlabs-ai/plural`. The client is
  `Plural`, errors are `PluralError`, environment policies are `PluralPolicy`,
  and the default env var / trace directory are `PLURAL_API_KEY` and `.plural`.
  `ENROUTE_API_KEY` is still read as a fallback.

## [0.5.1] - 2026-08-24

### Fixed

- Refresh model catalog list prices for DeepSeek V4 Flash, Gemini 3.7 Flash,
  GPT-5.6, and GPT-5.6 Sol.

## [0.5.0] - 2026-08-24

### Added

- Wordle `--host mlx` / `--mlx` talks to `mlx_lm.server` on
  `http://127.0.0.1:8080/v1`. Live runs print the harness the policy saw
  and write `wordle-summary.json` plus the full episode trace.
- Runnable offline benchmark examples now cover both model IDs and arbitrary
  policy factories with versioned `TaskDataset` inputs, persisted episode
  traces, and Markdown/JSON reports.
- Library and Twitter example guides, plus deterministic Twitter
  `wait_for_engagement` for an achievable delayed-likes task.
- Executable Wordle, Library, and Twitter notebooks covering environment
  authoring, scored traces, training returns, versioned tasks, and benchmarks.
- Synchronous environment policy APIs: the `Policy` protocol,
  `EnroutePolicy`, `ScriptedPolicy`, and `Environment.run_episode()`.
  `Benchmark.from_policies()` accepts named fresh-policy factories for
  arbitrary policy comparisons without an Enroute client.
- Explicit episode lifecycle and stop APIs: `EpisodeState`, `EpisodeError`,
  `StopReason`, and `Environment.episode_state`. Invalid reset/step/messages/
  close sequences are guarded.
- Deterministic replay APIs: `replay_actions()`, `verify_replay()`,
  `ReplayResult`, and `ReplayMismatch`, with fingerprint, observation,
  transition, snapshot, and final-stop verification.
- `TaskDataset` for versioned benchmark inputs, plus the `TraceDataset` alias
  and declarative `TraceFilter` for rollout/production trace collections.
- Benchmark provenance/report types: `CaseKey`, `CaseResult`, `WinRatePair`,
  `ModelStats`, `RunManifest`, `TaskSetMetadata`, and `TaskDatasetMetadata`.
  Reports now include per-case provenance, failure buckets, descriptive reward
  uncertainty, and run metadata.
- Benchmark environment/runtime factories: `environment_factory` creates a
  fresh environment when `spawn()` cannot reproduce required constructors or
  stateful dynamic closures, while `runtime_factory` creates a fresh
  synchronous sandbox, remote, or custom runtime for each job.
- Optional `trace_writer` persistence for `Benchmark.from_policies()`.
  Successful and failed episode traces are recorded when a caller-owned writer
  is supplied.
- Trace lineage and classification fields: `trace_kind`, `parent_trace_id`,
  `episode_trace_id`, and `stop_reason`; decisions now include `decision_id`
  and zero-based `index`. `TraceContext` links optional child LLM-call traces
  to an episode.
- Text-action helpers `TEXT_ACTION`, `normalize_action()`, `is_text_action()`,
  and `is_tool_action()`; text-only responses are recorded as `respond`
  actions and stop with `policy_stop`.
- Public `ActionResult` and the `Environment.apply_action()` author hook for
  scalar, text, and custom action semantics.
- `trace_json_schema()` for loading the packaged canonical JSON Schema.
  `scripts/generate_trace_schema.py` generates and checks identical packaged,
  repository, and documentation mirrors from the Python `Trace` model.

### Changed

- After each `step`, the next observation is appended to `env.messages()`
  so the policy sees the same board the decision recorded, not only the
  last tool JSON.
- `Environment.step()` is now framework-owned and rejects subclass overrides.
  It centrally records responses and decisions, manages tool messages/errors,
  merges `ActionResult.info`, and advances lifecycle state. Tool environments
  retain the default dispatch behavior; custom actions override
  `apply_action()`.
- Environment types live in their own modules (`task`, `step`, `rollout`,
  `episode`, `tool`, `action`). `from enroute.environments.env import
  TaskData` still works.
- `Environment.snapshot()` now returns `None` by default. State is persisted
  only when an environment explicitly returns a trace-safe snapshot.
- `Environment.fingerprint()` now hashes tool, scorer, and hook implementation
  bodies, configured callable-object/closure state, and
  `fingerprint_payload()`, in addition to `max_turns`, instructions, type
  contracts, schemas, weights, and standard environment fields.
- Environment authors can override `fingerprint_payload()` for
  behavior-affecting constructor or external configuration that is not
  represented elsewhere. Payloads must be deterministic and must not contain
  secrets.
- Environment rollout persists exactly one episode trace by default.
  `record_llm_traces=True` opts into separately persisted, linked child LLM
  traces; policy calls otherwise remain inside episode decisions.
- `TaskData.expected` is scorer-only and is no longer copied into episode
  trace metadata. Deterministic replay that needs this hidden value must
  receive the original `TaskData` explicitly.
- `Trace.transitions(source=...)` now aligns reward selection with
  `decision_rewards()` / `returns()`: `outcome`, `events`, or `both`.
- Trace dataset content hashes now cover full canonical trace serialization
  (`hash_version="2"`), and loads verify supported manifest hash versions.
  Task dataset hashes cover complete tasks, including sensitive `expected`
  labels and metadata, in task order, with required integrity-checked
  manifests. `content_hash` is a snapshot identity,
  `current_content_hash` recomputes current mutable content, and `save()`
  refreshes the snapshot.
- `Benchmark.run(dataset=...)` now consumes `TaskDataset`. Trace datasets are
  rollout/production outputs for analysis, export, and training artifacts.
- Benchmark manifests use the identity of the environments actually created
  for worker jobs, include an order-sensitive `task_set` hash for task
  datasets, explicit tasks, and environment-provided tasks, and record
  `runtime_fingerprints`. Stale mutated `TaskDataset` inputs are rejected.
- Pairwise benchmark win rates are now aligned by `(task_id, repeat)` rather
  than concurrent completion order. Failed or unscored pairs are excluded
  and counted; ties count as half a win.
- Benchmark cost and latency statistics aggregate episode-total metrics.
  `Report.compare()` accepts a non-negative absolute reward `tolerance`,
  validates compatible environment/runtime/task provenance by default, and
  supports `allow_incompatible=True`. `Report.manifest` remains optional when
  loading legacy reports.
- Default content redaction now also removes environment task input, state
  snapshots, decision observations, decision request/response content, and
  text-action payloads.
- Every `StopReason` now enters the `stopped` lifecycle state; only
  `messages()` and `close_episode()` remain valid until close. Policy, action,
  step, and scorer exceptions close the trace as `failed` with stop reason
  `failure`.
- Pre-1.0/v0.4 traces without `trace_kind` are migrated on load. Episode kind
  and lineage are inferred, and missing decision indexes/ids are generated
  deterministically. Replay now rejects traces marked as redacted.

## [0.4.0] - 2026-08-21

### Added

- Gym-shaped environments: subclass `Environment`, decorate methods with
  `@tool`, and use `reset` / `step` / `close_episode` alongside `rollout()`.
  One rollout is one episode; the model is passed in, not baked into the
  environment. The default `step` dispatches tools and records a decision.
- Episode traces: optional `Decision` steps (observation, model context, parsed
  action, tool results, reward events) plus `initial_state`, `final_state`,
  `model`, `metrics`, `terminated`, `truncated`, and `environment_fingerprint`.
  `Trace.transitions()` flattens an episode for downstream analysis. Production
  `llm` / `tool` / `event` steps still round-trip.
- Simulated Twitter account example (`examples/environment/twitter`) with
  person-complete tools and pluggable goals.
- `Trace.credit()` (late reward on the episode or one decision) and
  `Trace.returns(gamma=…)` for discounted credit assignment. Reward is not
  assumed per decision — research-then-answer uses a terminal scorer; likes
  that arrive later use `credit`.
- Library example (`examples/environment/library`): search / read / answer,
  the start-to-finish RL handoff.
- Wordle example (`examples/environment/wordle`): `WordleEnv` owns the secret,
  official word lists, `guess`, board observations, and rewards. The model
  is only the policy. The example plays via `reset` / `step` (Gymnasium /
  OpenEnv); `rollout()` stays as convenience.
- `Observation` and `State` types (`Environment[ObsT, StateT]`). Nested
  `@tool` calls are recorded as `ToolCallStep.children` for hierarchical
  credit later. Library `research` is the demo.

### Changed

- `World` / `BaseWorld` / `world=` are gone. Write
  `class WordleEnv(Environment[WordleObservation, WordleState])` and put
  episode data on `self.state`. `Rollout.env` replaces `Rollout.world`.
  Concurrent episodes use `env.spawn()` (Benchmark does this automatically).
  Drive agents with `reset` / `step` / `rollout`; `observe` is an author hook.

## [0.3.4] - 2026-08-18

### Added

- `StreamDelta.reasoning_started` and `reasoning_finished` mark the bounds of a
  thinking block, including when Anthropic encrypts the tokens and sends empty
  `thinking_delta` events. A UI can show a thinking indicator the same way
  Cursor does, even when there is no readable text. Anthropic requests ask for
  adaptive thinking by default so those bounds actually arrive.

## [0.3.3] - 2026-08-18

### Added

- `Message.reasoning` and `StreamDelta.reasoning` surface thinking-model output,
  read from `/v1/responses` on OpenAI, `reasoning`/`reasoning_content` on other
  OpenAI-compatible hosts, `thinking` blocks on Anthropic, `thought` parts on
  Gemini, and `reasoningContent` on Bedrock. `reasoning_signature` carries the
  host's attestation so a thinking block can be replayed on the next turn.
- OpenAI requests now use `/v1/responses` by default. Chat Completions rejects
  function tools on every current model and never reports reasoning; Responses
  streams both. A request that needs `stop`, `seed`, or a `max_tokens` below 16
  stays on Chat Completions. Pin `transport="chat"` or `transport="responses"`
  to force one endpoint.
- `response_format` now works on every host. Gemini uses its native
  `responseSchema`; Anthropic and Bedrock force a single-tool call whose input
  schema is the requested schema and unwrap the result into message content.
- `tool_choice` is translated for Anthropic and Bedrock.
- A capabilities guide covering streaming, tool calling, structured output, and
  reasoning.

### Changed

- Gemini requests ask for thought summaries (`includeThoughts`) so a thinking
  model is not silent for seconds before the first text delta.

### Fixed

- Anthropic streams now emit tool calls. `content_block_start` and
  `input_json_delta` were dropped, so tool calling silently produced nothing
  when `stream=True`.
- Bedrock streams now emit tool calls and reasoning from `contentBlockStart` and
  `contentBlockDelta`.
- Gemini streams now emit tool calls; `functionCall` parts were dropped.
- Failed streaming requests report the host's error instead of an httpx
  "Attempted to access streaming response content" message, which masked real
  4xx bodies on Anthropic, Google, and Bedrock.
- OpenAI-compatible hosts that 400 on `max_tokens` are retried with
  `max_completion_tokens`, and reasoning models that reject `temperature` or
  `top_p` are retried without them. Both rejections are remembered per model.

## [0.3.1] - 2026-08-18

### Added

- `StreamChunk.to_openai()` so a hosted gateway can emit one OpenAI Chat Completions
  SSE shape from every host. `raw` stays on the chunk for debugging and is not
  part of the client contract.
- Live stream smoke tests that pin `provider.only` for each configured key.

### Fixed

- Anthropic streams now carry `input_tokens` from `message_start` onto the usage
  chunk, so a streamed prompt is billed at the real token count.
- OpenAI-compatible hosts that 400 on `stream_options` are retried without it.

## [0.1.0] - 2026-08-13

### Added

- Initial `enroute` package: unified LLM routing with traces, environments, and benchmarks.
- Native httpx providers for OpenAI-compatible APIs, Anthropic, and Google.
- `Enroute` client with hosted-gateway mode (`ENROUTE_API_KEY`) and BYOK `providers={...}`.
- Routing policies, fallbacks, retries, model catalog, and local cost estimation.
- Tracing with JSONL/SQLite/OTel sinks, redaction, sampling, and late labels.
- Environments (tasks, tools, scorers), versioned datasets, and benchmark reports.
- Docs site (MkDocs) and cookbook-style routing examples.

[Unreleased]: https://github.com/lastlabs-ai/plural/compare/v0.14.0...HEAD
[0.14.1]: https://github.com/lastlabs-ai/plural/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.14.0
[0.13.3]: https://github.com/lastlabs-ai/plural/releases/tag/v0.13.3
[0.12.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.12.1
[0.12.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.12.0
[0.8.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.8.0
[0.7.4]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.4
[0.7.3]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.3
[0.7.2]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.2
[0.7.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.1
[0.6.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.6.1
[0.6.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.6.0
[0.5.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.5.1
[0.5.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.5.0
[0.4.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.4.0
[0.3.4]: https://github.com/lastlabs-ai/plural/releases/tag/v0.3.4
[0.3.3]: https://github.com/lastlabs-ai/plural/releases/tag/v0.3.3
[0.3.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.3.1
[0.1.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.1.0
