# Add tools and verification to a package

Continue from the [CLI walkthrough](cli-walkthrough.md). This example adds a
read-only command and a verifier that checks the final answer. It uses synthetic
public data and requires Docker for verification. It makes model calls when run.

## 1. Implement a command

Save `environment/lookup_order.py`:

```python
import json
import sys

arguments = json.load(sys.stdin)
orders = {"A100": "shipped", "A200": "processing"}
print(json.dumps({"status": orders.get(arguments["order_id"], "unknown")}))
```

The harness passes a JSON object on stdin. Your program writes its result on
stdout. Validate inputs and enforce service permissions in the implementation
when replacing this example with a real service.

## 2. Declare the tool and instructions

In `environment/environment.yaml`, replace the `instructions` and `commands`
values, leaving the other fields intact:

```yaml
instructions: >-
  Use lookup_order to find the order status. Reply with only the status word.
commands:
  - name: lookup_order
    description: Look up the status of an order.
    command: [python, lookup_order.py]
    parameters:
      type: object
      properties:
        order_id: {type: string}
      required: [order_id]
      additionalProperties: false
    timeout_seconds: 10
```

Change the tasks file to a single task for this verifier:

```json
{"task_id":"order-a100","input":"What is the status of A100?"}
```

In `harness/harness.yaml`, change `manifest.command` to
`[python, harness.py, tool-loop.v1]` and `manifest.capabilities` to
`[chat, tools, trajectory]`. `chat.v1` does not expose tools; `tool-loop.v1`
uses the environment's declarations and dispatches only named commands.
`code-task.v1` uses the same bounded command mechanism; it does not invent a
Python or shell tool for you.

## 3. Add an isolated final-answer verifier

Add this top-level `verifier` field to `environment/environment.yaml`:

```yaml
verifier:
  command:
    - python
    - -c
    - |
      import json
      from pathlib import Path
      rows = [json.loads(line) for line in Path("artifacts/trajectory.jsonl").read_text().splitlines()]
      messages = [row["message"] for row in rows if "message" in row]
      answer = (messages[-1].get("content") or "").strip().lower() if messages else ""
      reward = float(answer == "shipped")
      Path("verifier-result.json").write_text(json.dumps({
          "reward": reward,
          "scores": {"correct_status": reward},
          "evidence": ["Observed final answer: " + answer],
      }))
  required_artifacts: [trajectory.jsonl]
  result_path: verifier-result.json
  timeout_seconds: 30
```

This check intentionally uses a public, fixed answer for one demonstration
task. It verifies the final answer, not that the lookup was performed. A
production verifier should check evidence that actually establishes the task's
success, including authoritative state where needed. Harness-authored
trajectories are claims, not independent proof.

Plural starts the verifier separately with networking disabled and provides
declared artifacts beneath `artifacts/`. The built-in harness already declares
`trajectory.jsonl` as an artifact. An ordinary output file is not automatically
passed as verifier evidence; declare every needed artifact in the harness.

For private labels, the verifier receives `.plural/verifier-input.json` with
`task`, `expected`, `verifier_input`, and artifact paths. Never put private
labels or verifier secrets in the source bundle/image visible to the harness.
A task file inside a staged environment source directory is readable to a
harness with filesystem access even if the protocol excludes its `expected`
field. Keep secret evaluator data outside that source and supply it through the
execution specification. See [security](../operations/security.md).

## 4. Refresh pins and run

The environment and harness have both changed. Regenerate their references in
this order (these commands replace the existing benchmark and agent files):

```bash
plural harness validate harness
plural harness add harness --environment environment
plural env validate environment
plural benchmark init benchmark.yaml --name support-smoke --environment environment --force
plural agent init agent.yaml --name candidate --model openai/gpt-4o-mini \
  --environment environment --harness harness --secret PLURAL_API_KEY --force
plural run job.yaml --dry-run
plural runtime doctor docker
plural run job.yaml --runtime docker --unsafe-local
```

Expect one trial. Its reward is `1.0` only if the final answer is exactly
`shipped`; a completed run with reward `0.0` is a valid failed task, whereas a
verifier crash is an execution error. The verifier cannot run on `local`, because
that provider cannot enforce its no-network requirement.

For file-based verifier programs, install the verifier in the runtime image
and use its absolute command path. The verifier sandbox does not automatically
receive the environment source upload used by the harness phase.

## 5. Regrade without calling the model again

```bash
plural job regrade JOB_ID
```

Regrade uses the stored immutable artifacts and locked verifier. It requires
successful stored results for every trial and links the new receipt to the
source receipt. It does not pick up arbitrary changes you just made to a local
verifier file; a changed evaluation definition belongs to a new revision.

Continue with [job operations](../guides/jobs.md) or
[custom harness protocol and packaging](../guides/harnesses.md).
