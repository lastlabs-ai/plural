from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plural import Resource, Runtime, RuntimeVariable, Secret
from plural.environments.definition import EnvironmentDefinition
from plural.execution.engine import Trial
from plural.execution.inputs import resource_uploads, runtime_values
from plural.harness.native_runner import _action_environment


def inline(path="policy.md", content="shared"):
    return Resource(kind="file", name=path, path=path, delivery="inline", content=content)


def test_scopes_are_isolated_and_manifest_contains_actual_hashes():
    uploads = resource_uploads((inline(),), (inline(content="case"),), None, {})
    files = {item.path: item.data for item in uploads}
    assert files["shared/policy.md"] == b"shared"
    assert files["task/policy.md"] == b"case"
    manifest = json.loads(files["manifest.json"])
    assert manifest["schema_version"] == 1
    assert manifest["resources"][1]["digest"] == "sha256:" + hashlib.sha256(b"case").hexdigest()
    next_run = resource_uploads((inline(),), (), None, {})
    assert "task/policy.md" not in {item.path for item in next_run}


@pytest.mark.parametrize("path", ["../data", "/etc/passwd", "a/../b", "a//b", "a/", "a\\b"])
def test_unsafe_resource_paths_rejected(path):
    with pytest.raises(ValidationError, match="safe relative"):
        inline(path)


def test_file_directory_collisions_are_rejected():
    with pytest.raises(ValueError, match="Conflicting resource"):
        resource_uploads((inline("data"), inline("data/item")), (), None, {})


def test_source_cannot_escape_package(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "private").write_text("secret")
    (source / "escape").symlink_to(tmp_path / "private")
    item = Resource(kind="file", name="escape", path="escape", delivery="source")
    with pytest.raises(ValueError, match="inside Environment source"):
        resource_uploads((item,), (), source, {})


def test_resolver_requires_matching_bytes():
    item = Resource(
        kind="data",
        name="ticket",
        path="ticket.json",
        delivery="resolver",
        resolver="tickets",
        uri="tickets://1",
        digest="sha256:" + hashlib.sha256(b"{}").hexdigest(),
        config={"ticket_id": 1},
    )
    with pytest.raises(ValueError, match="needs resolver"):
        resource_uploads((), (item,), None, {})
    with pytest.raises(ValueError, match="expected digest"):
        resource_uploads((), (item,), None, {"tickets": lambda resource: b"changed"})

    def resolve(resource):
        assert resource.config == {"ticket_id": 1}
        return b"{}"

    assert resource_uploads((), (item,), None, {"tickets": resolve})[0].data == b"{}"


def test_launch_values_are_scoped_and_validated_without_disclosing_values():
    env = EnvironmentDefinition(
        name="support",
        runtime=Runtime.docker(
            variables=[
                RuntimeVariable(name="SUPPORT_TOKEN", secret=True),
                RuntimeVariable(name="SUPPORT_URL", format="url"),
            ]
        ),
        secrets=[Secret(name="JUDGE_TOKEN", target="verifier")],
    )
    supplied = {
        "SUPPORT_TOKEN": "private",
        "SUPPORT_URL": "https://example.com",
        "JUDGE_TOKEN": "judge",
        "UNRELATED": "hidden",
    }
    values, secrets = runtime_values(env, supplied)
    assert values == {"SUPPORT_TOKEN": "private", "SUPPORT_URL": "https://example.com"}
    assert secrets == {"SUPPORT_TOKEN": "private"}
    assert runtime_values(env, supplied, target="verifier")[0] == {"JUDGE_TOKEN": "judge"}
    assert "private" not in env.model_dump_json()
    with pytest.raises(ValueError, match="Missing required runtime variable: SUPPORT_TOKEN"):
        runtime_values(env, {})
    with pytest.raises(ValueError, match="SUPPORT_URL must contain url") as caught:
        runtime_values(env, {**supplied, "SUPPORT_URL": "sensitive-invalid-value"})
    assert "sensitive-invalid-value" not in str(caught.value)


def test_reserved_variables_and_saved_values_rejected():
    for name in ("PATH", "PYTHONPATH", "PLURAL_GATEWAY_URL", "DYLD_INSERT_LIBRARIES"):
        with pytest.raises(ValidationError):
            RuntimeVariable(name=name)
    with pytest.raises(ValidationError):
        RuntimeVariable(name="TOKEN", value="do-not-store")


def test_action_environment_has_only_declared_inputs(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPPORT_TOKEN", "private")
    monkeypatch.setenv("OTHER_TOKEN", "hidden")
    monkeypatch.setenv("PLURAL_SANDBOX_ROOT", str(tmp_path))
    values = _action_environment({"variable_names": ["SUPPORT_TOKEN"]})
    assert values["SUPPORT_TOKEN"] == "private"
    assert "OTHER_TOKEN" not in values
    assert values["PLURAL_RESOURCES_DIR"] == str(tmp_path / "workspace/resources")


def test_trial_stages_resources_and_initial_state_without_source():
    staged = {}

    class Provider:
        async def upload_files(self, handle, files, *, root):
            staged[root] = {item.path: item.data for item in files}

    task = SimpleNamespace(
        environment=EnvironmentDefinition(
            name="test",
            resources=(inline(),),
            state_schema={"properties": {"seed": {"type": "integer"}}},
        ),
        resources=(inline("ticket.txt", "case"),),
        state={"seed": 42},
        task_id="case",
    )
    asyncio.run(
        Trial._stage_environment(
            SimpleNamespace(task=task, resource_resolvers={}), Provider(), None
        )
    )
    assert staged["/workspace/resources"]["task/ticket.txt"] == b"case"
    assert json.loads(staged["/workspace/environment"]["state.json"]) == {"seed": 42}


def test_explicit_empty_job_environment_does_not_inherit_values(monkeypatch):
    from plural import Job

    monkeypatch.setenv("SUPPORT_TOKEN", "private-host-value")
    job = object.__new__(Job)
    job._runner_options = {"environ": {}, "provider": object()}
    assert job._credential_environ() == {}
