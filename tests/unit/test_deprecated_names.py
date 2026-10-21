"""Renamed names keep working for one release, with a DeprecationWarning naming the new one."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

import plural
from plural import Agent, Harness, HarnessDefinition, Runtime, VerifierRuntime
from plural.agents import AgentDefinition
from plural.harness import HarnessAgent
from plural.identity import revision_hash

SCHEMAS = Path(plural.__file__).parent / "schemas" / "packages"


def package_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _keys(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def test_agent_accepts_old_keys_and_serializes_new_ones() -> None:
    with pytest.warns(DeprecationWarning) as caught:
        old = Agent.model_validate(
            {
                "model": "openai/gpt-5.6-luna",
                "auth_mode": "none",
                "secret_names": [],
            }
        )
    assert sorted(str(item.message).split(" is ")[0] for item in caught) == [
        "Agent.auth_mode",
        "Agent.secret_names",
    ]
    assert "use Agent.secrets" in " ".join(str(item.message) for item in caught)
    new = Agent(model="openai/gpt-5.6-luna", auth="none")
    assert old.auth == "none"
    assert old == new
    dumped = new.model_dump(mode="json")
    assert {"harness_config", "auth", "secrets"} <= set(dumped)
    assert not {"harness_kwargs", "auth_mode", "secret_names"} & set(dumped)
    with pytest.warns(DeprecationWarning, match=r"Agent\.auth_mode .* use Agent\.auth"):
        assert new.auth_mode == "none"


def test_agent_rejects_old_and_new_key_together() -> None:
    with pytest.raises(ValueError, match="keep auth"):
        Agent.model_validate({"model": "openai/gpt-5.6-luna", "auth": "none", "auth_mode": "none"})


def test_agent_identity_is_unchanged_by_the_rename() -> None:
    definition = AgentDefinition(name="agent", model="test/model", auth="none")
    payload = definition.model_dump(mode="json", exclude={"harness", "harness_package"})
    del payload["credentials"]
    payload["harness_kwargs"] = payload.pop("harness_config")
    payload["auth_mode"] = payload.pop("auth")
    payload["secret_names"] = payload.pop("secrets")
    payload["harness"] = None
    assert definition.content_hash == revision_hash("agent", payload)
    with pytest.warns(DeprecationWarning):
        stored = AgentDefinition.model_validate(
            {"name": "agent", "model": "test/model", "auth_mode": "none"}
        )
    assert stored.content_hash == definition.content_hash


def test_harness_definition_env_vars(tmp_path: Path) -> None:
    with pytest.warns(DeprecationWarning, match=r"HarnessDefinition\.environment"):
        old = HarnessDefinition.model_validate(
            {"name": "h", "command": "python run.py", "source": str(tmp_path), "environment": ["A"]}
        )
    new = HarnessDefinition(
        name="h", command=("python", "run.py"), source=str(tmp_path), env_vars=("A",)
    )
    assert old == new
    assert "env_vars" in new.model_dump() and "environment" not in new.model_dump()
    with pytest.warns(DeprecationWarning):
        assert new.environment == ("A",)


def test_harness_subclass_environment_moves_to_env_vars() -> None:
    with pytest.warns(DeprecationWarning, match=r"Old\.environment .* use Old\.env_vars"):

        class Old(Harness):
            name = "old"
            environment = ("TOKEN",)

            def run(self, task: Any, agent: Any, environment: Any) -> str:
                return ""

    assert Old.env_vars == ("TOKEN",)


def test_harness_agent_harness_kwargs() -> None:
    agent = HarnessAgent({"harness_kwargs": {"sandbox": "read-only"}})
    assert agent.harness_config == {"sandbox": "read-only"}
    with pytest.warns(DeprecationWarning, match="harness_config"):
        assert agent.harness_kwargs == {"sandbox": "read-only"}


def test_runtime_accepts_old_keys_and_keeps_its_hash() -> None:
    with pytest.warns(DeprecationWarning) as caught:
        old = Runtime.model_validate(
            {
                "network": "allowlist",
                "network_allowlist": ["api.example.com"],
                "build_timeout_sec": 30,
                "resources": {"cpu": 2},
                "targets": ["docker", "remote"],
            }
        )
    assert len(caught) == 3
    new = Runtime.docker(
        image=None,
        network="allowlist",
        allowed_hosts=("api.example.com",),
        cpus=2,
        build_timeout_seconds=30,
    )
    assert old == new
    assert new.compute.cpu == 2 and new.build_timeout_seconds == 30
    dumped = new.model_dump(mode="json")
    assert {"allowed_hosts", "compute", "build_timeout_seconds"} <= set(dumped)
    assert not {"network_allowlist", "resources", "build_timeout_sec"} & set(dumped)
    with pytest.warns(DeprecationWarning, match=r"Runtime\.compute"):
        assert new.resources == new.compute


def test_verifier_runtime_accepts_old_keys() -> None:
    with pytest.warns(DeprecationWarning):
        old = VerifierRuntime.model_validate(
            {"network": "allowlist", "network_allowlist": ["a.example"], "resources": {"cpu": 1}}
        )
    assert old.allowed_hosts == ("a.example",) and old.compute.cpu == 1


def test_package_schemas_show_only_new_keys() -> None:
    agent = _keys(package_schema("Agent"))
    assert {"harness_config", "auth", "secrets"} <= agent
    assert not {"harness_kwargs", "auth_mode", "secret_names"} & agent
    runtime = _keys(package_schema("Environment")["$defs"]["EnvironmentRuntime"])
    assert {"allowed_hosts", "compute", "build_timeout_seconds"} <= runtime
    assert not {"network_allowlist", "resources", "build_timeout_sec"} & runtime


@pytest.mark.parametrize(
    ("module", "old", "new"),
    [
        ("plural", "Plural", "Client"),
        ("plural", "TimeoutError", "PluralTimeoutError"),
        ("plural", "Capability", "SandboxCapability"),
        ("plural", "Outcome", "TraceOutcome"),
        ("plural.client", "Plural", "Client"),
        ("plural.errors", "TimeoutError", "PluralTimeoutError"),
        ("plural.sandbox", "Capability", "SandboxCapability"),
        ("plural.tracing", "Outcome", "TraceOutcome"),
        ("plural.execution", "Trial", "TrialRunner"),
    ],
)
def test_renamed_top_level_names_still_import(module: str, old: str, new: str) -> None:
    loaded = importlib.import_module(module)
    with pytest.warns(DeprecationWarning, match=new):
        value = getattr(loaded, old)
    replacement = (
        importlib.import_module("plural.execution").TrialRunner
        if new == "TrialRunner"
        else getattr(loaded, new, None) or getattr(plural, new)
    )
    assert value is replacement


def test_trial_is_not_a_top_level_export() -> None:
    assert "Trial" not in plural.__all__
    assert "TrialRunner" not in plural.__all__
    with pytest.warns(DeprecationWarning, match="TrialRunner"):
        assert plural.Trial is importlib.import_module("plural.execution").TrialRunner
