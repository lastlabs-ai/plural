from __future__ import annotations

import json

import httpx

from plural.cli.auth import AuthClient
from plural.cli.config import Credential


def test_auth_client_device_refresh_revoke_status_and_whoami() -> None:
    requests: list[httpx.Request] = []
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        requests.append(request)
        path = request.url.path
        if path.endswith("/device/start"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device-secret",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://login.example/device",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        if path.endswith("/device/poll"):
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(202, json={"error": "authorization_pending"})
            return httpx.Response(
                200,
                json={"access_token": "access-secret", "refresh_token": "refresh-secret"},
            )
        if path.endswith("/refresh"):
            return httpx.Response(
                200,
                json={"access_token": "new-access", "refresh_token": "new-refresh"},
            )
        if path.endswith("/revoke"):
            return httpx.Response(204)
        if path.endswith("/status"):
            return httpx.Response(200, json={"authenticated": True, "subject": "user-1"})
        if path.endswith("/account/me"):
            return httpx.Response(200, json={"id": "user-1", "email": "dev@example.com"})
        return httpx.Response(404, json={"detail": "missing"})

    opened: list[str] = []
    with AuthClient(
        "https://api.example",
        transport=httpx.MockTransport(handler),
    ) as client:
        device, tokens = client.login(
            open_browser=opened.append,
            sleep=lambda _seconds: None,
            monotonic=lambda: 0.0,
        )
        assert device.user_code == "ABCD-EFGH"
        assert tokens.access_token == "access-secret"
        assert opened == ["https://login.example/device"]
        refreshed = client.refresh(tokens.refresh_token or "")
        assert refreshed.access_token == "new-access"
        credential = tokens.credential()
        assert client.status(credential).authenticated
        assert client.whoami(credential)["id"] == "user-1"
        client.revoke(credential)

    assert any(request.url.path.endswith("/refresh") for request in requests)
    auth_requests = [
        request
        for request in requests
        if request.url.path.endswith("/status") or request.url.path.endswith("/account/me")
    ]
    assert all(
        request.headers["authorization"] == "Bearer access-secret" for request in auth_requests
    )
    bodies = [json.loads(request.content) for request in requests if request.content]
    assert any(body.get("refresh_token") == "refresh-secret" for body in bodies)


def test_no_browser_still_reports_device_before_polling() -> None:
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/device/start"):
            return httpx.Response(
                200,
                json={
                    "device_code": "secret",
                    "user_code": "CODE",
                    "verification_uri": "https://login.example",
                    "expires_in": 10,
                    "interval": 1,
                },
            )
        events.append("poll")
        return httpx.Response(200, json={"access_token": "token"})

    with AuthClient("https://api.example", transport=httpx.MockTransport(handler)) as client:
        client.login(
            no_browser=True,
            open_browser=lambda _url: events.append("browser"),
            on_device=lambda device: events.append(device.user_code),
            sleep=lambda _seconds: None,
            monotonic=lambda: 0.0,
        )
    assert events == ["CODE", "poll"]


def test_credential_repr_never_exposes_tokens() -> None:
    credential = Credential(access_token="top-secret")
    assert "top-secret" not in repr(credential)
