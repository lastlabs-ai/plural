---
route: /docs/start/from-traces
title: Start from traces
order: 22
description: "Score conversations your agent already had, draft Tasks and a Benchmark from them, and run other models on the same Tasks to compare."
audience: all
nav: true
nav_group: Start
---
# Start from traces

**You start with** conversations an agent you already run has had.

**You end with** a score for each one, a Benchmark made from them, and your agent's
scores next to any other model's on the same Tasks.

## What your traces need to look like

One conversation per line, in the OpenAI chat format most agent frameworks already log:

```json
{"messages": [{"role": "user", "content": "Where is order 42?"}, {"role": "assistant", "content": "It shipped on Monday."}]}
```

That's the whole requirement. If your agent called tools, keep them in the same list:
the assistant's `tool_calls`, each answered by a `tool` message with the same
`tool_call_id`, exactly as OpenAI's API returns them.

:::details Every field Plural reads
| Field | Required | What it's for |
| --- | --- | --- |
| `messages` | Yes | The conversation, oldest first. The first `user` message becomes the Task's instructions. |
| `trace_id` (or `id`) | No | Names the trace and the Task drafted from it. Default: `trace-1`, `trace-2`, and so on. |
| `model` | No | Names your agent in the results, such as `acme/support-bot`. Default: `recorded`. |
| `metadata` | No | Any object; it is kept with the trace. |

In `messages`:

- `content` may be a string or a list of parts; Plural reads the `text` parts.
- A tool call's `arguments` may be a JSON string, as OpenAI sends it, or an object.
- A `tool` message's `content` is the tool's result. JSON text is read as JSON.
- `system` messages are kept in the conversation but never become the instructions.

A `.json` file holding one array of these objects works too.
:::

:::details Your agent used several systems
Prefix each tool's name with its system and two underscores, such as `crm__get_record`
and `billing__issue_refund`. Plural then drafts one replay App per system, `crm` and
`billing`, each answering only its own tools. Tools without a prefix go to one App
named `tools`.
:::

:::details Your traces are in another format
**Plural Traces.** If you record runs with Plural's tracing SDK, pass those Traces, or
a `TraceDataset`, wherever this page uses `conversations.jsonl`.

**Anthropic's Messages format.** Convert it first. A `tool_use` block becomes an
OpenAI tool call, and a `tool_result` block becomes a `tool` message:

```python
import json


def to_openai(messages: list[dict]) -> list[dict]:
    converted = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": message["role"], "content": content})
            continue
        text = "".join(block.get("text", "") for block in content if block["type"] == "text")
        calls = [
            {
                "id": block["id"],
                "type": "function",
                "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
            }
            for block in content
            if block["type"] == "tool_use"
        ]
        results = [block for block in content if block["type"] == "tool_result"]
        for block in results:
            converted.append(
                {"role": "tool", "tool_call_id": block["tool_use_id"], "content": block["content"]}
            )
        if text or calls:
            entry = {"role": message["role"], "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            converted.append(entry)
    return converted
```

**Anything else.** Write each conversation as the `messages` list your agent would
have sent an OpenAI-compatible model. That list is all Plural needs.
:::

## How it works

```text
conversations.jsonl
  │
  ├─ 1. Score    a judge grades each conversation as it happened
  │
  └─ 2. Draft    each conversation becomes a Task; every tool result is recorded
       │
       └─ 3. Compare    other models work those Tasks; the recording answers their tool calls
```

1. **Score.** A judge model reads each conversation and scores it. Nothing is rerun.
2. **Draft.** Each conversation becomes a Task. Every tool call, with the result it
   got, is saved to a recording that stands in for your real tools.
3. **Compare.** Other models work the same Tasks. When one calls a tool, it gets the
   recorded result. The same judge scores everyone.

:::details What the recording answers when a model does something new
- Same tool, same arguments as a recorded call: the recorded result.
- Same tool, different arguments: the result of the closest recorded call. The step
  is marked `off_recording`.

Nothing real is called after step 1, so comparing is safe and repeatable. The limit
is the recording: a model that takes a path your agent never took gets the closest
recorded answer, not the real one. Many `off_recording` steps mean the comparison is
approximate there. To test that behavior, connect the real system, as in
[Start from a system](from-a-system.md).
:::

The rest of this page does all three with two example conversations.

## 1. Create a project and add your traces

```bash
plural project init support
cd support
```

Save these two conversations as `conversations.jsonl`:

```json
{"trace_id": "t-1", "model": "acme/support-bot", "messages": [{"role": "user", "content": "Where is order 42?"}, {"role": "assistant", "content": null, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "lookup_order", "arguments": "{\"order_id\": \"42\"}"}}]}, {"role": "tool", "tool_call_id": "c1", "content": "Order 42 shipped on Monday."}, {"role": "assistant", "content": "Your order shipped on Monday."}]}
{"trace_id": "t-2", "model": "acme/support-bot", "messages": [{"role": "user", "content": "Can I get a refund for order 7? It arrived broken."}, {"role": "assistant", "content": null, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "lookup_order", "arguments": "{\"order_id\": \"7\"}"}}]}, {"role": "tool", "tool_call_id": "c1", "content": "Order 7 delivered Friday, $40."}, {"role": "assistant", "content": null, "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "issue_refund", "arguments": "{\"order_id\": \"7\", \"amount\": 40}"}}]}, {"role": "tool", "tool_call_id": "c2", "content": "Refund of $40 issued for order 7."}, {"role": "assistant", "content": "I've refunded the full $40 for order 7. Sorry it arrived broken."}]}
```

## 2. Score them right away

Before drafting anything, find out how your agent did. Save this as `score_traces.py`:

```python
from plural import AgentVerifier, Client, Job, RubricCriterion

judge = AgentVerifier(
    name="resolved",
    model="openai/gpt-5.6-luna",
    instructions="Judge whether the agent resolved the customer's request.",
    criteria=[
        RubricCriterion(
            name="resolved",
            description="0: not resolved. 1: resolved, with the actions it needed.",
        )
    ],
)
result = Job.from_traces("conversations.jsonl", verifiers=[judge], client=Client()).run()
for trial in result.trials:
    print(trial.receipt.task_pin.name, trial.score, trial.verifier_results[0].evidence[0])
```

```bash
python score_traces.py
```

```text
t-1 1.0 The agent used lookup_order for order 42 and received the status "Order 42 shipped on Monday."
t-2 1.0 The agent looked up order 7 and confirmed its $40 value.
```

**What just happened.** Each conversation was replayed as a Trial: every assistant
message became a model call and every tool result a step, without calling your agent's
model. A model judge, an `AgentVerifier`, read each one and scored it with evidence.
The judge's call goes through the Plural gateway, which is why this step needs you
signed in.

## 3. Draft Tasks and a Benchmark

A score for each trace tells you how your agent did. To compare it with other models,
turn the traces into Tasks they can attempt too:

```bash
plural env from-traces support --traces conversations.jsonl
```

```text
Drafted environment support:
  environments/support/recordings/tools.jsonl
  environments/support/environment.yaml
  environments/support/README.md
  verifiers/support-judge/verifier.yaml
  tasks/support-t-1/task.yaml
  tasks/support-t-1/instruction.md
  tasks/support-t-2/task.yaml
  tasks/support-t-2/instruction.md
  benchmarks/support/benchmark.yaml
  benchmarks/support/README.md

App tools (replay, replayed) offers:
  lookup_order
  issue_refund

Drafted 2 Task(s) and benchmark support. Review the instructions, then score the recorded agent with `plural run --benchmark support --traces <file>`.
```

**What just happened.** Plural wrote:

- An Environment with one **replay App**, `tools`, whose actions are the tools the
  traces called. It answers each call with the result that was recorded for it.
- One Task per trace, with the trace's first user message as its instructions.
- A model-judge Verifier, `support-judge`.
- A Benchmark, `support`, that holds every Task.

All of them are ordinary project files.

## 4. Review the drafts

Read each `tasks/*/instruction.md` and make sure it says what the user actually wanted;
a first message is not always the whole request. Then sharpen the judge's `criteria` in
`verifiers/support-judge/verifier.yaml` until they describe your policy, for example
"refunds over $50 need a manager". Check the draft with:

```bash
plural benchmark validate support
```

**What just happened.** `validate` checked that every Task, the judge, and the replay App
load.

:::details Refuse calls the recording doesn't cover
Add `fallback: error` under `replay:` in `environment.yaml`. A model's call with no
exact recording is then told no recording matches, instead of getting the closest one.
:::

## 5. Score your agent on the Benchmark

```bash
plural run --benchmark support --traces conversations.jsonl
```

```text
  [1/2] trl_d9e151759572131586fa1562  support-t-2  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/2] trl_6c35608c630b0a1e3cd3fa9b  support-t-1  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
Job job_1453507c51bdf816d4b92bbd succeeded.
  support-bot: mean score 1.000 over 2 trial(s), 2 succeeded
```

**What just happened.** Each trace was matched to the Task drafted from it and scored
by that Task's Verifier. The Agent is named after the traces' `model`, here
`support-bot`. This is your baseline.

## 6. Run another model and compare

```bash
plural run --benchmark support --model openai/gpt-5.6-luna
```

```text
  [1/2] trl_444c014d7bfe1dfe3399aa6e  support-t-1  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/2] trl_fecbf00bd3679d2eebad499d  support-t-2  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
Job job_3a3b71e85e95e020a05801b5 succeeded.
  gpt-5.6-luna: mean score 1.000 over 2 trial(s), 2 succeeded
```

**What just happened.** The model worked the same Tasks, calling the same tools, and was
graded by the same Verifier. Its mean score sits next to your agent's. Run as many
models as you like; `plural job show <job-id>` lists each Trial's score, and
`plural trial show <trial-id>` shows the judge's evidence.

## Where you are now

You have a Benchmark, `support`, that you can rerun on any model with
`plural run --benchmark support --model <model>`, or repeat exactly with
`plural job rerun <job-id>`. The other two paths end in the same place.

Next:

- Collect more traces and rerun `plural env from-traces` to grow the Benchmark.
- Replace the judge with a deterministic Verifier where a rule can decide; see
  [Verifiers](../project/verifiers.md).
- The full reference for trace scoring is
  [Score traces you already have](../running/traces.md#score-traces-you-already-have).
- To train on these Trials, see [Training and RL](../running/training.md).
