---
route: /docs/start/from-traces
title: Start from traces
order: 22
description: "Turn conversations your agent already had into an Environment, Tasks, and a Benchmark, then run models on the same Tasks to compare."
audience: all
nav: true
nav_group: Start
---

# Start from traces

**You start with** conversations an agent you already run has had.

**You end with** an Environment whose tools answer the way your real tools did, a Task
for each conversation, and a Benchmark you can run any model on.

## What your traces need to look like

Each trace is one conversation, in the OpenAI chat format most agent frameworks
already log. Here a customer asks about an order, and the agent looks it up in the
orders system before answering:

```json
{
  "trace_id": "t-1",
  "messages": [
    {"role": "user", "content": "Where is order 42?"},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_1",
          "type": "function",
          "function": {
            "name": "orders__lookup_order",
            "arguments": "{\"order_id\": \"42\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_1",
      "content": "{\"order_id\": \"42\", \"status\": \"shipped\", \"shipped_on\": \"Monday\"}"
    },
    {"role": "assistant", "content": "Your order shipped on Monday."}
  ]
}
```

Reading it top to bottom:

1. The **user** message is the request. It becomes the Task's instructions.
2. The **assistant** calls a tool. `orders__lookup_order` means the `lookup_order` tool
   on the `orders` system; the part before the two underscores names the system.
3. The **tool** message is what the system returned. Its `tool_call_id` matches the
   call's `id`. This is the answer Plural replays when another model makes the same
   call.
4. The last **assistant** message is the agent's reply.

Only `messages` is required, and a conversation with no tool calls works too. Put
your traces in a JSON array, one per line in a `.jsonl` file, or pretty-printed one
after another; Plural reads all three.

:::details Include your tool definitions
Add `tools`, the list your agent sent the model, and other models see your tools
exactly as your agent did, including tools it never called:

```json
{
  "trace_id": "t-1",
  "messages": ["...as above..."],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "orders__lookup_order",
        "description": "Look up an order by its number.",
        "parameters": {
          "type": "object",
          "properties": {"order_id": {"type": "string"}},
          "required": ["order_id"]
        }
      }
    }
  ]
}
```

From this trace, Plural drafts an App named `orders` that offers one tool:

```text
The Agent sees 1 tool:
  lookup_order  Look up an order by its number.
```
:::

:::details Every field Plural reads
| Field | Required | What it's for |
| --- | --- | --- |
| `messages` | Yes | The conversation, oldest first. The first `user` message becomes the Task's instructions. |
| `trace_id` (or `id`) | No | Names the trace and the Task drafted from it. Default: a name made from the conversation, so the same conversation always gets the same one. |
| `tools` | No | The tools your agent was offered, in OpenAI or Anthropic form. Other models get the same names, descriptions, and parameters. |
| `model` | No | Your agent's model, kept with the trace. |
| `metadata` | No | Any object; it is kept with the trace. |

In `messages`:

- `content` may be a string or a list of parts; Plural reads the `text` parts.
- A tool call's `arguments` may be a JSON string, as OpenAI sends it, or an object.
- A `tool` message's `content` is the tool's result. JSON text is read as JSON.
- `system` messages are kept in the conversation but never become the instructions.
:::

:::details Your agent used several systems
Prefix each tool's name with its system and two underscores, as in
`orders__lookup_order`, `crm__get_record`, and `billing__issue_refund`. Plural drafts
one replay App per system, each answering only its own tools. Tools without a prefix
go to one App named `tools`.
:::

:::details Your traces are in another format
**Plural Traces.** If you record runs with Plural's tracing SDK, pass those Traces, or
a `TraceDataset`, wherever this page uses `conversations.json`.

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

Anthropic tool definitions, with `input_schema`, can go in `tools` as they are.

**Anything else.** Write each conversation as the `messages` list your agent would
have sent an OpenAI-compatible model. That list is all Plural needs.
:::

## How it works

```text
conversations.json
  │
  └─ 1. Draft     tool calls become a recording of your tools; conversations become Tasks
       │
       └─ 2. Run      models work those Tasks; the recording answers their tool calls
```

1. **Draft.** Every tool call, with the result it got, is saved to a recording that
   stands in for your real tools. Conversations become Tasks, and a judge model is
   drafted to score them.
2. **Run.** Models work the Tasks. When one calls a tool, it gets the recorded result.
   The same judge scores every model, so their scores compare.

:::details What Plural learns about your tools
- A tool in a trace's `tools` list is offered with your name, description, and
  parameters, even if your agent never called it.
- A tool your agent called but no `tools` list defines is offered too, with
  parameters inferred from its calls.
- A tool your agent never called has no recorded answers. A model that calls it is
  told so, and the step is marked `off_recording`.
:::

:::details What the recording answers when a model does something new
- Same tool, same arguments as a recorded call: the recorded result.
- Same tool, different arguments: the result of the closest recorded call. The step
  is marked `off_recording`.

Nothing real is called, so runs are safe and repeatable. The limit is the recording:
a model that takes a path your agent never took gets the closest recorded answer, not
the real one. Many `off_recording` steps mean the comparison is approximate there. To
test that behavior, connect the real system, as in
[Start from a system](from-a-system.md).
:::

:::details Hundreds or thousands of traces
Every tool call from every trace goes into the recording, so more traces give models
more real answers.

At most 50 traces become Tasks; change that with `--max-tasks`. Plural first picks
traces that call tools no other picked trace calls, so every tool your agent used is
exercised by some Task where possible, then fills the rest in file order.
:::

The rest of this page does both steps with two example conversations.

## 1. Create a project and add your traces

```bash
plural project init support
cd support
```

Save these two conversations as `conversations.json`:

```json
[
  {
    "trace_id": "t-1",
    "messages": [
      {"role": "user", "content": "Where is order 42?"},
      {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "c1",
            "type": "function",
            "function": {"name": "lookup_order", "arguments": "{\"order_id\": \"42\"}"}
          }
        ]
      },
      {"role": "tool", "tool_call_id": "c1", "content": "Order 42 shipped on Monday."},
      {"role": "assistant", "content": "Your order shipped on Monday."}
    ]
  },
  {
    "trace_id": "t-2",
    "messages": [
      {"role": "user", "content": "Can I get a refund for order 7? It arrived broken."},
      {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "c1",
            "type": "function",
            "function": {"name": "lookup_order", "arguments": "{\"order_id\": \"7\"}"}
          }
        ]
      },
      {"role": "tool", "tool_call_id": "c1", "content": "Order 7 delivered Friday, $40."},
      {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "c2",
            "type": "function",
            "function": {
              "name": "issue_refund",
              "arguments": "{\"order_id\": \"7\", \"amount\": 40}"
            }
          }
        ]
      },
      {"role": "tool", "tool_call_id": "c2", "content": "Refund of $40 issued for order 7."},
      {
        "role": "assistant",
        "content": "I've refunded the full $40 for order 7. Sorry it arrived broken."
      }
    ]
  }
]
```

## 2. Draft the Environment, Tasks, and a Benchmark

```bash
plural env add support --traces conversations.json
```

```text
Created environment support:
  environments/support/apps/tools/recordings.jsonl
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

Review the drafted Tasks' instructions, then run Agents on them with `plural run --benchmark support --model <model>`.
```

**What just happened.** Plural wrote:

- An Environment with one **replay App**, `tools`, whose actions are the tools the
  traces called. It answers each call with the result that was recorded for it.
- One Task per trace, with the trace's first user message as its instructions.
- A model-judge Verifier, `support-judge`.
- A Benchmark, `support`, that holds every Task.

All of them are ordinary project files.

## 3. Review the drafts

Read each `tasks/*/instruction.md` and make sure it says what the user actually wanted;
a first message is not always the whole request. Then sharpen the judge's `criteria` in
`verifiers/support-judge/verifier.yaml` until they describe your policy, for example
"refunds over $50 need a manager". Check the draft with:

```bash
plural benchmark validate support
```

:::details Refuse calls the recording doesn't cover
Add `fallback: error` under `replay:` in `environment.yaml`. A model's call with no
exact recording is then told no recording matches, instead of getting the closest one.
:::

## 4. Run models and compare

```bash
plural run --benchmark support --model openai/gpt-5.6-luna
```

```text
  [1/2] trl_444c014d7bfe1dfe3399aa6e  support-t-1  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/2] trl_fecbf00bd3679d2eebad499d  support-t-2  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
Job job_3a3b71e85e95e020a05801b5 succeeded.
  gpt-5.6-luna: mean score 1.000 over 2 trial(s), 2 succeeded
```

**What just happened.** The model worked both Tasks, calling the recorded tools, and the
judge scored each attempt. Run as many models as you like; `plural job show <job-id>`
lists each Trial's score, and `plural trial show <trial-id>` shows the judge's
evidence.

:::details Put your own agent on the same Benchmark
If your agent's model is served behind an OpenAI-compatible API, run it as an Agent
with its own `endpoint`, and it works the same Tasks as every other model; see
[Use your own endpoint](../project/agents.md#use-your-own-endpoint).
:::

## 5. Bring newer traces

When your agent changes, such as gaining new tools, run the same command with the new
traces:

```bash
plural env add support --traces newer.json
```

```text
Updated environment support:
  App tools: 1 new action(s): reship_order; 1 new recorded call(s).
  Drafted 1 new Task(s) and added them to benchmark support.
  environments/support/apps/tools/recordings.jsonl
  environments/support/apps/tools/tools.json
  environments/support/environment.yaml
  tasks/support-t-3/task.yaml
  tasks/support-t-3/instruction.md
  benchmarks/support/benchmark.yaml

App tools (replay, replayed) offers:
  lookup_order
  issue_refund
  reship_order
```

**What just happened.** The Environment picked up what the new traces show: a new
tool, `reship_order`, and its recorded call. The new trace became a Task in the same
Benchmark. Your edited Tasks and judge were left as they were.

:::details Exactly what an update changes
- A trace already imported, by `trace_id`, is skipped.
- New calls are added to the recording. A tool in the new traces' `tools` lists is
  added, and a tool defined again replaces the old description and parameters.
- A system seen for the first time, such as a new `billing__` prefix, becomes a new
  replay App.
- An App you replaced with a real connection is left alone; the output says which
  calls were not added.
- New Tasks are drafted only from new traces, up to `--max-tasks`, preferring traces
  that call tools no existing Task covers.
:::

## Where you are now

You have a Benchmark, `support`, that you can rerun on any model with
`plural run --benchmark support --model <model>`, or repeat exactly with
`plural job rerun <job-id>`. The other two paths end in the same place.

Next:

- Replace the judge with a deterministic Verifier where a rule can decide; see
  [Verifiers](../project/verifiers.md).
- Swap a replay App for the real system when recorded answers aren't enough; see
  [Start from a system](from-a-system.md).
- To train on these Trials, see [Training and RL](../running/training.md).
