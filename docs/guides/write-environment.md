# Write a stateful Python environment

New to Plural? Start with the [complete support walkthrough](../tutorials/sdk-walkthrough.md).
This guide adds state, custom actions, replay, and lifecycle details.

Use this checklist:

1. Subclass `Environment[MyObservation, MyState]`; set `name`, `version`, and `max_turns`.
2. Seed `self.state` in `setup(task)`. Persist boards and other durable structures there, mark secrets with `hidden()`, and expose only the visible slice from `observe()`.
3. Decorate actions with `@action`, or register functions with `@env.action`.
4. For scalar or custom text actions, override `apply_action()` and return `ActionResult`; tool-only environments need no override.
5. Implement `done()` for natural termination and scorers for the final outcome.
6. If state should be persisted, override `snapshot()` with an explicitly trace-safe dictionary. The default is `None`.
7. Give every `TaskData` a stable `task_id`; put deterministic seeds in task metadata.
8. Override `fingerprint_payload()` for behavior-affecting constructor or external configuration not represented by your hooks and callables.
9. Run the environment through `run_episode`, `rollout`, or guarded `reset` / `step` / `close_episode`.

## A small stateful environment

```python
from plural import Environment, TaskData
from plural.environments import Observation, State, hidden, tool

class CounterState(State):
    count: int = 0
    target: int = hidden(2, description="Goal the agent must not see.")

class CounterObservation(Observation):
    count: int

    def render(self) -> str:
        return f"count={self.count}"

class CounterEnv(Environment[CounterObservation, CounterState]):
    name = "counter"
    version = "1.0.0"
    max_turns = 4

    def setup(self, task: TaskData) -> None:
        super().setup(task)
        self.state = CounterState(
            seed=self.seed,
            target=int(task.expected if task.expected is not None else 2),
        )

    def observe(self) -> CounterObservation:
        return CounterObservation(count=self.state.count)

    def done(self) -> bool:
        return self.state.count >= self.state.target

    def snapshot(self) -> dict:
        return {"count": self.state.count}

    @action
    def increment(self, by: int = 1) -> int:
        """Increment the counter."""
        self.state.count += by
        return self.state.count
```

`snapshot` is not a general serializer. Include only fields approved for trace persistence; omit credentials, hidden labels, and unnecessary simulator state.

## Custom scalar and text actions

`Environment.step()` is final and framework-owned so every turn receives the same lifecycle checks, policy-message handling, `Turn` record, and observation update. Action authors do not override action handling: the base `apply_action()` normalizes and dispatches their `@action` calls.

Override `apply_action()` when the policy emits another action type. The hook receives the raw action and returns trace-safe turn data:

```python
from plural import ActionResult
from plural.tracing import ParsedAction

class RatingEnv(Environment[RatingObservation, RatingState]):
    def apply_action(self, action, *, runtime, response=None):
        self.state.rating = int(action)
        return ActionResult(
            parsed_actions=[
                ParsedAction(name="rate", arguments={"value": self.state.rating})
            ],
            reward_events=[],
            stop_reason=None,
            info={"accepted": True},
        )
```

For a multi-turn text workflow, parse or represent the response in `parsed_actions` and return `stop_reason=None`; the base text behavior uses `policy_stop`. `step` records the `ActionResult` and calls `finish_turn()` once. Normal author hooks should not call `record_decision()` or `finish_turn()` directly; those methods remain available for advanced manual integrations.

## Tasks and hidden expected values

```python
task = TaskData(
    task_id="count-to-two",
    input="Reach the target count.",
    expected=2,
    metadata={"seed": 7},
)

@env.scorer
def reached_expected(rollout) -> float:
    return float(rollout.env.state.count == rollout.task.expected)
```

`expected` is evaluator-only data for scorers. It participates in a `TaskDataset` content hash, but is never sent to the policy and is never copied into episode trace metadata. The trace-safe task payload contains only `task_id`, `input`, and `metadata`.

## Run with a scripted policy

`ScriptedPolicy` is useful for deterministic tests and examples:

```python
from plural import ScriptedPolicy
from plural.tracing import ParsedAction

policy = ScriptedPolicy([
    ParsedAction(name="increment", arguments={"by": 1}),
    ParsedAction(name="increment", arguments={"by": 1}),
])
rollout = CounterEnv().run_episode(task, policy, model="scripted")
assert rollout.trace.stop_reason == "terminated"
```

## Run with a custom policy

A custom synchronous policy receives the environment's exact `ChatRequest` and episode lineage:

```python
class IncrementPolicy:
    def act(self, request, *, trace_context=None):
        return ParsedAction(name="increment", arguments={"by": 1})

rollout = CounterEnv().run_episode(
    task,
    IncrementPolicy(),
    model="increment-policy",
)
```

For Plural-backed model calls, use the built-in convenience:

```python
rollout = CounterEnv().rollout(
    task,
    client,
    model="openai/gpt-4o-mini",
)
```

This writes one episode trace by default. Set `record_llm_traces=True` only when you also want linked per-call child traces.

## Verify deterministic replay

Replay invokes no policy or model. Use a fresh environment:

```python
from plural.environments import verify_replay

result = verify_replay(CounterEnv(), rollout.trace, task=task)
assert result.ok, result.mismatches
```

Pass `task=` whenever replay setup or scoring requires hidden `expected` data. If the trace's safe task payload is sufficient, it can be reconstructed automatically. Fingerprint verification is enabled by default.

Replay rejects redacted traces because their task input, observations, state, or action text may be incomplete.

## Manual client loop

Prefer `run_episode` or `rollout`; they preserve policy inputs, lineage, stops, and one-trace persistence. If you need a manual loop, disable the standalone `client.chat` trace so `close_episode(client=client)` does not create duplicate top-level records:

```python
from plural.types import ChatRequest

obs, info = env.reset(task, model=model)
while True:
    request = ChatRequest(model=model, messages=env.messages(), tools=env.tool_defs)
    response = client.chat(
        model=model,
        messages=request.messages,
        tools=request.tools,
        write_trace=False,
    )
    obs, reward, terminated, truncated, info = env.step(
        response,
        request=request,
        response=response,
    )
    if terminated or truncated or info["stop_reason"] == "policy_stop":
        break
rollout = env.close_episode(client=client)
```

If a custom `Policy.act` calls `client.chat`, pass through its `trace_context`. Use `write_trace=False` for the one-episode-trace default, or opt in to `write_trace=True` to persist a correctly linked child LLM trace.

## Examples

Run the library and Wordle examples from the repository root:

```bash
uv run python examples/environment/library/run.py
uv run python examples/environment/wordle/run.py --secret crane
```

- [Library environment](https://github.com/lastlabs-ai/plural/tree/main/examples/environment/library)
- [Wordle environment](https://github.com/lastlabs-ai/plural/tree/main/examples/environment/wordle)

## Create the environment on Plural

Once the environment exists in code, sync it to the hosted project:

```python
client.create(env)
client.update(env)
```

`create` fails if the slug already exists. `update` uploads a new revision
when the fingerprint changed. Agents are created with
`client.agents.templates.create(name=..., model=..., environment_id=env.slug)`.
See [Create and update hosted objects](push-to-plural.md).

## Version and fingerprint

Bump `version` when the public environment contract changes. The fingerprint covers `max_turns`, action schemas, callable implementation bodies/configured state, scorer weights, author hooks, and `fingerprint_payload()`, so replay and benchmark reports can detect many forms of execution-contract drift.

```python
class CounterEnv(Environment[CounterObservation, CounterState]):
    def __init__(self, *, ruleset: str, **kwargs):
        self.ruleset = ruleset
        super().__init__(**kwargs)

    def fingerprint_payload(self):
        return {"ruleset": self.ruleset}
```

Include stable ids or versions for behavior-affecting constructor and external configuration. Never include API keys, credentials, tokens, or other secrets. A matching fingerprint is a compatibility signal, not a guarantee that mutable external services will return identical results.

## Benchmark construction

The default `spawn()` works for environments reconstructible from the standard `Environment` constructor and safely copied/rebound registrations. If your subclass requires constructor arguments, or a dynamic tool/scorer/task closure captures mutable environment state, override `spawn()` or pass a fresh `environment_factory` to `Benchmark`. Use `runtime_factory` when each benchmark job needs its own synchronous sandbox, remote, or custom runtime.
