from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plural import Resource, Runtime, RuntimeVariable, Secret
from plural.apps.definition import AppAction, AppDefinition
from plural.environments.definition import EnvironmentDefinition
from plural.execution.apps import (
    app_secret_values,
    host_files,
    host_inputs,
    missing_app_secrets,
    trial_seed,
)
from plural.execution.engine import TrialRunner
from plural.execution.inputs import resource_uploads, runtime_values
from plural.harness.native_runner import _action_environment


def inline(path="policy.md", content="shared"):
    return Resource(kind="file", name=path, path=path, delivery="inline", content=content)


def test_environment_and_task_resources_are_separate_read_only_volumes():
    uploads = resource_uploads((inline(),), (inline(content="case"),), None, {})
    files = {item.path: item.data for item in uploads}
    assert files["environment-resources/policy.md"] == b"shared"
    assert files["task-resources/policy.md"] == b"case"
    assert {item.mode for item in uploads} == {0o444}
    manifest = json.loads(files["manifest.json"])
    assert manifest["schema_version"] == 2
    assert [item["scope"] for item in manifest["resources"]] == ["environment", "task"]
    assert manifest["resources"][1]["digest"] == "sha256:" + hashlib.sha256(b"case").hexdigest()
    next_run = resource_uploads((inline(),), (), None, {})
    assert "task-resources/policy.md" not in {item.path for item in next_run}


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
    assert "private" not in env.model_dump_json()
    with pytest.raises(ValueError, match="Missing required runtime variable: SUPPORT_TOKEN"):
        runtime_values(env, {})
    with pytest.raises(ValueError, match="SUPPORT_URL must contain url") as caught:
        runtime_values(env, {**supplied, "SUPPORT_URL": "sensitive-invalid-value"})
    assert "sensitive-invalid-value" not in str(caught.value)


def _crm_environment() -> EnvironmentDefinition:
    crm = AppDefinition(
        name="crm",
        kind="mcp",
        actions=(AppAction(name="get_record", description="Read."),),
        secrets=(Secret(name="CRM_TOKEN"), Secret(name="CRM_REGION", required=False)),
        control="live",
    )
    return EnvironmentDefinition(name="desk", apps=(crm,))


def test_app_secrets_are_resolved_by_app_and_named_when_missing():
    env = _crm_environment()
    assert [item.name for item in env.secrets] == ["CRM_TOKEN", "CRM_REGION"]
    assert app_secret_values(env, {"CRM_TOKEN": "t", "OTHER": "x"}) == {"CRM_TOKEN": "t"}
    assert missing_app_secrets(env, {}) == {"crm": ["CRM_TOKEN"]}
    with pytest.raises(ValueError, match="App 'crm' needs CRM_TOKEN") as caught:
        app_secret_values(env, {"CRM_REGION": "eu-private"})
    assert "eu-private" not in str(caught.value)


def test_secret_names_cannot_shadow_runtime_variables():
    with pytest.raises(ValidationError):
        Secret(name="PATH")
    with pytest.raises(ValidationError):
        Secret(name="PLURAL_API_KEY")


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


def gentle(step):
    return 0.0


def test_trial_stages_resources_and_the_app_host_reads_initial_state_by_app():
    from plural import DeterministicVerifier

    staged = {}

    class Provider:
        async def upload_files(self, handle, files, *, root):
            staged[root] = {item.path: item.data for item in files}

    game = AppDefinition(
        name="game",
        kind="python",
        python="game.py:Game",
        actions=(AppAction(name="move", description="Move."),),
        state_schema={"properties": {"seed": {"type": "integer", "x-plural-initial": True}}},
    )
    task = SimpleNamespace(
        environment=EnvironmentDefinition(name="test", resources=(inline(),), apps=(game,)),
        resources=(inline("ticket.txt", "case"),),
        state={"seed": 42},
        task_id="case",
        info={"hint": "visible"},
        metadata={"tier": "gold"},
        verifiers=(SimpleNamespace(verifier=DeterministicVerifier(name="gentle", reward=gentle)),),
    )
    asyncio.run(
        TrialRunner._stage_environment(
            SimpleNamespace(task=task, resource_resolvers={}), Provider(), None
        )
    )
    assert staged["/workspace/resources"]["task-resources/ticket.txt"] == b"case"
    assert "/workspace/environment" not in staged
    files = {item.path: item.data for item in host_files(task)}
    # The hidden initial State is not in the shared file; it goes to the host on stdin.
    assert json.loads(files[".plural/apps/task.json"]) == {
        "task": {"name": "case", "metadata": {"tier": "gold"}},
        "verifiers": [
            {
                "name": "gentle",
                "version": "0.1.0",
                "dir": ".plural/verifiers/0",
                "python": "test_runtime_inputs.py:gentle",
            }
        ],
    }
    assert host_inputs(task, seed=7) == {
        "initial_state": {"game": {"seed": 42}},
        "info": {"hint": "visible"},
        "seed": 7,
    }
    assert b"def gentle(step)" in files[".plural/verifiers/0/test_runtime_inputs.py"]
    assert (
        EnvironmentDefinition.model_validate_json(files[".plural/apps/environment.json"]).identity
        == task.environment.identity
    )


def test_explicit_empty_job_environment_does_not_inherit_values(monkeypatch):
    from plural import Job

    monkeypatch.setenv("SUPPORT_TOKEN", "private-host-value")
    job = object.__new__(Job)
    job._runner_options = {"environ": {}, "provider": object()}
    assert job._credential_environ() == {}


def test_each_attempt_has_its_own_seed_and_every_agent_shares_it():
    assert trial_seed("sha256:task", 1) == trial_seed("sha256:task", 1)
    assert trial_seed("sha256:task", 1) != trial_seed("sha256:task", 2)
    assert trial_seed("sha256:task", 1) != trial_seed("sha256:other", 1)
    assert 0 <= trial_seed("sha256:task", 1) < 2**32


def test_apps_draw_repeatable_random_numbers_from_the_episode_seed():
    from plural import App, Environment, Runtime, action

    class Dice(App):
        def reset(self, initial_state):
            super().reset(initial_state)
            return {"seed": self.seed, "roll": self.rng.randint(1, 1_000_000)}

        @action
        def roll(self) -> int:
            return self.rng.randint(1, 1_000_000)

    environment = Environment(name="dice", apps=[Dice()], runtime=Runtime.local())
    first = environment.reset(seed=3)[0]
    assert first["seed"] == 3
    assert environment.reset(seed=3)[0] == first
    assert environment.reset(seed=4)[0] != first
