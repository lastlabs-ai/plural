from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from plural.agents.models import AgentCredential, AgentDefinition
from plural.cli import credential_commands
from plural.errors import AuthenticationError
from plural.jobs import AgentBinding


class _Credentials:
    def __init__(self, saved: dict[str, str], *, refuse: bool = False) -> None:
        self.saved = saved
        self.refuse = refuse
        self.asked: list[list[str]] = []

    def resolve(self, names: list[str]) -> dict[str, Any]:
        self.asked.append(list(names))
        if self.refuse:
            raise AuthenticationError("This API key cannot use your credentials.", status_code=403)
        return {
            "credentials": {
                name: {"value": self.saved[name], "updated_at": "2026-10-12T00:00:00+00:00"}
                for name in names
                if name in self.saved
            },
            "missing": [name for name in names if name not in self.saved],
        }


@dataclass
class _Studio:
    credentials: _Credentials


class _Spec:
    def __init__(self, *agents: AgentDefinition) -> None:
        self.agents = tuple(AgentBinding(agent=agent) for agent in agents)


def _agent(name: str, *credentials: str) -> AgentDefinition:
    return AgentDefinition(
        name=name,
        model="test/model",
        credentials={item: AgentCredential(scopes=("read",)) for item in credentials},
    )


def test_every_agent_you_run_uses_your_saved_values(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _Credentials({"CRM_TOKEN": "mine-1234", "ERP_KEY": "erp-5678"})
    monkeypatch.setattr(credential_commands, "_studio", lambda: _Studio(saved))
    spec = _Spec(_agent("sales", "CRM_TOKEN"), _agent("ops", "ERP_KEY", "DESK"), _agent("bare"))

    found = credential_commands.stored_credentials(spec, None, err=True)  # type: ignore[arg-type]

    assert saved.asked == [["CRM_TOKEN", "DESK", "ERP_KEY"]]
    assert {agent: {k: v.value for k, v in values.items()} for agent, values in found.items()} == {
        "sales": {"CRM_TOKEN": "mine-1234"},
        "ops": {"ERP_KEY": "erp-5678"},
    }
    assert found["sales"]["CRM_TOKEN"].source == "hosted"


def test_a_key_that_cannot_read_your_credentials_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = _Credentials({"CRM_TOKEN": "mine-1234"}, refuse=True)
    monkeypatch.setattr(credential_commands, "_studio", lambda: _Studio(refused))

    found = credential_commands.stored_credentials(
        _Spec(_agent("sales", "CRM_TOKEN")),  # type: ignore[arg-type]
        None,
        err=True,
    )

    assert found == {}
    assert "Using credentials from your environment" in capsys.readouterr().err


def test_no_lookup_when_no_agent_carries_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    def never() -> _Studio:
        raise AssertionError("looked up credentials no Agent carries")

    monkeypatch.setattr(credential_commands, "_studio", never)
    assert credential_commands.stored_credentials(_Spec(_agent("bare")), None, err=True) == {}  # type: ignore[arg-type]
