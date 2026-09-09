from __future__ import annotations

import stat
from pathlib import Path

from plural.cli.config import (
    CLIConfig,
    CLIProfile,
    Credential,
    FileCredentialStore,
    load_config,
    resolve_context,
    save_config,
)


def test_context_precedence_flags_then_environment_then_config(tmp_path: Path) -> None:
    config = CLIConfig(
        active_profile="work",
        profiles={
            "work": CLIProfile(
                api_url="https://config.example",
                organization="config-org",
                project="config-project",
            )
        },
    )
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set("work", Credential(api_key="stored-secret"))
    environment = {
        "PLURAL_API_URL": "https://env.example",
        "PLURAL_ORG": "env-org",
        "PLURAL_PROJECT": "env-project",
        "PLURAL_API_KEY": "ci-secret",
    }

    env_context = resolve_context(config=config, credentials=store, environ=environment)
    assert env_context.api_url == "https://env.example"
    assert env_context.organization == "env-org"
    assert env_context.project == "env-project"
    assert env_context.api_key == "ci-secret"

    flag_context = resolve_context(
        config=config,
        credentials=store,
        environ=environment,
        api_url="https://flag.example",
        organization="flag-org",
        project="flag-project",
    )
    assert flag_context.api_url == "https://flag.example"
    assert flag_context.organization == "flag-org"
    assert flag_context.project == "flag-project"


def test_file_credentials_are_0600_and_redacted(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = FileCredentialStore(path)
    credential = Credential(
        access_token="access-secret",
        refresh_token="refresh-secret",
        api_key="api-secret",
    )
    store.set("default", credential)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.get("default") == credential
    assert "secret" not in repr(credential)
    assert credential.redacted() == {
        "access_token": "***",
        "refresh_token": "***",
        "api_key": "***",
    }


def test_config_toml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = CLIConfig(
        active_profile="team",
        profiles={
            "default": CLIProfile(),
            "team": CLIProfile(organization="acme", project="evals"),
        },
    )
    save_config(config, path)
    assert load_config(path) == config
