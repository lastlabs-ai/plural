"""Runtime providers, project Runtimes, and copying one into an Environment."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from hosted_fake import FakeHosted, routed
from project_fixtures import hasher_for, write_project
from typer.testing import CliRunner

import plural.auth
from plural.auth import Credential
from plural.cli.main import app
from plural.common import ExecutionTarget
from plural.environments.definition import EnvironmentRuntime
from plural.project import Project, ProjectBinding, Workspace
from plural.project.layout import ENVIRONMENT, ResourceRef
from plural.project.manifests import read_yaml_mapping
from plural.project.resources import runtime_from_manifest
from plural.project.runtimes import use_runtime
from plural.sandbox.catalog import (
    RUNTIME_PROVIDERS,
    RuntimeSettingsError,
    clean_credentials,
    clean_settings,
    require_provider,
    resolved_settings,
    runtime_environ,
    runtime_from_settings,
    settings_from_runtime,
)

runner = CliRunner()


def test_every_available_provider_explains_each_field_and_credential() -> None:
    available = [item for item in RUNTIME_PROVIDERS if item.status == "available"]
    assert {item.id for item in available} == {"daytona", "docker", "local"}
    for provider in available:
        assert provider.fields, provider.id
        for field in provider.fields:
            assert field.label and len(field.help) > 20, (provider.id, field.key)
            if field.kind == "select":
                assert field.options, (provider.id, field.key)
        for credential in provider.credentials:
            assert credential.help, (provider.id, credential.key)
    coming = {item.id for item in RUNTIME_PROVIDERS if item.status == "coming_soon"}
    assert coming == {"e2b", "modal", "blaxel", "cloudflare", "aws", "gcp", "azure"}


@pytest.mark.parametrize(
    ("provider", "settings", "message"),
    [
        ("daytona", {"gpus": "A10G"}, "has no setting 'gpus'"),
        ("daytona", {"target": "mars"}, "Region must be one of"),
        ("docker", {"cpus": "lots"}, "CPU cores must be a number"),
        ("docker", {"memory_mb": 16}, "Memory must be at least 128 MB"),
        ("daytona", {"api_url": "ftp://x"}, "API URL must be a URL"),
        ("daytona", {"allowed_hosts": "not a host"}, "is not a host name"),
        ("aws", {}, "coming soon"),
        ("modal", {}, "Modal Runtimes are coming soon"),
        ("nope", {}, "Unknown Runtime provider"),
    ],
)
def test_settings_are_validated_with_readable_errors(
    provider: str, settings: dict[str, object], message: str
) -> None:
    with pytest.raises(RuntimeSettingsError, match=message):
        clean_settings(provider, settings)


def test_partial_settings_skip_required_fields_for_template_overrides() -> None:
    assert clean_settings("daytona", {"memory_mb": "2048"}, partial=True) == {"memory_mb": 2048}


def test_resolved_settings_fill_defaults_and_check_the_network() -> None:
    assert resolved_settings("daytona", {})["image"] == "python:3.12-slim"
    assert "image" not in resolved_settings("daytona", {"snapshot": "warm"})
    with pytest.raises(RuntimeSettingsError, match="at least one allowed host"):
        resolved_settings("daytona", {"network": "allowlist"})
    with pytest.raises(RuntimeSettingsError, match="must be one of: public, no-network"):
        resolved_settings("docker", {"network": "allowlist"})


def test_credentials_require_every_required_key_unless_already_stored() -> None:
    with pytest.raises(RuntimeSettingsError, match="API key"):
        clean_credentials("daytona", {})
    assert (
        clean_credentials("daytona", {"DAYTONA_API_KEY": ""}, stored=frozenset({"DAYTONA_API_KEY"}))
        == {}
    )
    with pytest.raises(RuntimeSettingsError, match="no credential"):
        clean_credentials("daytona", {"OPENAI_API_KEY": "x"})


def test_runtime_from_settings_maps_fields_and_placement() -> None:
    runtime = runtime_from_settings(
        "daytona", {"target": "eu", "cpus": "4", "memory_mb": 8192}, ref="big-box"
    )
    assert runtime.provider == "daytona"
    assert runtime.ref == "big-box"
    assert runtime.placement == {"target": "eu"}
    assert runtime.resources.cpu == 4 and runtime.resources.memory_mb == 8192
    assert runtime.requested_target is ExecutionTarget.REMOTE
    assert settings_from_runtime(runtime)["target"] == "eu"
    assert runtime_environ("daytona", {"target": "eu"}) == {"DAYTONA_TARGET": "eu"}


def test_sizes_come_in_steps_and_provider_defaults_are_never_applied() -> None:
    daytona = require_provider("daytona")
    cpus, memory = daytona.field("cpus"), daytona.field("memory_mb")
    assert cpus is not None and cpus.kind == "integer" and cpus.provider_default == 1
    assert memory is not None and memory.step == 1024
    with pytest.raises(RuntimeSettingsError, match="whole number"):
        clean_settings("daytona", {"cpus": 1.5})
    with pytest.raises(RuntimeSettingsError, match="multiple of 1024"):
        clean_settings("daytona", {"memory_mb": 1500})
    with pytest.raises(RuntimeSettingsError, match="multiple of 0.5"):
        clean_settings("docker", {"cpus": 0.7})
    assert clean_settings("docker", {"cpus": "1.5"}) == {"cpus": 1.5}
    resolved = resolved_settings("daytona", {})
    assert "cpus" not in resolved and "memory_mb" not in resolved


@pytest.mark.parametrize(
    ("manifest", "preset"),
    [
        ({"provider": "docker"}, EnvironmentRuntime.docker()),
        ({"provider": "local"}, EnvironmentRuntime.local()),
        ({"provider": "daytona"}, EnvironmentRuntime.daytona()),
        (
            {"provider": "docker", "image": "x:1", "cpus": 2, "network": "no-network"},
            EnvironmentRuntime.docker(image="x:1", cpus=2, network="no-network"),
        ),
        (
            {"provider": "daytona", "network": "allowlist", "allowed_hosts": ["api.openai.com"]},
            EnvironmentRuntime.daytona(network="allowlist", allowed_hosts=("api.openai.com",)),
        ),
        (
            {"provider": "docker", "dockerfile": "Dockerfile"},
            EnvironmentRuntime.docker(dockerfile="Dockerfile"),
        ),
    ],
)
def test_existing_manifests_build_the_same_runtime(
    manifest: dict[str, object], preset: EnvironmentRuntime
) -> None:
    assert runtime_from_manifest(manifest) == preset


def test_a_bare_ref_asks_for_plural_runtime_use() -> None:
    with pytest.raises(ValueError, match="plural runtime use gpu-box"):
        runtime_from_manifest({"ref": "gpu-box"})


def test_an_unset_ref_leaves_environment_hashes_unchanged(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    environment = Workspace(project).load(ResourceRef(ENVIRONMENT.name, "queue")).value
    definition = environment.definition()
    payload = definition.model_dump(mode="json", exclude={"source"})
    assert payload["runtime"]["ref"] is None
    referenced = definition.model_copy(
        update={"runtime": definition.runtime.model_copy(update={"ref": "gpu-box"})}
    )
    assert referenced.content_hash != definition.content_hash
    del payload["runtime"]["ref"]
    from plural.identity import revision_hash

    payload["source_digest"] = definition.source.digest if definition.source else None
    if payload["source_digest"] is not None:
        for rewarder in payload["rewarders"]:
            rewarder.pop("implementation_digest", None)
    assert revision_hash("environment", payload) == definition.content_hash


def test_use_runtime_replaces_only_the_runtime_block(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    path = project.manifest_path(ResourceRef(ENVIRONMENT.name, "queue"))
    path.write_text(
        path.read_text().replace(
            "runtime:\n",
            "runtime:\n  variables:\n    - name: SUPPORT_API_URL\n      format: url\n",
            1,
        )
        if "runtime:\n" in path.read_text()
        else path.read_text()
        + "runtime:\n  provider: local\n  variables:\n    - name: SUPPORT_API_URL\n"
    )
    before = read_yaml_mapping(path)
    runtime = runtime_from_settings("daytona", {"target": "eu"}, ref="eu-box")
    assert use_runtime(project, "queue", runtime.model_dump(mode="json"))
    after = read_yaml_mapping(path)
    assert {key: value for key, value in after.items() if key != "runtime"} == {
        key: value for key, value in before.items() if key != "runtime"
    }
    assert after["runtime"]["provider"] == "daytona"
    assert after["runtime"]["ref"] == "eu-box"
    assert after["runtime"]["target"] == "eu"
    assert after["runtime"]["variables"][0]["name"] == "SUPPORT_API_URL"
    rebuilt = runtime_from_manifest(after["runtime"])
    assert rebuilt.ref == "eu-box" and rebuilt.placement["target"] == "eu"
    assert not use_runtime(project, "queue", runtime.model_dump(mode="json"))


class Hosted:
    def __init__(self, project: Project, fake: FakeHosted) -> None:
        self.project = project
        self.fake = fake

    def cli(self, *args: str) -> tuple[int, str]:
        result = runner.invoke(app, list(args))
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result.exit_code, result.output


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path) -> Iterator[Hosted]:
    project = write_project(tmp_path / "support-desk")
    fake = FakeHosted(hasher_for(project.root))
    record = fake.add_project("support-desk")
    plural.auth.default_credential_store().set("default", Credential(access_token="token"))
    project.write_binding(
        ProjectBinding(
            api_url="https://plural.test",
            account_id="acc_personal",
            project_id=record["id"],
            project_slug="support-desk",
        )
    )
    monkeypatch.setenv("PLURAL_API_URL", "https://plural.test")
    monkeypatch.chdir(project.root)
    with routed(monkeypatch, fake):
        yield Hosted(project, fake)


def test_providers_lists_what_each_provider_needs(hosted: Hosted) -> None:
    code, output = hosted.cli("runtime", "providers")
    assert code == 0, output
    assert "DAYTONA_API_KEY" in output
    assert "coming soon" in output
    code, output = hosted.cli("runtime", "provider", "daytona")
    assert code == 0, output
    assert "DAYTONA_API_KEY" in output and "target" in output


def test_create_from_a_provider_then_use_it_in_an_environment(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, output = hosted.cli("runtime", "create", "GPU box", "--provider", "modal", "--no-input")
    assert code != 0 and "coming soon" in output
    assert not hosted.fake.runtimes

    monkeypatch.setenv("DAYTONA_API_KEY", "dtn_secret_1234")
    code, output = hosted.cli(
        "runtime",
        "create",
        "Agent box",
        "--provider",
        "daytona",
        "--set",
        "target=eu",
        "--credentials-from-env",
        "--no-input",
        "--json",
    )
    assert code == 0, output
    created = json.loads(output)
    assert created["slug"] == "agent-box"
    assert hosted.fake.runtimes[0]["secrets"] == {"DAYTONA_API_KEY": "dtn_secret_1234"}

    code, output = hosted.cli("runtime", "list")
    assert code == 0, output
    assert "agent-box" in output and "custom" in output

    code, output = hosted.cli("runtime", "use", "agent-box", "queue")
    assert code == 0, output
    assert "now runs on agent-box" in output
    manifest = read_yaml_mapping(
        hosted.project.manifest_path(ResourceRef(ENVIRONMENT.name, "queue"))
    )
    assert manifest["runtime"]["provider"] == "daytona"
    assert manifest["runtime"]["ref"] == "agent-box"
    assert manifest["runtime"]["target"] == "eu"
    code, output = hosted.cli("env", "validate", "queue")
    assert code == 0, output


def test_create_from_a_template_refuses_credentials(hosted: Hosted) -> None:
    code, output = hosted.cli(
        "runtime",
        "template",
        "create",
        "Daytona EU",
        "--provider",
        "daytona",
        "--set",
        "target=eu",
        "--lock",
        "target",
        "--no-input",
        "--json",
    )
    assert code == 0, output
    code, output = hosted.cli(
        "runtime",
        "create",
        "Fast",
        "--template",
        "daytona-eu",
        "--credential",
        "DAYTONA_API_KEY=x",
        "--no-input",
    )
    assert code == 1
    assert "uses the template's credentials" in output
    code, output = hosted.cli(
        "runtime", "create", "Fast", "--template", "daytona-eu", "--set", "cpus=2", "--no-input"
    )
    assert code == 0, output
    assert "from template daytona-eu" in output


def test_policy_set_sends_templates_only_with_allowed_providers(hosted: Hosted) -> None:
    code, output = hosted.cli(
        "runtime", "policy", "set", "--mode", "templates-only", "--allow", "modal"
    )
    assert code == 0, output
    assert hosted.fake.runtime_policy["mode"] == "templates_only"
    assert hosted.fake.runtime_policy["allowed_providers"] == ["modal"]
    code, output = hosted.cli("runtime", "policy")
    assert code == 0, output
    assert "only Runtimes from templates" in output


def test_local_runs_load_missing_credentials_from_the_project_runtime(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.cli.run_commands import _runtime_credentials

    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    hosted.fake.runtimes.append(
        {
            "id": "rt_1",
            "slug": "day",
            "name": "day",
            "description": "",
            "provider": "daytona",
            "template_id": None,
            "overrides": {},
            "credential_hints": {},
            "secrets": {"DAYTONA_API_KEY": "dtn_from_hosted", "DAYTONA_TARGET": "eu"},
        }
    )
    runtime = runtime_from_settings("daytona", {}, ref="day")

    class Plan:
        class spec:  # noqa: N801
            tasks = [
                type(
                    "Task",
                    (),
                    {"environment": type("Env", (), {"runtime": runtime})()},
                )()
            ]

    _runtime_credentials(Workspace(hosted.project), Plan(), err=True)  # type: ignore[arg-type]
    assert os.environ["DAYTONA_API_KEY"] == "dtn_from_hosted"
    assert os.environ["DAYTONA_TARGET"] == "eu"
    monkeypatch.delenv("DAYTONA_API_KEY")
    monkeypatch.delenv("DAYTONA_TARGET")


def test_daytona_runtimes_default_to_plurals_account(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, output = hosted.cli("runtime", "create", "Box", "--provider", "daytona", "--no-input")
    assert code == 0, output
    assert "billed to your credits as compute usage" in output
    assert hosted.fake.runtimes[0]["credential_mode"] == "plural"
    code, output = hosted.cli("runtime", "list")
    assert "plural" in output

    monkeypatch.setenv("DAYTONA_API_KEY", "dtn_secret_1234")
    code, output = hosted.cli(
        "runtime", "create", "Own", "--provider", "daytona", "--credentials-from-env", "--no-input"
    )
    assert code == 0, output
    assert hosted.fake.runtimes[1]["credential_mode"] == "own"
    code, output = hosted.cli(
        "runtime",
        "create",
        "Both",
        "--provider",
        "daytona",
        "--plural-credentials",
        "--credentials-from-env",
        "--no-input",
    )
    assert code == 1 and "--own-credentials" in output
    code, output = hosted.cli(
        "runtime", "create", "Docker", "--provider", "docker", "--plural-credentials", "--no-input"
    )
    assert code == 1 and "cannot start Docker sandboxes" in output


def test_plural_account_runtimes_start_sandboxes_through_plural(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from plural.cli.run_commands import _runtime_credentials
    from plural.sandbox import DaytonaProvider, default_registry
    from plural.sandbox.models import ExecRequest, FileUpload, SandboxRequirements

    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    code, output = hosted.cli("runtime", "create", "Day", "--provider", "daytona", "--no-input")
    assert code == 0, output
    runtime = runtime_from_settings("daytona", {}, ref="day")

    class Plan:
        class spec:  # noqa: N801
            tasks = [type("Task", (), {"environment": type("Env", (), {"runtime": runtime})()})()]

    try:
        _runtime_credentials(Workspace(hosted.project), Plan(), err=True)  # type: ignore[arg-type]
        assert "DAYTONA_API_KEY" not in os.environ
        provider = default_registry.get("daytona")

        async def run() -> tuple[bytes, str]:
            assert (await provider.capabilities()).available
            handle = await provider.create(SandboxRequirements(image="python:3.12-slim"))
            await provider.upload_files(handle, [FileUpload(path="a.txt", data=b"hello")])
            result = await provider.exec(handle, ExecRequest(command=("echo", "hi")))
            (downloaded,) = await provider.download_files(handle, ["a.txt"])
            await provider.destroy(handle)
            return downloaded.data, result.stdout.decode()

        data, stdout = asyncio.run(run())
    finally:
        default_registry.register(DaytonaProvider(), replace=True)
    assert (data, stdout) == (b"hello", "echo hi")
    (sandbox,) = hosted.fake.sandboxes.values()
    assert sandbox["runtime"] == "day"
    assert sandbox["requirements"]["image"] == "python:3.12-slim"
    assert sandbox["files"] == {"/workspace/a.txt": b"hello"}
    assert sandbox["status"] == "ended"
