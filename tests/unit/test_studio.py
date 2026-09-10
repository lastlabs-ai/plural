from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from plural import Client, Environment
from plural.benchmarks.runner import Benchmark, Report
from plural.domain import (
    AgentTemplate,
    EnvironmentManifest,
    HarnessManifest,
    HarnessPackage,
    PackageSource,
)
from plural.errors import ConflictError, InvalidRequestError, PluralError
from plural.studio import studio_base_url
from plural.tracing.schema import Trace


def test_studio_base_url_strips_gateway_prefix() -> None:
    assert studio_base_url("https://api.example.com/v1") == "https://api.example.com/api/v1"
    assert studio_base_url("https://api.example.com/v1/") == "https://api.example.com/api/v1"
    assert studio_base_url("https://api.example.com") == "https://api.example.com/api/v1"


def test_client_reads_project_and_exposes_studio(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PLURAL_PROJECT", "proj_from_env")
    client = Client(
        api_key="plural_test",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    assert client.project == "proj_from_env"
    assert client.environments is client.studio.environments
    assert client.agents is client.studio.agents
    explicit = Client(
        api_key="plural_test",
        base_url="https://api.example.com/v1",
        project="proj_explicit",
        trace_dir=tmp_path,
    )
    assert explicit.project == "proj_explicit"


@respx.mock
def test_studio_sends_project_header_for_account_keys(tmp_path: Path) -> None:
    route = respx.get("https://api.example.com/api/v1/environments").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "env_1"}]})
    )
    client = Client(
        api_key="plural_account",
        base_url="https://api.example.com/v1",
        project="proj_1",
        trace_dir=tmp_path,
    )
    items = client.environments.list()
    assert items[0]["id"] == "env_1"
    assert route.called
    assert route.calls.last.request.headers["x-project-id"] == "proj_1"
    assert route.calls.last.request.headers["authorization"] == "Bearer plural_account"


@respx.mock
def test_environment_create_and_update_use_slug(tmp_path: Path) -> None:
    create_route = respx.post("https://api.example.com/api/v1/environments").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "env_remote",
                "name": "refund-support",
                "slug": "refund-support",
                "version": "0.1.0",
            },
        )
    )
    respx.get("https://api.example.com/api/v1/environments/refund-support").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "env_remote",
                "name": "refund-support",
                "slug": "refund-support",
            },
        )
    )
    respx.patch("https://api.example.com/api/v1/environments/refund-support").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "env_remote",
                "name": "refund-support",
                "slug": "refund-support",
            },
        )
    )
    respx.post("https://api.example.com/api/v1/environments/refund-support/revisions").mock(
        return_value=httpx.Response(
            200,
            json={"id": "rev_1", "version": "0.1.0", "fingerprint": "abc"},
        )
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    env = Environment(
        name="refund-support",
        version="0.1.0",
        system_prompt="Be brief.",
        description="Help with refunds.",
        readme="# Refunds",
    )
    assert env.slug == "refund-support"
    created = client.create(env)
    posted = json.loads(create_route.calls[0].request.content)
    assert posted["description"] == "Help with refunds."
    assert posted["readme_md"] == "# Refunds"
    assert env.remote_id == "env_remote"
    assert created["slug"] == "refund-support"
    updated = client.update(env)
    assert updated["environment_id"] == "env_remote"
    again = env.update(client)
    assert again["environment_id"] == "env_remote"


@respx.mock
def test_environment_create_conflict(tmp_path: Path) -> None:
    respx.post("https://api.example.com/api/v1/environments").mock(
        return_value=httpx.Response(
            409, json={"detail": "A environment with slug 'refund-support' already exists"}
        )
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    env = Environment(name="refund-support")
    with pytest.raises(ConflictError):
        client.create(env)


@respx.mock
def test_environment_push_creates_then_updates_by_slug(tmp_path: Path) -> None:
    respx.get("https://api.example.com/api/v1/environments/refund-support").mock(
        side_effect=[
            httpx.Response(404, json={"detail": "Not found"}),
            httpx.Response(
                200,
                json={"id": "env_remote", "slug": "refund-support", "name": "refund-support"},
            ),
            httpx.Response(
                200,
                json={"id": "env_remote", "slug": "refund-support", "name": "refund-support"},
            ),
        ]
    )
    respx.post("https://api.example.com/api/v1/environments").mock(
        return_value=httpx.Response(
            200,
            json={"id": "env_remote", "slug": "refund-support", "name": "refund-support"},
        )
    )
    respx.post("https://api.example.com/api/v1/environments/refund-support/revisions").mock(
        return_value=httpx.Response(
            200,
            json={"id": "rev_1", "version": "0.1.0", "fingerprint": "abc"},
        )
    )
    respx.patch("https://api.example.com/api/v1/environments/refund-support").mock(
        return_value=httpx.Response(
            200,
            json={"id": "env_remote", "slug": "refund-support", "name": "refund-support"},
        )
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    env = Environment(name="refund-support", version="0.1.0", system_prompt="Be brief.")
    pushed = client.push(env)
    assert env.remote_id == "env_remote"
    assert pushed["environment_id"] == "env_remote"
    again = env.push(client)
    assert again["environment_id"] == "env_remote"


@respx.mock
def test_client_push_trace_and_report(tmp_path: Path) -> None:
    respx.post("https://api.example.com/api/v1/traces").mock(
        return_value=httpx.Response(200, json={"id": "tr_1", "trace_id": "abc"})
    )
    respx.get("https://api.example.com/api/v1/benchmarks/refund-support").mock(
        return_value=httpx.Response(404, json={"detail": "Not found"})
    )
    respx.post("https://api.example.com/api/v1/benchmarks").mock(
        return_value=httpx.Response(200, json={"id": "bm_1", "name": "refund-support"})
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    stored = client.push(Trace(trace_id="abc", trace_kind="episode"))
    assert stored["id"] == "tr_1"
    stored_report = client.push(Report(environment="refund-support", environment_version="0.1.0"))
    assert stored_report["id"] == "bm_1"


def test_client_push_rejects_unrun_benchmark_and_agents(tmp_path: Path) -> None:
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    bench = Benchmark(
        Environment(name="x"),
        models=["openai/gpt-4o-mini"],
        client=client,
    )
    with pytest.raises(InvalidRequestError, match="run the benchmark"):
        client.create(bench)
    with pytest.raises(InvalidRequestError, match="agents"):
        client.create(object())


@respx.mock
def test_agent_invoke_posts_to_gateway(tmp_path: Path) -> None:
    respx.post("https://api.example.com/v1/agents/ag_1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chat_1",
                "model": "openai/gpt-5.6-luna",
                "choices": [{"message": {"role": "assistant", "content": "done"}}],
            },
        )
    )
    client = Client(
        api_key="plural_account",
        base_url="https://api.example.com/v1",
        project="proj_1",
        trace_dir=tmp_path,
    )
    response = client.agents.invoke("ag_1", "Refund this ticket")
    assert response.choices[0].message.content == "done"
    request = respx.calls.last.request
    assert request.headers["x-project-id"] == "proj_1"
    assert b"Refund this ticket" in request.content


@respx.mock
def test_control_plane_clients_register_batch_finalize_and_sanitize(
    tmp_path: Path,
) -> None:
    respx.post("https://api.example.com/api/v1/jobs/preflight").mock(
        return_value=httpx.Response(
            200,
            json={
                "valid": True,
                "spec_hash": "sha256:server",
                "environment_revision_id": "env_rev",
                "trial_count": 1,
            },
        )
    )
    create_route = respx.post("https://api.example.com/api/v1/jobs").mock(
        return_value=httpx.Response(
            200,
            json={"id": "job_remote", "status": "registered"},
        )
    )
    respx.get("https://api.example.com/api/v1/jobs/job_remote/trials").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "trial_remote",
                    "trial_key": "trl_remote",
                    "task_id": "t1",
                    "attempt": 1,
                }
            ],
        )
    )
    batch_route = respx.post("https://api.example.com/api/v1/jobs/job_remote/trials/batch").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "trial_key": "trl_remote",
                        "trial_id": "trial_remote",
                        "execution_id": "execution_1",
                        "sequence": 1,
                    }
                ]
            },
        )
    )
    finalize_route = respx.post("https://api.example.com/api/v1/jobs/job_remote/finalize").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "job_remote",
                "status": "finalized",
                "benchmark_run_id": "run_1",
            },
        )
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    preflight = client.jobs.preflight(
        benchmark_revision_id="bench_rev",
        agent_revision_ids=["agent_rev"],
        job_spec={"schema_version": "1"},
    )
    assert preflight["trial_count"] == 1
    created = client.jobs.create(
        benchmark_revision_id="bench_rev",
        agent_revision_ids=["agent_rev"],
        idempotency_key="local-job",
        job_spec={"schema_version": "1"},
    )
    assert created["id"] == "job_remote"
    assert json.loads(create_route.calls.last.request.content)["idempotency_key"] == "local-job"
    assert client.jobs.trials("job_remote")[0]["trial_key"] == "trl_remote"
    client.jobs.batch(
        "job_remote",
        [
            {
                "trial_key": "trl_remote",
                "result": {
                    "status": "succeeded",
                    "receipt": {
                        "trial_id": "local",
                        "trust": "self_reported",
                        "authorization": "Bearer secret",
                    },
                    "reward": 1.0,
                },
            }
        ],
    )
    batch = json.loads(batch_route.calls.last.request.content)
    assert batch["executions"][0]["result"]["receipt"]["trust"] == "self_reported"
    assert batch["executions"][0]["result"]["receipt"]["authorization"] == "[redacted]"
    finalized = client.jobs.finalize("job_remote", Report(environment="demo", models={}))
    assert finalized["benchmark_run_id"] == "run_1"
    assert finalize_route.called


@respx.mock
def test_publish_environment_and_agent_exact_package_identity(
    tmp_path: Path,
) -> None:
    package = EnvironmentManifest(name="World", revision="1.0.0")
    respx.get("https://api.example.com/api/v1/environments/world").mock(
        return_value=httpx.Response(200, json={"id": "env_1", "name": "World"})
    )
    revision_route = respx.post("https://api.example.com/api/v1/environments/env_1/revisions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "env_rev_1",
                "package_content_hash": package.content_hash,
            },
        )
    )
    agent_route = respx.post("https://api.example.com/api/v1/agent-templates").mock(
        return_value=httpx.Response(
            200,
            json={"id": "agent_1", "name": "Agent", "slug": "agent"},
        )
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    published = client.environments.publish_manifest(package)
    assert published["package_content_hash"] == package.content_hash
    sent_environment = json.loads(revision_route.calls.last.request.content)
    assert sent_environment["package_manifest"]["name"] == "World"
    agent = AgentTemplate(
        name="Agent",
        model="test/model",
        environment=package.identity,
    )
    client.agents.create(
        name=agent.name,
        model=agent.model,
        environment_revision_id="env_rev_1",
        harness_revision_id="harness_rev_1",
        routing=agent.routing.model_dump(mode="json"),
        package_spec=agent,
    )
    sent_agent = json.loads(agent_route.calls.last.request.content)
    assert sent_agent["package_spec"]["environment"]["digest"] == package.content_hash
    assert sent_agent["harness_revision_id"] == "harness_rev_1"


@respx.mock
def test_harness_revision_client_uses_v1_contract_without_local_path(
    tmp_path: Path,
) -> None:
    route = respx.post("https://api.example.com/api/v1/harnesses/runner/revisions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "hrev_1",
                "package_id": "harness_1",
                "version": "1.0.0",
                "content_hash": f"sha256:{'b' * 64}",
                "source_digest": f"sha256:{'a' * 64}",
                "manifest": {},
                "source": {},
                "created_at": "2026-09-09T00:00:00Z",
            },
        )
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    package = HarnessPackage(
        manifest=HarnessManifest(
            name="runner",
            version="1.0.0",
            command=("python", "run.py"),
        ),
        source=PackageSource(
            kind="local",
            uri="/Users/dev/private/source",
            digest=f"sha256:{'a' * 64}",
        ),
    )
    created = client.harnesses.create_revision("runner", package)
    assert created["id"] == "hrev_1"
    sent = json.loads(route.calls.last.request.content)
    assert sent["source"]["uri"] == "local"
    assert "/Users/dev" not in route.calls.last.request.content.decode()


@respx.mock
def test_job_upload_results_recovers_by_idempotent_replay(
    tmp_path: Path,
) -> None:
    route = respx.post("https://api.example.com/api/v1/jobs/job_1/trials/batch").mock(
        side_effect=[
            httpx.Response(200, json={"items": []}),
            httpx.Response(503, json={"detail": "temporary"}),
            httpx.Response(200, json={"items": [{"duplicate": True}]}),
            httpx.Response(200, json={"items": []}),
        ]
    )
    client = Client(
        api_key="plural_project",
        base_url="https://api.example.com/v1",
        trace_dir=tmp_path,
    )
    results = [
        {
            "status": "succeeded",
            "receipt": {"trial_id": f"local_{index}"},
            "reward": 1.0,
        }
        for index in range(2)
    ]
    with pytest.raises(PluralError, match="temporary"):
        client.jobs.upload_results(
            "job_1",
            trial_keys=["remote_0", "remote_1"],
            results=results,
            batch_size=1,
        )
    assert (
        client.jobs.upload_results(
            "job_1",
            trial_keys=["remote_0", "remote_1"],
            results=results,
            batch_size=1,
        )
        == 2
    )
    assert route.call_count == 4
