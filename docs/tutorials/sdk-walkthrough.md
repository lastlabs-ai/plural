# Build and evaluate a support environment

You will build a read-only order lookup tool, test it without a model, compare
models, and save a report. Start in the project folder from
[setup](../getting-started/setup.md). The first two steps are offline; step 3
requires model credentials and makes paid calls.

## 1. Define the world and its tasks

Save the following as `support.py`:

```python
from plural import Environment, TaskData, TaskDataset

ORDERS = {"A100": "shipped", "A200": "processing", "A300": "cancelled"}


def make_environment(*, scored=True):
    env = Environment(
        name="order-support",
        version="0.1.0",
        max_turns=4,
        system_prompt=(
            "Look up the requested order using lookup_order. "
            "Reply with only its status: shipped, processing, cancelled, or unknown."
        ),
    )

    @env.action
    def lookup_order(order_id: str) -> dict:
        """Return an order's status, or unknown if it does not exist."""
        return {"order_id": order_id, "status": ORDERS.get(order_id, "unknown")}

    def correct_status(rollout) -> float:
        answer = rollout.response.text if rollout.response else ""
        return float((answer or "").strip().lower() == rollout.task.expected)

    if scored:
        env.scorer(correct_status)
    return env


def make_tasks():
    return TaskDataset(
        name="order-support-smoke",
        version="1.0.0",
        tasks=[
            TaskData(task_id="shipped", input="Where is A100?", expected="shipped"),
            TaskData(task_id="processing", input="Where is A200?", expected="processing"),
            TaskData(task_id="cancelled", input="Where is A300?", expected="cancelled"),
            TaskData(task_id="missing", input="Where is A999?", expected="unknown"),
        ],
    )
```

`@env.action` derives the model-facing action schema from the function signature
and docstring. The function owns the implementation. There is no write action in
this example. Its read-only behavior comes from the implementation; this
in-process environment is not a security sandbox.

`expected` is used by the scorer and is not copied into policy requests.
The scorer checks the final answer, not whether the lookup was performed. If
using the action is itself a requirement, add a separate check over the recorded
turns. An exact-match scorer is useful for this constrained output; open-ended
answers need a task-appropriate verifier.

## 2. Check the wiring without spending tokens

Save `check_support.py`:

```python
from plural import ChatResponse, ScriptedPolicy
from plural.tracing import ParsedAction
from support import make_environment, make_tasks

policy = ScriptedPolicy([
    ParsedAction(name="lookup_order", arguments={"order_id": "A100"}),
    ChatResponse.model_validate({
        "id": "offline", "model": "scripted",
        "choices": [{"message": {"role": "assistant", "content": "shipped"}}],
    }),
])
rollout = make_environment().run_episode(make_tasks().tasks[0], policy, model="scripted")
assert rollout.trace.outcome.reward == 1.0
assert len(rollout.trace.turns()) == 2
print("Action and scorer work; score:", rollout.trace.outcome.reward)
```

```bash
python check_support.py
```

This exercises an actual native action and final answer. A scripted policy
returns exactly the supplied actions; it is a deterministic test of your
environment.

## 3. Run one task with a model

Save `run_support.py`:

```python
from plural import Client
from support import make_environment, make_tasks

with Client(capture_content=True) as client:
    rollout = make_environment().rollout(
        make_tasks().tasks[0], client, model="openai/gpt-4o-mini",
    )
    print("Answer:", rollout.response.text if rollout.response else None)
    print("Score:", rollout.trace.outcome.reward)
    print("Stop:", rollout.trace.stop_reason)
    print("Trace:", rollout.trace.trace_id)
```

```bash
python run_support.py
```

Plural sends the instructions and native action definitions to the model,
dispatches requested actions, and scores the completed episode. One episode
trace is written to `.plural/traces.jsonl`. A missing final response,
truncation, or score of zero is a reason to inspect that trace, not assume the
test was solved.

## 4. Evaluate a second model

Save `compare_support.py`:

```python
from pathlib import Path
from plural import Benchmark, Client
from support import make_environment, make_tasks

if __name__ == "__main__":
    tasks = make_tasks()
    tasks.save("data/support-tasks.jsonl")
    with Client(capture_content=True) as client:
        benchmark = Benchmark(
            make_environment(),
            models=["openai/gpt-4o-mini", "anthropic/claude-sonnet-4"],
            client=client,
            name="order-support-smoke",
            repeats=2,
            concurrency=2,
            environment_factory=make_environment,
        )
        report = benchmark.run(dataset=tasks)
        Path("report.md").write_text(report.to_markdown(), encoding="utf-8")
        Path("report.json").write_text(report.to_json(), encoding="utf-8")
        print(report.to_markdown())
```

```bash
python compare_support.py
```

This performs 16 episodes: two models × four tasks × two repeats. Each episode
may make several model calls. Choose models enabled for your gateway or BYOK
providers. A fresh environment is created per case; the explicit factory makes
that reconstruction easy to see.

Open `report.md`. Compare reward alongside failures, cost, and latency. Inspect
`report.cases` when a model fails. A higher average reward on four synthetic
tasks is not evidence of general production quality. Expand the task set to
cover your real cases before drawing conclusions.

The saved task file has a `.manifest.json` companion. Keep both: loading checks
integrity, including hidden answers and task order.

## 5. Reuse the result and catch regressions

After saving a trusted earlier report as `baseline.json`, load both reports:

```python
from pathlib import Path
from plural import Report

report = Report.model_validate_json(Path("report.json").read_text())
baseline = Report.model_validate_json(Path("baseline.json").read_text())
comparison = report.compare(baseline, tolerance=0.02)
if comparison["regressions"]:
    raise SystemExit(f"Reward regression: {comparison['regressions']}")
```

Compatibility checks protect against accidentally comparing different tasks or
environments. See [benchmark models](../guides/benchmark-models.md) for paired
win rates, policy comparisons, factories, and uncertainty.

## 6. Use the environment for a new request

Evaluation labels are optional when doing actual work:

```python
from plural import Client, TaskData
from support import make_environment

with Client() as client:
    result = make_environment(scored=False).rollout(
        TaskData(task_id="live-question", input="Where is A200?"),
        client,
        model="openai/gpt-4o-mini",
    )
    print(result.response.text if result.response else "No final answer")
```

This configuration keeps the same lookup action and instructions but omits the
exact-answer scorer, so the result has no benchmark quality reward. A missing
score does not establish success; use human review or a suitable operational
check when needed. The local data remains synthetic; connecting a real order
service requires implementing that connection in the action.

## Next

[Publish the environment and report to Plural Intel](../guides/push-to-plural.md),
or [add state, observations, custom actions, and replay](../guides/write-environment.md).
