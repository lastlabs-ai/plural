from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from plural import Agent, Client, Environment, Runtime, Task
from plural.agents import AgentBinding, AgentDefinition
from plural.environments.definition import EnvironmentDefinition
from plural.jobs import BenchmarkJobSource, JobSpec
from plural.studio import studio_base_url
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import DeterministicVerifier, WeightedVerifier

BASE = "https://api.example.com/api/v1"


def _client(tmp_path: Path) -> Client:
    return Client(
        api_key="plural_test",
        base_url="https://api.example.com/v1",
        project="project_1",
        trace_dir=tmp_path,
    )


def test_studio_base_url() -> None:
    assert studio_base_url("https://api.example.com/v1") == BASE
    assert studio_base_url("https://api.example.com") == BASE


@respx.mock
def test_stamp_harness_posts_compatible_evidence(tmp_path: Path) -> None:
    route = respx.post(f"{BASE}/environments/env_1/revisions/env_rev_1/harness-evidence").mock(
        return_value=httpx.Response(200, json={"id": "stamp_1", "compatible": True})
    )

    result = _client(tmp_path).environments.stamp_harness(
        environment_id="env_1",
        revision_id="env_rev_1",
        harness_revision_id="harness_rev_1",
        evidence={"kind": "context_truncation"},
    )

    assert result["id"] == "stamp_1"
    assert json.loads(route.calls.last.request.content) == {
        "harness_revision_id": "harness_rev_1",
        "compatible": True,
        "evidence": {"kind": "context_truncation"},
    }


@respx.mock
def test_upload_trace_tito_uses_canonical_binary_route(tmp_path: Path) -> None:
    route = respx.post(f"{BASE}/traces/trace%2Fid/artifacts/tito").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "stored_trace_1",
                "tito_metadata": {"digest": "sha256:test"},
            },
        )
    )
    raw = b'{"schema_version":"1"}\n'

    result = _client(tmp_path).traces.upload_tito("trace/id", raw)

    assert result["id"] == "stored_trace_1"
    assert route.calls.last.request.content == raw
    assert route.calls.last.request.headers["content-type"] == (
        "application/x-ndjson; profile=tito-v1"
    )
    assert route.calls.last.request.headers["x-project-id"] == "project_1"
    assert route.calls.last.request.headers["authorization"] == "Bearer plural_test"


@respx.mock
def test_push_environment_parent_and_revision(tmp_path: Path) -> None:
    respx.get(f"{BASE}/environments/world").mock(
        return_value=httpx.Response(404, json={"detail": "Not found"})
    )
    parent = respx.post(f"{BASE}/environments").mock(
        return_value=httpx.Response(200, json={"id": "env_1", "slug": "world", "name": "World"})
    )
    revision = respx.post(f"{BASE}/environments/env_1/revisions").mock(
        return_value=httpx.Response(200, json={"id": "env_rev_1"})
    )
    result = _client(tmp_path).environments.push(
        EnvironmentDefinition(name="World", overview="Runtime world")
    )
    assert result["id"] == "env_rev_1"
    assert json.loads(parent.calls.last.request.content)["slug"] == "world"
    payload = json.loads(revision.calls.last.request.content)
    assert payload["overview"] == "Runtime world"
    assert "instructions" not in payload
    assert "tasks" not in payload


@respx.mock
def test_push_task_and_agent_revision_references(tmp_path: Path) -> None:
    client = _client(tmp_path)
    task = Task(
        name="case-1",
        instructions="Solve it.",
        environment=Environment(name="World", runtime=Runtime.docker()),
        verifiers=[DeterministicVerifier(name="correct", check="python verify.py")],
    )
    for collection, slug, parent_id in (
        ("tasks", "case-1", "task_1"),
        ("agents", "candidate", "agent_1"),
    ):
        respx.get(f"{BASE}/{collection}/{slug}").mock(
            return_value=httpx.Response(200, json={"id": parent_id, "slug": slug})
        )
    task_route = respx.post(f"{BASE}/tasks/task_1/revisions").mock(
        return_value=httpx.Response(200, json={"id": "task_rev_1"})
    )
    agent_route = respx.post(f"{BASE}/agents/agent_1/revisions").mock(
        return_value=httpx.Response(200, json={"id": "agent_rev_1"})
    )
    client.tasks.push(
        task,
        environment_revision_id="env_rev_1",
        verifier_revision_ids=["verifier_rev_1"],
    )
    client.agents.push(Agent(name="candidate", model="openai/gpt-5.6-luna"))
    task_payload = json.loads(task_route.calls.last.request.content)
    assert task_payload["environment_revision_id"] == "env_rev_1"
    assert task_payload["verifier_revision_ids"] == ["verifier_rev_1"]
    assert task_payload["instructions"] == "Solve it."
    assert "environment" not in task_payload and "verifiers" not in task_payload
    agent_payload = json.loads(agent_route.calls.last.request.content)
    assert agent_payload["model"] == "openai/gpt-5.6-luna"
    assert "environment" not in agent_payload
    assert all(
        "/agents/" in str(call.request.url)
        for call in respx.calls
        if call.request.method == "POST" and "agent" in str(call.request.url)
    )
    assert not hasattr(client.agents, "publish_revision")


@respx.mock
def test_submit_job_and_transition_cancel(tmp_path: Path) -> None:
    task = TaskDefinition(
        task_id="case-1",
        instructions="Solve it.",
        environment=EnvironmentDefinition(name="World"),
        verifiers=(
            WeightedVerifier(
                verifier=DeterministicVerifier(name="correct", command=("python", "verify.py"))
            ),
        ),
    )
    benchmark = BenchmarkDefinition(name="suite", tasks=(task,))
    spec = JobSpec(
        source=BenchmarkJobSource(benchmark=benchmark),
        agents=(AgentBinding(agent=AgentDefinition(name="candidate", model="test/model")),),
        mode="train",
        attempts=2,
    )
    create = respx.post(f"{BASE}/jobs").mock(return_value=httpx.Response(200, json={"id": "job_1"}))
    transition = respx.post(f"{BASE}/jobs/job_1/transition").mock(
        return_value=httpx.Response(200, json={"id": "job_1", "status": "cancelled"})
    )
    client = _client(tmp_path)
    client.jobs.submit(
        spec,
        source_revision_id="benchmark_rev_1",
        agent_revision_ids=["agent_rev_1"],
        idempotency_key="submit-1",
    )
    client.jobs.cancel("job_1")
    payload = json.loads(create.calls.last.request.content)
    assert payload["source"] == {
        "type": "benchmark",
        "revision_id": "benchmark_rev_1",
    }
    assert payload["agent_revision_ids"] == ["agent_rev_1"]
    assert payload["mode"] == "train"
    assert json.loads(transition.calls.last.request.content) == {"status": "cancelled"}


@respx.mock
def test_watch_events_and_submit_human_review(tmp_path: Path) -> None:
    respx.get(f"{BASE}/jobs/job_1/events").mock(
        return_value=httpx.Response(
            200,
            text=(
                "id: 1\n"
                "event: queued\n"
                'data: {"sequence":1,"kind":"queued"}\n\n'
                "id: 2\n"
                "event: awaiting_review\n"
                'data: {"sequence":2,"kind":"awaiting_review"}\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )
    )
    submission = respx.post(f"{BASE}/reviews/review_1/submissions").mock(
        return_value=httpx.Response(200, json={"id": "submission_1"})
    )
    client = _client(tmp_path)
    assert [event["sequence"] for event in client.jobs.watch("job_1")] == [1, 2]
    client.reviews.submit(
        "review_1",
        scores={"correct": 1},
        feedback="approved",
        idempotency_key="review-submit-1",
    )
    payload = json.loads(submission.calls.last.request.content)
    assert payload["scores"] == {"correct": 1.0}
    assert payload["idempotency_key"] == "review-submit-1"
