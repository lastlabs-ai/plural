from __future__ import annotations

import stat
from pathlib import Path

from plural.auth import (
    Config,
    Credential,
    FileCredentialStore,
    Profile,
    load_config,
    resolve_session,
    save_config,
)


def test_session_precedence_environment_then_config(tmp_path: Path) -> None:
    config = Config(
        active_profile="work",
        profiles={
            "work": Profile(
                api_url="https://config.example",
                account_id="acc_config",
                project_id="prj_config",
                project_slug="config-project",
            )
        },
    )
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set("work", Credential(api_key="stored-secret"))

    stored = resolve_session(config=config, store=store, environ={})
    assert stored.api_url == "https://config.example"
    assert stored.account_id == "acc_config"
    assert stored.project == "prj_config"
    assert stored.token == "stored-secret"
    assert stored.environment_key is None

    environment = {
        "PLURAL_API_URL": "https://env.example",
        "PLURAL_ACCOUNT": "acc_env",
        "PLURAL_PROJECT": "env-project",
        "PLURAL_API_KEY": "ci-secret",
    }
    overridden = resolve_session(config=config, store=store, environ=environment)
    assert overridden.api_url == "https://env.example"
    assert overridden.account_id == "acc_env"
    assert overridden.project == "env-project"
    assert overridden.token == overridden.api_key == "ci-secret"
    assert overridden.credential_kind == "api_key"

    other = resolve_session(config=config, store=store, environ={"PLURAL_PROFILE": "missing"})
    assert other.profile == "missing"
    assert other.credential is None
    assert other.project is None


def test_login_tokens_never_act_as_gateway_api_keys(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set("default", Credential(access_token="login-token"))
    session = resolve_session(config=Config(), store=store, environ={})
    assert session.credential_kind == "login"
    assert session.token == "login-token"
    assert session.api_key is None


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
    store.delete("default")
    assert store.get("default") is None


def test_config_toml_round_trip_holds_no_secrets(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = Config(
        active_profile="team",
        profiles={
            "default": Profile(),
            "team": Profile(account_id="acc_1", account_slug="acme", project_slug="evals"),
        },
    )
    save_config(config, path)
    assert load_config(path) == config
    assert "secret" not in path.read_text()
    assert "api_key" not in path.read_text()
