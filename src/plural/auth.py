"""Hosted Plural credentials, login, and the selected hosted scope.

Three things are kept apart:

* A **credential** proves who you are. It lives in the OS keyring or a
  0600 file under the user config directory, never in a project.
* The **scope** is the hosted destination commands use by default: an account
  (personal or organization), optionally narrowed to one project. Changing it
  selects a destination; it never changes what the credential may do.
* A project's **binding** (``.plural/project.json``) records which hosted
  project a checkout pushes to. See :mod:`plural.project`.

Examples:
    >>> from plural.auth import Profile
    >>> Profile().project_id is None
    True
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from plural.common import ErrorCode

if TYPE_CHECKING:
    from plural.studio import Studio

if sys.version_info >= (3, 11):
    import tomllib as tomli
else:
    import tomli

DEFAULT_API_URL = "https://api.pluralintel.com"


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
        """Read and validate one profile's credential.

        Returns:
            The credential, or ``None`` when none is stored.
        """
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
        """Read serialized credentials from the OS keyring.

        Returns:
            The credential, or ``None`` when none is stored.
        """
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
        """Read from primary, then fallback.

        Returns:
            The credential, or ``None`` when neither store has one.
        """
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


class Profile(BaseModel):
    """One named hosted context: which service, and which scope within it.

    ``account_id`` selects a personal or organization account. ``project_id``
    narrows the scope to one project in that account; ``None`` is account
    scope.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    api_url: str = DEFAULT_API_URL
    account_id: str | None = None
    account_slug: str | None = None
    project_id: str | None = None
    project_slug: str | None = None


class Config(BaseModel):
    """Persistent, non-secret CLI configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_profile: str = "default"
    profiles: dict[str, Profile] = Field(default_factory=lambda: {"default": Profile()})

    @property
    def active(self) -> Profile:
        """Selected profile, falling back to defaults."""
        return self.profiles.get(self.active_profile, Profile())

    def with_profile(self, name: str, profile: Profile) -> Config:
        """A copy with one profile replaced.

        Returns:
            The updated configuration.
        """
        return self.model_copy(update={"profiles": {**self.profiles, name: profile}})


def config_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the platform-aware Plural config directory."""
    env = os.environ if environ is None else environ
    configured = env.get("PLURAL_CONFIG_HOME")
    if configured:
        return Path(configured).expanduser()
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "plural"
    return Path.home() / ".config" / "plural"


def load_config(path: Path | None = None) -> Config:
    """Load config, returning defaults when the file does not exist.

    Returns:
        The stored configuration.
    """
    source = path or config_home() / "config.toml"
    if not source.exists():
        return Config()
    with source.open("rb") as handle:
        return Config.model_validate(tomli.load(handle))


def save_config(config: Config, path: Path | None = None) -> Path:
    """Persist non-secret config as deterministic TOML.

    Returns:
        The written path.
    """
    destination = path or config_home() / "config.toml"
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = [f"active_profile = {json.dumps(config.active_profile)}", ""]
    for name in sorted(config.profiles):
        profile = config.profiles[name]
        lines.append(f"[profiles.{json.dumps(name)}]")
        for key, value in profile.model_dump(exclude_none=True).items():
            lines.append(f"{key} = {json.dumps(value)}")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def default_credential_store(path: Path | None = None) -> CredentialStore:
    """Build optional keyring plus secure file fallback storage.

    Returns:
        The credential store.
    """
    fallback = FileCredentialStore(path or config_home() / "credentials.json")
    primary: CredentialStore | None = None
    try:
        keyring = import_module("keyring")
        primary = KeyringCredentialStore(keyring)
    except ImportError:
        pass
    return FallbackCredentialStore(fallback=fallback, primary=primary)


class AuthHTTPError(RuntimeError):
    """Sanitized auth API error with a stable code."""

    def __init__(self, message: str, *, code: ErrorCode, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _AuthModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class DeviceAuthorization(_AuthModel):
    """Device flow instructions returned by the service."""

    device_code: str = Field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    expires_in: int = Field(default=600, gt=0)
    interval: int = Field(default=5, gt=0)


class AuthTokens(_AuthModel):
    """Access and refresh tokens from device or refresh flow."""

    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    token_type: str = "Bearer"
    expires_in: int | None = None

    def credential(self) -> Credential:
        """Convert the token response into stored credentials.

        Returns:
            The credential to store.
        """
        return Credential(access_token=self.access_token, refresh_token=self.refresh_token)


class AuthStatus(_AuthModel):
    """What the hosted service knows about the presented credential.

    ``credential`` is ``login`` for an interactive login or ``api_key``.
    An API key may be limited to one account (``account_id``) and one
    project (``project_id``); a login is limited only by the user's roles.
    """

    authenticated: bool
    subject: str | None = None
    expires_at: str | None = None
    credential: Literal["login", "api_key"] | None = None
    account_id: str | None = None
    project_id: str | None = None


class AuthClient:
    """Synchronous client for the hosted device-authorization endpoints."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "plural-cli"},
        )
        self._poll_interval = 5

    def __enter__(self) -> AuthClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def device_start(self) -> DeviceAuthorization:
        """Start a device authorization flow.

        Returns:
            Instructions to show the user.
        """
        response = self._client.post("/api/v1/auth/device/start", json={"client": "plural-cli"})
        device = DeviceAuthorization.model_validate(self._json(response))
        self._poll_interval = device.interval
        return device

    def device_poll(self, device_code: str) -> AuthTokens | None:
        """Poll once, returning ``None`` while user authorization is pending.

        Returns:
            Tokens once the user approves, otherwise ``None``.
        """
        response = self._client.post(
            "/api/v1/auth/device/poll",
            json={"device_code": device_code, "client": "plural-cli"},
        )
        if response.status_code in {202, 428}:
            return None
        if response.status_code == 400:
            payload = self._safe_payload(response)
            if payload.get("error") in {"authorization_pending", "slow_down"}:
                interval = payload.get("interval")
                if (
                    payload.get("error") == "slow_down"
                    and isinstance(interval, int)
                    and interval > 0
                ):
                    self._poll_interval = interval
                return None
        return AuthTokens.model_validate(self._json(response))

    def login(
        self,
        *,
        no_browser: bool = False,
        open_browser: Callable[[str], Any] = webbrowser.open,
        on_device: Callable[[DeviceAuthorization], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> tuple[DeviceAuthorization, AuthTokens]:
        """Complete device authorization without handling passwords.

        Returns:
            The device instructions and the issued tokens.
        """
        device = self.device_start()
        if on_device is not None:
            on_device(device)
        target = device.verification_uri_complete or device.verification_uri
        if not no_browser:
            open_browser(target)
        deadline = monotonic() + device.expires_in
        while monotonic() < deadline:
            tokens = self.device_poll(device.device_code)
            if tokens is not None:
                return device, tokens
            sleep(float(self._poll_interval))
        raise AuthHTTPError(
            "device authorization expired; run `plural auth login` again",
            code=ErrorCode.AUTHENTICATION,
        )

    def refresh(self, refresh_token: str) -> AuthTokens:
        """Exchange a refresh token for new tokens.

        Returns:
            The new tokens.
        """
        response = self._client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token, "client": "plural-cli"},
        )
        return AuthTokens.model_validate(self._json(response))

    def revoke(self, credential: Credential) -> None:
        """Revoke available hosted tokens without exposing them."""
        token = credential.refresh_token or credential.access_token
        if token is None:
            return
        response = self._client.post("/api/v1/auth/revoke", json={"token": token})
        self._json(response, allow_empty=True)

    def status(self, token: str) -> AuthStatus:
        """Return hosted authentication status for one bearer token."""
        response = self._client.get(
            "/api/v1/auth/status", headers={"Authorization": f"Bearer {token}"}
        )
        return AuthStatus.model_validate(self._json(response))

    def _json(self, response: httpx.Response, *, allow_empty: bool = False) -> dict[str, Any]:
        if response.is_error:
            payload = self._safe_payload(response)
            detail = (
                payload.get("detail") or payload.get("message") or "authentication request failed"
            )
            code = (
                ErrorCode.AUTHENTICATION
                if response.status_code in {401, 403}
                else ErrorCode.INVALID_REQUEST
            )
            raise AuthHTTPError(str(detail), code=code, status_code=response.status_code)
        if allow_empty and not response.content:
            return {}
        payload = self._safe_payload(response)
        if not payload and not allow_empty:
            raise AuthHTTPError(
                "authentication service returned an invalid response",
                code=ErrorCode.INTERNAL,
                status_code=response.status_code,
            )
        return payload

    @staticmethod
    def _safe_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}


CredentialKind = Literal["api_key", "login"]


@dataclass
class Session:
    """The effective hosted context: service, credential, and scope.

    Precedence is environment over stored configuration: ``PLURAL_API_KEY``
    replaces the stored credential, ``PLURAL_API_URL`` the service, and
    ``PLURAL_ACCOUNT`` / ``PLURAL_PROJECT`` (an id or slug) the scope.
    """

    profile: str
    api_url: str
    credential: Credential | None
    environment_key: str | None
    account_id: str | None
    project: str | None
    project_slug: str | None
    store: CredentialStore | None = None
    http: httpx.Client | None = None

    @property
    def credential_kind(self) -> CredentialKind | None:
        """Which kind of credential authenticates requests."""
        if self.environment_key or (self.credential and self.credential.api_key):
            return "api_key"
        if self.credential and self.credential.access_token:
            return "login"
        return None

    @property
    def token(self) -> str | None:
        """Bearer token for hosted API requests."""
        if self.environment_key:
            return self.environment_key
        if self.credential is None:
            return None
        return self.credential.api_key or self.credential.access_token

    @property
    def api_key(self) -> str | None:
        """An API key for the model gateway, which does not accept login tokens."""
        if self.environment_key:
            return self.environment_key
        return self.credential.api_key if self.credential else None

    def studio(self, *, project: str | None | Literal[False] = None) -> Studio:
        """Hosted API client for this context.

        Args:
            project: A project id to address. ``None`` uses the scope's
                project; ``False`` addresses the account only.

        Returns:
            A client that refreshes an expired login once, transparently.
        """
        from plural.studio import Studio, studio_base_url

        selected = None if project is False else (project or self.project)
        return Studio(
            api_root=studio_base_url(self.api_url),
            token=self.token,
            account=self.account_id,
            project=selected,
            refresh=self._refresh if self.credential_kind == "login" else None,
            http=self.http,
        )

    def _refresh(self) -> str | None:
        credential = self.credential
        if credential is None or not credential.refresh_token:
            return None
        try:
            with AuthClient(self.api_url) as client:
                tokens = client.refresh(credential.refresh_token)
        except (AuthHTTPError, httpx.HTTPError):
            return None
        refreshed = Credential(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token or credential.refresh_token,
        )
        self.credential = refreshed
        if self.store is not None:
            self.store.set(self.profile, refreshed)
        return refreshed.access_token


def resolve_session(
    *,
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    config: Config | None = None,
    store: CredentialStore | None = None,
) -> Session:
    """Resolve the hosted context from the environment and stored profile.

    Returns:
        The effective session. It may carry no credential.
    """
    env = os.environ if environ is None else environ
    stored = config or load_config()
    selected = profile or env.get("PLURAL_PROFILE") or stored.active_profile
    configured = stored.profiles.get(selected, Profile())
    credentials = store if store is not None else default_credential_store()
    credential = credentials.get(selected)
    project_override = env.get("PLURAL_PROJECT")
    return Session(
        profile=selected,
        api_url=env.get("PLURAL_API_URL") or configured.api_url,
        credential=credential,
        environment_key=env.get("PLURAL_API_KEY") or None,
        account_id=env.get("PLURAL_ACCOUNT") or configured.account_id,
        project=project_override or configured.project_id,
        project_slug=None if project_override else configured.project_slug,
        store=credentials,
    )


__all__ = [
    "DEFAULT_API_URL",
    "AuthClient",
    "AuthHTTPError",
    "AuthStatus",
    "AuthTokens",
    "Config",
    "Credential",
    "CredentialKind",
    "CredentialStore",
    "DeviceAuthorization",
    "FallbackCredentialStore",
    "FileCredentialStore",
    "KeyringCredentialStore",
    "Profile",
    "Session",
    "config_home",
    "default_credential_store",
    "load_config",
    "resolve_session",
    "save_config",
]
