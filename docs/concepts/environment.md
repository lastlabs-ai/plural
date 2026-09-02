# Environment

An `Environment[Observation, State]` is a versioned, Gymnasium-shaped harness for tasks, actions, observations, stop conditions, and scorers. The policy is separate from the environment, and every completed run produces one scored episode [Trace](trace.md).

The environment is everything except the model: instructions, tools (actions), observation and state schemas, guardrails, tasks, runtime, and how a turn becomes a `ChatRequest`. A working env can be a name, a version, one `@tool`, and `observe()`. Extra fields stay optional.

```python
class RefundEnv(Environment[RefundObservation, RefundState]):
    name = "refund-support"
    version = "1.0.0"
    description = "Resolve refund tickets against order eligibility."
    readme = "Check eligibility, then refund only when the order is allowed."
    guardrails = [
        "Never refund before checking eligibility.",
        "Do not expose hidden expected values or secrets.",
    ]
```

`Observation` is the typed view the policy may see. `State` is writable memory and other data structures the agent and tools update as they go — including hidden fields. Both schemas are derived from the Pydantic models and uploaded with the hosted revision.

## Environment and policy

Implement environment behavior by overriding author hooks such as `setup`, `observe`, `done`, and—when actions are not tool calls—`apply_action`. Drive it through `reset` / `step`, `run_episode`, or `rollout`; do not call `observe` as the agent loop.

Policies use the synchronous `Policy` protocol:

```python
class MyPolicy:
    def act(self, request, *, trace_context=None):
        return ParsedAction(name="lookup", arguments={"query": "refund"})

rollout = env.run_episode(task, MyPolicy(), model="my-policy")
```

`Policy.act()` receives the exact `ChatRequest` built by the environment and returns a `ChatResponse`, one `ParsedAction`, or a list of `ParsedAction` values. Built-in adapters are:

- `PluralPolicy(client, model, ...)` for Plural model calls.
- `ScriptedPolicy(actions)` for deterministic tests and offline examples.

`rollout(task, client, model=...)` is convenience around `PluralPolicy` plus `run_episode`.

## Lifecycle guards

An environment instance has an explicit `episode_state`:

| State | Meaning | Valid next operation |
| --- | --- | --- |
| `idle` | No episode has started | `reset(task)` |
| `open` | An episode is active | `messages`, `step`, `close_episode` |
| `stopped` | A `StopReason` has been set | `messages`, `close_episode` |
| `closed` | The prior episode was scored and closed | `reset(task)` |

Calling an operation outside its valid state raises `EpisodeError` with the current `EpisodeState`. Every defined `StopReason` enters `stopped`, even when both Gym flags are false. After that, only `messages()` and `close_episode()` are allowed; close before resetting. `Environment.step()` is framework-owned and cannot be overridden, which guarantees these lifecycle checks for every action.

## Actions and stopping

`step` records one `Decision` and advances the lifecycle. Its default `apply_action` hook dispatches tool actions to `@tool` methods, so tool-based environments need no action override. A model response without tool calls is normalized to the text action `ParsedAction(name="respond", arguments={"text": ...})` and defaults to `policy_stop`.

For scalar or custom text workflows, override `apply_action(action, *, runtime, response=None)` and return an `ActionResult`. The hook receives the raw action, may mutate environment state, and describes the turn with `parsed_actions`, `tool_calls`, `reward_events`, `stop_reason`, and `info`. Return `stop_reason=None` to continue after a text action:

```python
from plural import ActionResult, Environment
from plural.tracing import ParsedAction

class RatingEnv(Environment):
    def apply_action(self, action, *, runtime, response=None):
        self.state.rating = int(action)
        return ActionResult(
            parsed_actions=[
                ParsedAction(name="rate", arguments={"value": self.state.rating})
            ],
            stop_reason=None,
            info={"accepted": True},
        )
```

Do not call `record_decision()` or `finish_turn()` from `apply_action`; `step` records the returned result and advances exactly once. Those methods remain public only for advanced manual integrations. Custom `ActionResult.info` is merged into `StepResult.info`, but cannot replace canonical `turn`, `stop_reason`, or `tool_errors` values.

`step` returns `(observation, reward, terminated, truncated, info)`. `info["stop_reason"]` and the final trace distinguish why the episode stopped:

| `stop_reason` | `terminated` | `truncated` | Meaning |
| --- | ---: | ---: | --- |
| `terminated` | true | false | `done()` reached a natural terminal state |
| `truncated` | false | true | `max_turns` was reached before termination |
| `policy_stop` | false | false | The policy emitted no tool action, usually a text response |
| `failure` | false | false | A custom loop explicitly stopped because execution failed |

Natural termination takes precedence over truncation; truncation takes precedence over an explicit policy stop on the same turn.

Exceptions from a policy, `apply_action`, `step`, or a scorer close the episode trace, set `failed=true` and `stop_reason="failure"`, and re-raise. `run_episode(..., persist_with=client)` persists that failed trace before re-raising.

## State, observations, and snapshots

State can contain hidden values; observations are what the policy may see. Snapshots are independently controlled for persistence:

```python
class WordleEnv(Environment[WordleObservation, WordleState]):
    def snapshot(self) -> dict:
        # Include only fields approved for trace storage.
        return {"guesses": list(self.state.guesses)}
```

The default `snapshot()` returns `None`. This safe-by-default behavior prevents `self.state`—including secrets—from being serialized accidentally. Override it only with an explicitly trace-safe representation; it supplies both `initial_state` and `final_state`.

`TaskData.expected` is scorer-only and is never copied into episode trace metadata. The trace includes `task_id`, task `input`, and task `metadata`.

## Runtime boundary

`Runtime` is the small extension boundary for tool execution:

```python
class Runtime(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> Any: ...
```

`LocalRuntime` executes registered Python callables in-process. Supply another synchronous implementation to `step`, `run_episode`, or `rollout` when tool invocation needs a sandbox, remote executor, or another boundary. The runtime interface is a synchronous public-alpha extension point; plural does not provide a sandbox or remote execution service.

For benchmarks, `runtime_factory` creates a fresh runtime per job. Custom runtimes may expose `fingerprint()` or `fingerprint_payload()`; benchmark manifests record the resulting `runtime_fingerprints`.

## Fresh benchmark workers

`Benchmark` calls `env.spawn()` for each job. The default implementation reconstructs the environment with standard constructor fields and copies or rebinds tools, scorers, and the task provider. It cannot safely recreate subclasses with required constructor arguments or stateful dynamic closures that capture the original environment.

Override `spawn()` when the subclass owns a reliable reconstruction strategy, or pass `Benchmark(..., environment_factory=lambda: MyEnv(...))`. The factory must return a fresh, fully configured environment per job.

## Tracing and persistence

`run_episode(..., persist_with=client)` and `rollout(...)` persist exactly one `trace_kind="episode"` trace by default. Each decision stores its stable `decision_id`, zero-based `index`, observation, policy request/output, parsed actions, tool results, and reward events.

`rollout(..., record_llm_traces=True)` opts into additional `trace_kind="llm_call"` child traces. Each child has `parent_trace_id` and `episode_trace_id` set to the episode trace id. With the default `False`, model calls are embedded in decisions but are not persisted as duplicate top-level traces.

## Deterministic replay

Replay applies recorded actions without calling a policy:

```python
result = verify_replay(WordleEnv(), rollout.trace, task=task)
assert result.ok, result.mismatches
```

Replay checks the environment fingerprint, decision observations, step rewards and stop flags, final safe snapshot, and final stop state. A trace normally reconstructs `TaskData` from `metadata["task"]`. Because `expected` is intentionally excluded, pass the original `task=` when setup or scoring needs that hidden value.

Replay rejects traces marked as redacted because their actions, observations, state, or task input may no longer be complete enough for deterministic execution.

## Compatibility fingerprint

`environment_fingerprint` hashes the environment name/version, `max_turns`, system instructions, observation/state type names and JSON schemas, guardrails, skills, tool schemas, scorer names and weights, and implementation bodies for tools, scorers, and the `setup`, `observe`, `apply_action`, `done`, `snapshot`, and `step_reward` hooks. It also includes stable configured state for callable objects and closures. Callable-object configuration includes private instance fields and slots; define `fingerprint_payload()` on the callable when a smaller authoritative stable configuration is appropriate.

Override `fingerprint_payload()` when behavior depends on constructor arguments or external configuration not already represented—for example, a ruleset id or endpoint version. Return only deterministic, non-secret values. Never include credentials, tokens, or other secrets in environment or callable fingerprint configuration.

Use the declared `version` as the human compatibility key and the fingerprint as a local execution-contract compatibility key. Benchmark manifests record both, but a matching fingerprint cannot guarantee identical results from changing external services, nondeterministic dependencies, or mutable remote data.

## Rewards and transitions

Step rewards become `Decision.reward_events`; end-of-episode scorers become `trace.outcome.reward`. Late labels can be attached with `trace.credit(...)`. Select the intended source explicitly when flattening:

- `trace.transitions(source="outcome")` puts the episode outcome on the final decision.
- `source="events"` uses decision reward events.
- `source="both"` combines them.

Task inputs belong in a [TaskDataset](dataset.md); completed episode traces belong in a `Dataset` / `TraceDataset`. See [Benchmark](benchmark.md) for repeated comparisons.

## Hosted sync

`client.create(env)` and `client.update(env)` upload the local environment
by slug. See [Create and update hosted objects](../guides/push-to-plural.md).
