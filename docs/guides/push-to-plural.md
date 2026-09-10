# Fetch and update Plural Intel objects

This walkthrough uses the current hosted SDK. Source code calls this integration
`Studio`; these pages call the hosted product **Plural Intel**. You need a
compatible hosted deployment, a Plural API key, and project access from
[setup](../getting-started/setup.md). The SDK sends real reads and writes;
examples labelled create/update are not local previews.

## 1. Find your objects

Save as `list_objects.py` and run with `python list_objects.py`:

```python
from plural import Client

with Client() as client:
    for label, objects in (
        ("Environments", client.environments.list()),
        ("Agents", client.agents.list()),
        ("Benchmarks", client.benchmarks.list()),
    ):
        print(label)
        for item in objects:
            print(item.get("slug") or item.get("id"), item.get("name"))
```

An empty list is valid. A permission or project error is different; check the
selected project before assuming an object is missing. The SDK returns the
server's list response; it does not promise automatic pagination of all objects.

Environment, agent, and benchmark **slugs** are unique within a project.
For example, a name such as “Order Support” normally becomes `order-support`.
Use returned slugs or IDs in subsequent calls; do not guess revision IDs.
Traces and jobs use their own IDs.

## 2. Fetch objects and save a local snapshot

Replace the three slugs below with values returned by your project:

```python
import json
from pathlib import Path
from plural import Client

with Client() as client:
    environment = client.environments.get("order-support")
    agent = client.agents.get("support-assistant")
    benchmark = client.benchmarks.get("order-support-smoke")
    snapshot = {
        "environment": environment,
        "agent": agent.data,
        "benchmark": benchmark,
    }
    Path("intel-objects.json").write_text(
        json.dumps(snapshot, indent=2), encoding="utf-8",
    )
    print("Agent model:", agent.model)
```

The environment and benchmark are dictionaries. The agent is a `RemoteAgent`
handle; `.data` holds the response dictionary. Saving these is a metadata
snapshot, **not an executable package download**. Treat snapshots as project
data: they may contain task inputs or other sensitive content.

There is no `Environment.pull()`, `env.agent()`, or general `plural pull`
command in this release. Getting a hosted environment does not reconstruct
Python tools, provision services, or install dependencies.

## 3. Use a hosted agent

```python
from plural import Client

with Client() as client:
    agent = client.agents.get("support-assistant")
    response = agent.invoke("Where is order A100?")
    print(response.text)
```

This invokes the deployment's agent chat endpoint and may incur model charges.
You can also use `client.agents.invoke("support-assistant", "Where is order A100?")`
or supply a message list. The hosted gateway determines the configured agent's
behavior; this SDK call does not launch the local package runner or upload your
Python tool implementations. A stored agent record alone does not establish
that its invocation endpoint is configured and available.

## 4. Update existing metadata and verify the change

```python
from plural import Client

with Client() as client:
    client.environments.update(
        "order-support", description="Read-only order status support.",
    )
    agent = client.agents.update(
        "support-assistant", description="Answers order-status questions.",
    )
    client.benchmarks.update("order-support-smoke", notes="Reviewed smoke suite.")
    print(client.environments.get("order-support").get("description"))
    print(agent.description)
    print(client.benchmarks.get("order-support-smoke").get("notes"))
```

These methods send PATCH fields accepted by the hosted deployment. Changing
model or environment bindings may create or require new revisions according to
that backend's rules; fetch the result and verify its binding. Do not resend an
entire fetched object as a patch: it can contain read-only fields.

A metadata update is different from publishing changed executable behavior.
For behavior changes, update the source environment/package and publish its
revision as shown below. Existing package pins do not automatically advance.

## 5. Create hosted objects from the Python walkthrough

Complete the [support tutorial](../tutorials/sdk-walkthrough.md) first so that
`support.py` and `report.json` exist. Save this script beside them:

```python
from pathlib import Path
from plural import Client, Report
from support import make_environment

with Client() as client:
    env = make_environment()
    created = client.create(env)
    print("Environment:", env.slug, env.remote_id)

    template = client.agents.templates.create(
        name="support-assistant",
        model="openai/gpt-4o-mini",
        environment_id=env.slug,
        description="Read-only order-status assistant.",
    )
    print("Agent template:", template["slug"])

    report = Report.model_validate_json(Path("report.json").read_text())
    client.create(
        report, name="order-support-smoke", environment_id=env.slug,
    )
```

`create` fails with a conflict when the slug already exists. On later runs use
`client.update(env)` and `client.update(report, name="order-support-smoke", ...)`
for the intended existing objects. For agents use `client.agents.update(...)`.
`client.create(benchmark)` also works after a local `Benchmark.run()` has set
its `.report`; an unrun local benchmark cannot be uploaded through that helper.

The Python environment upload includes instructions, schemas, fingerprints,
tool/scorer metadata, and revision information. It is not deployment of Python
callables. Continue distributing executable source through your normal package
or repository process.

`env.create(client)` and `env.update(client)` are convenience aliases.
`client.push(env)` / `env.push(client)` retain upsert behavior, but explicit
create versus update makes accidental overwrites easier to avoid.

## 6. Keep benchmark run history

To attach another scored run to an existing hosted benchmark:

```python
from pathlib import Path
from plural import Client, Report

report = Report.model_validate_json(Path("report.json").read_text())
with Client() as client:
    client.benchmarks.create_run(
        "order-support-smoke",
        report=report.model_dump(mode="json"),
        environment_id="order-support",
        notes="Second evaluation with the same task set.",
    )
    print(client.benchmarks.list_runs("order-support-smoke"))
```

Use `benchmarks.update` for metadata and `create_run` to explicitly add a run.
You can create a hosted benchmark before results exist with
`client.benchmarks.create(name=..., environment_id=..., description=...,
methodology=..., primary_metric="reward")`. This differs from the local
`client.create(Benchmark(...))` helper, which requires a completed report.

## 7. Publish exact package revisions

For the [CLI package tutorial](../tutorials/cli-walkthrough.md):

```bash
plural env push environment
```

The SDK equivalent is:

```python
from pathlib import Path
from plural import Client
from plural.cli.scaffold import load_environment

package = load_environment(Path("environment"))
with Client() as client:
    revision = client.environments.publish_manifest(package)
    print("Environment revision:", revision["id"])
```

The return value identifies the exact published revision. Metadata publication
does not upload an executable archive or make a local source path portable.
For full agent, benchmark, harness, and job registration, prefer
`plural run job.yaml --sync` or `plural job upload JOB_ID`; the CLI coordinates
the required revision IDs. [Package sync](studio-sync.md) explains the lifecycle.

## 8. Reuse stored package definitions locally (advanced)

Some hosted objects have complete v1 package payloads; older Python/Studio
records do not. Inspect your deployment's returned data first. A complete
`AgentTemplate` stored in `package_spec` can be validated and saved:

```python
from pathlib import Path
from plural import AgentTemplate, Client
from plural.cli.scaffold import write_yaml

with Client() as client:
    remote = client.agents.templates.get("support-assistant")
    payload = remote.get("package_spec")
    if payload is None:
        raise ValueError("This hosted template has no executable package_spec.")
    template = AgentTemplate.model_validate(payload)
    write_yaml(Path("downloaded-agent.yaml"), template)
```

Likewise, when a selected environment revision exposes `package_manifest`,
validate that payload with `EnvironmentManifest.model_validate(...)`. For a
benchmark revision's `package_definition`, use
`BenchmarkDefinition.model_validate(...)`. Do not validate the whole hosted
wrapper as a package. The SDK has explicit benchmark revision reads:

```python
from plural import BenchmarkDefinition, Client

with Client() as client:
    revisions = client.benchmarks.revisions("order-support-smoke")
    if not revisions:
        raise ValueError("No immutable benchmark revisions are available.")
    selected_id = revisions[0]["id"]  # inspect/select intentionally in real use
    revision = client.benchmarks.get_revision("order-support-smoke", selected_id)
    payload = revision.get("package_definition")
    if payload is None:
        raise ValueError("This revision has no v1 package_definition.")
    definition = BenchmarkDefinition.model_validate(payload)
    print(definition.task_ids)
```

There is no dedicated environment-revision get helper in this SDK. Use the
revision data actually returned by your deployment, or obtain the exact
manifest from the environment author; do not assume a response layout.

Before executing restored definitions, obtain the matching environment source,
harness archive/image, dependencies, and credential grants. Local source paths
from another machine are not usable downloads. Match environment and harness
digests, validate task ownership, and run a dry plan. If source bytes change,
create new matching pins instead of changing a digest to bypass validation.
A hosted snapshot alone is insufficient for a reproducible local run.

## 9. Delete only when intended

The explicit methods are `client.environments.delete(slug)`,
`client.agents.delete(slug)`, and `client.benchmarks.delete(slug)`.
They make hosted deletes immediately; referenced objects may be rejected by the
backend. Keep deletion separate from a repeatable create/update script.

## Related data

For hosted harness revision publishing, benchmark revision promotion, job
receipts, and traces, see [advanced hosted workflows](../sdk/hosted-advanced.md).
For exact parameters see the [hosted SDK reference](../reference/api.md#hosted-studio-sdk).
