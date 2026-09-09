# Your first evaluation

In this walkthrough you will define one customer-support task, run a
deterministic policy, and inspect its score. No API key or model call is needed
until the last step. Complete [installation](getting-started/setup.md) first.

## 1. Save a tiny environment

Create `first_eval.py` with:

```python
from plural import ChatResponse, Environment, ScriptedPolicy, TaskData


def make_environment():
    env = Environment(name="support-answer", version="0.1.0")

    @env.scorer
    def correct(rollout):
        return float(rollout.response.text.strip().lower() == rollout.task.expected)

    return env


task = TaskData(
    task_id="order-status",
    input="Reply with only the word shipped.",
    expected="shipped",
)

if __name__ == "__main__":
    policy = ScriptedPolicy([
        ChatResponse.model_validate({
            "id": "offline", "model": "scripted",
            "choices": [{"message": {"role": "assistant", "content": "shipped"}}],
        }),
    ])
    rollout = make_environment().run_episode(task, policy, model="scripted")
    print("Score:", rollout.trace.outcome.reward)
    print("Stopped because:", rollout.trace.stop_reason)
```

## 2. Run it

```bash
python first_eval.py
```

The score should be `1.0`. `policy_stop` means the policy finished with a text
answer. The scorer awarded credit independently; finishing and answering
correctly are different things.

The environment contains the scoring rule. The task contains the input and
hidden expected answer. The policy supplies the response. This smoke test checks
the wiring; it does not measure a model's ability.

## 3. Replace the scripted policy with a model

After [setting your API key](getting-started/setup.md), save `model_eval.py`
next to `first_eval.py`:

```python
from plural import Client
from first_eval import make_environment, task

with Client(capture_content=True) as client:
    rollout = make_environment().rollout(task, client, model="openai/gpt-4o-mini")
    print("Answer:", rollout.response.text)
    print("Score:", rollout.trace.outcome.reward)
    print("Trace:", rollout.trace.trace_id)
```

```bash
python model_eval.py
```

This step makes a paid model call. The trace is saved to `.plural/traces.jsonl`.
`capture_content=True` saves prompt/response content for this synthetic example;
it is off by default.

## Next: make the test useful

A one-question test does not establish quality. Continue with the
[practical SDK walkthrough](tutorials/sdk-walkthrough.md) to add real tools and
multiple tasks, compare models, and save reports. If you want executable
packages and durable jobs, follow the [CLI walkthrough](tutorials/cli-walkthrough.md).
