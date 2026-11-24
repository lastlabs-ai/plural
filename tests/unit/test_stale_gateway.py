"""A gateway left on this machine doesn't silently fail a hosted project's runs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from plural.cli import run_commands
from plural.project.manifests import ProjectBinding

HOSTED = "https://api.pluralintel.com"


def _space(api_url: str | None) -> Any:
    binding = (
        None
        if api_url is None
        else ProjectBinding(api_url=api_url, project_id="p1", project_slug="demo")
    )
    return SimpleNamespace(project=SimpleNamespace(read_binding=lambda: binding))


def _session(api_url: str) -> Any:
    return SimpleNamespace(api_url=api_url, api_key="plural_key")


def test_a_local_gateway_gives_way_to_the_bound_platform(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLURAL_GATEWAY_URL", "http://localhost:8005/v1")
    environ = run_commands._run_environ(_session(HOSTED), _space(HOSTED))
    assert environ["PLURAL_GATEWAY_URL"] == f"{HOSTED}/v1"
    warning = capsys.readouterr().err
    assert "http://localhost:8005/v1, on this machine" in warning
    assert f"bound to {HOSTED}" in warning


def test_signed_in_elsewhere_the_mismatch_is_named_and_left_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLURAL_GATEWAY_URL", "http://127.0.0.1:8005/v1")
    environ = run_commands._run_environ(_session("http://127.0.0.1:8005"), _space(HOSTED))
    assert environ["PLURAL_GATEWAY_URL"] == "http://127.0.0.1:8005/v1"
    assert "you are signed in to http://127.0.0.1:8005" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("gateway", "bound"),
    [
        (f"{HOSTED}/v1", HOSTED),
        ("http://localhost:8005/v1", "http://localhost:8005"),
        ("http://localhost:8005/v1", None),
    ],
)
def test_a_consistent_gateway_is_kept_quietly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    gateway: str,
    bound: str | None,
) -> None:
    monkeypatch.setenv("PLURAL_GATEWAY_URL", gateway)
    environ = run_commands._run_environ(_session(bound or HOSTED), _space(bound))
    assert environ["PLURAL_GATEWAY_URL"] == gateway
    assert capsys.readouterr().err == ""
