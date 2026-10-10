from collections.abc import Iterator
from pathlib import Path

import pytest
from project_fixtures import home

__all__ = ["home", "isolated_user_config"]


@pytest.fixture(autouse=True)
def isolated_user_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Keep every test away from the developer's own profile, keychain, and hosted project."""
    from plural.auth import FileCredentialStore

    config = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("PLURAL_CONFIG_HOME", str(config))
    for name in ("PLURAL_API_KEY", "PLURAL_PROJECT", "PLURAL_ACCOUNT", "PLURAL_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLURAL_API_URL", "https://plural.test")
    store = FileCredentialStore(Path(config) / "credentials.json")
    monkeypatch.setattr("plural.auth.default_credential_store", lambda path=None: store)
    yield
