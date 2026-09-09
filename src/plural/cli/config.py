"""CLI context, persistent configuration, and secure credential storage."""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping
from contextlib import suppress
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

if sys.version_info >= (3, 11):
    import tomllib as tomli
else:
    import tomli

DEFAULT_API_URL = "https://api.pluralintel.com"


class CLIProfile(BaseModel):
    """One named CLI context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_url: str = DEFAULT_API_URL
    organization: str | None = None
    project: str | None = None


class CLIConfig(BaseModel):
    """Persistent, non-secret CLI configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_profile: str = "default"
    profiles: dict[str, CLIProfile] = Field(default_factory=lambda: {"default": CLIProfile()})

    @property
    def active(self) -> CLIProfile:
        """Selected profile, falling back to defaults."""
        return self.profiles.get(self.active_profile, CLIProfile())


class Credential(BaseModel):
    """Secret tokens stored for one profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    access_token: str | None = Field(default=None, repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    api_key: str | None = Field(default=None, repr=False)

    def redacted(self) -> dict[str, str | None]:
        """Return presence-only values safe for logs and machine output."""
        return {
            "access_token": "***" if self.access_token else None,
            "refresh_token": "***" if self.refresh_token else None,
            "api_key": "***" if self.api_key else None,
        }


class CredentialStore(Protocol):
    """Minimal credential storage abstraction."""

    def get(self, profile: str) -> Credential | None:
        """Read credentials for a profile."""
        ...

    def set(self, profile: str, credential: Credential) -> None:
        """Persist credentials for a profile."""
        ...

    def delete(self, profile: str) -> None:
        """Delete credentials for a profile."""
        ...


class FileCredentialStore:
    """0600 JSON credential fallback."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, profile: str) -> Credential | None:
        """Read and validate one profile's credential."""
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw = payload.get(profile) if isinstance(payload, dict) else None
        return Credential.model_validate(raw) if isinstance(raw, dict) else None

    def set(self, profile: str, credential: Credential) -> None:
        """Atomically save credentials with owner-only permissions."""
        payload = self._read_all()
        payload[profile] = credential.model_dump(mode="json")
        self._write_all(payload)

    def delete(self, profile: str) -> None:
        """Delete one profile without affecting others."""
        payload = self._read_all()
        payload.pop(profile, None)
        self._write_all(payload)

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(raw) if isinstance(raw, dict) else {}

    def _write_all(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)


class KeyringCredentialStore:
    """Optional OS keyring-backed credential store."""

    service_name = "plural-cli"

    def __init__(self, keyring_module: Any) -> None:
        self._keyring = keyring_module

    def get(self, profile: str) -> Credential | None:
        """Read serialized credentials from the OS keyring."""
        raw = self._keyring.get_password(self.service_name, profile)
        return Credential.model_validate_json(raw) if raw else None

    def set(self, profile: str, credential: Credential) -> None:
        """Store serialized credentials in the OS keyring."""
        self._keyring.set_password(self.service_name, profile, credential.model_dump_json())

    def delete(self, profile: str) -> None:
        """Delete credentials when they exist."""
        try:
            self._keyring.delete_password(self.service_name, profile)
        except Exception:  # noqa: BLE001
            return


class FallbackCredentialStore:
    """Use the keyring when available and securely fall back to a file."""

    def __init__(self, fallback: CredentialStore, primary: CredentialStore | None = None) -> None:
        self.fallback = fallback
        self.primary = primary

    def get(self, profile: str) -> Credential | None:
        """Read from primary, then fallback."""
        if self.primary is not None:
            try:
                value = self.primary.get(profile)
                if value is not None:
                    return value
            except Exception:  # noqa: BLE001
                pass
        return self.fallback.get(profile)

    def set(self, profile: str, credential: Credential) -> None:
        """Write to primary, falling back on backend errors."""
        if self.primary is not None:
            try:
                self.primary.set(profile, credential)
                return
            except Exception:  # noqa: BLE001
                pass
        self.fallback.set(profile, credential)

    def delete(self, profile: str) -> None:
        """Delete from both stores without exposing backend details."""
        if self.primary is not None:
            with suppress(Exception):
                self.primary.delete(profile)
        self.fallback.delete(profile)


class ResolvedContext(BaseModel):
    """Effective CLI context after flags > environment > config precedence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: str
    api_url: str
    organization: str | None
    project: str | None
    api_key: str | None = Field(default=None, repr=False)

    def redacted(self) -> dict[str, Any]:
        """Return context safe for console output."""
        return {
            "profile": self.profile,
            "api_url": self.api_url,
            "organization": self.organization,
            "project": self.project,
            "authenticated": bool(self.api_key),
        }


def config_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the platform-aware Plural CLI config directory."""
    env = os.environ if environ is None else environ
    configured = env.get("PLURAL_CONFIG_HOME")
    if configured:
        return Path(configured).expanduser()
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "plural"
    return Path.home() / ".config" / "plural"


def load_config(path: Path | None = None) -> CLIConfig:
    """Load config, returning defaults when the file does not exist."""
    source = path or config_home() / "config.toml"
    if not source.exists():
        return CLIConfig()
    with source.open("rb") as handle:
        return CLIConfig.model_validate(tomli.load(handle))


def save_config(config: CLIConfig, path: Path | None = None) -> Path:
    """Persist non-secret config as deterministic TOML."""
    destination = path or config_home() / "config.toml"
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = [f"active_profile = {json.dumps(config.active_profile)}", ""]
    for name in sorted(config.profiles):
        profile = config.profiles[name]
        lines.append(f"[profiles.{json.dumps(name)}]")
        lines.append(f"api_url = {json.dumps(profile.api_url)}")
        if profile.organization is not None:
            lines.append(f"organization = {json.dumps(profile.organization)}")
        if profile.project is not None:
            lines.append(f"project = {json.dumps(profile.project)}")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def default_credential_store(path: Path | None = None) -> CredentialStore:
    """Build optional keyring plus secure file fallback storage."""
    fallback = FileCredentialStore(path or config_home() / "credentials.json")
    primary: CredentialStore | None = None
    try:
        keyring = import_module("keyring")
        primary = KeyringCredentialStore(keyring)
    except ImportError:
        pass
    return FallbackCredentialStore(fallback=fallback, primary=primary)


def resolve_context(
    *,
    api_url: str | None = None,
    organization: str | None = None,
    project: str | None = None,
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    config: CLIConfig | None = None,
    credentials: CredentialStore | None = None,
) -> ResolvedContext:
    """Resolve flags > environment > selected profile config."""
    env = os.environ if environ is None else environ
    stored = config or load_config()
    selected = profile or env.get("PLURAL_PROFILE") or stored.active_profile
    configured = stored.profiles.get(selected, CLIProfile())
    credential = credentials.get(selected) if credentials is not None else None
    api_key = env.get("PLURAL_API_KEY") or (credential.api_key if credential else None)
    return ResolvedContext(
        profile=selected,
        api_url=api_url or env.get("PLURAL_API_URL") or configured.api_url,
        organization=organization or env.get("PLURAL_ORG") or configured.organization,
        project=project or env.get("PLURAL_PROJECT") or configured.project,
        api_key=api_key,
    )


__all__ = [
    "CLIConfig",
    "CLIProfile",
    "Credential",
    "CredentialStore",
    "FileCredentialStore",
    "ResolvedContext",
    "config_home",
    "default_credential_store",
    "load_config",
    "resolve_context",
    "save_config",
]
