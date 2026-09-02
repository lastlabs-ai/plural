from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from plural import Client, Environment
from plural.benchmarks.runner import Benchmark, Report
from plural.errors import ConflictError, InvalidRequestError
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
