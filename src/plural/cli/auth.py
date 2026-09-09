"""Device authorization HTTP client for the Plural CLI."""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from plural.cli.config import Credential
from plural.domain import ErrorCode


class AuthHTTPError(RuntimeError):
    """Sanitized auth API error with a stable code."""

    def __init__(self, message: str, *, code: ErrorCode, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AuthModel(BaseModel):
    """Strict immutable auth response base."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class DeviceAuthorization(AuthModel):
    """Device flow instructions returned by the service."""

    device_code: str = Field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    expires_in: int = Field(default=600, gt=0)
    interval: int = Field(default=5, gt=0)


class AuthTokens(AuthModel):
    """Access and refresh tokens from device or refresh flow."""

    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    token_type: str = "Bearer"
    expires_in: int | None = None

    def credential(self) -> Credential:
        """Convert the token response into stored credentials."""
        return Credential(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
        )


class AuthStatus(AuthModel):
    """Authentication status from the hosted service."""

    authenticated: bool
    subject: str | None = None
    expires_at: str | None = None


class AuthClient:
    """Synchronous client for future LastLabs device auth endpoints."""

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
        """Start a device authorization flow."""
        response = self._client.post("/api/v1/auth/device/start", json={"client": "plural-cli"})
        device = DeviceAuthorization.model_validate(self._json(response))
        self._poll_interval = device.interval
        return device

    def device_poll(self, device_code: str) -> AuthTokens | None:
        """Poll once, returning ``None`` while user authorization is pending."""
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
        """Complete device authorization without handling passwords."""
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
        """Exchange a refresh token for new tokens."""
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

    def status(self, credential: Credential) -> AuthStatus:
        """Return hosted authentication status."""
        response = self._client.get(
            "/api/v1/auth/status",
            headers=self._authorization(credential),
        )
        return AuthStatus.model_validate(self._json(response))

    def whoami(self, credential: Credential) -> dict[str, Any]:
        """Return the authenticated account payload."""
        response = self._client.get(
            "/api/v1/account/me",
            headers=self._authorization(credential),
        )
        return self._json(response)

    @staticmethod
    def _authorization(credential: Credential) -> dict[str, str]:
        token = credential.access_token or credential.api_key
        if token is None:
            raise AuthHTTPError(
                "not authenticated; run `plural auth login` or set PLURAL_API_KEY",
                code=ErrorCode.AUTHENTICATION,
            )
        return {"Authorization": f"Bearer {token}"}

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


__all__ = [
    "AuthClient",
    "AuthHTTPError",
    "AuthStatus",
    "AuthTokens",
    "DeviceAuthorization",
]
