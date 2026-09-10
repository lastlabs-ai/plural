from __future__ import annotations

import json
from pathlib import Path

import pytest

from plural.domain import ExecutionTarget, HarnessStamp
from plural.execution.policy import (
    ProjectPolicy,
    policy_case_agent,
    policy_case_environment,
    resolve_effective_policy,
)
from plural.sandbox.models import CapabilityError, ProviderCapabilities

CASES_PATH = Path(__file__).resolve().parents[2] / "src/plural/schemas/execution_policy.cases.json"


def _load_cases() -> list[dict]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


@pytest.mark.parametrize("case", _load_cases(), ids=lambda item: item["id"])
def test_resolve_effective_policy_cases(case: dict) -> None:
    environment = policy_case_environment(case["environment"])
    stamp_payload = case.get("stamp")
    stamp = None
    if stamp_payload is not None:
        stamp_payload = dict(stamp_payload)
        stamp_payload["environment"] = environment.identity.model_dump(mode="json")
        stamp = HarnessStamp.model_validate(stamp_payload)
    agent = policy_case_agent(environment, case.get("template") or {}, stamp)
    provider = ProviderCapabilities.model_validate(case["provider"])
    project = ProjectPolicy.model_validate(case["project"])
    target = ExecutionTarget(case["requested_target"])
    if case["expect"] == "error":
        with pytest.raises(CapabilityError, match=case["error_contains"]) as exc_info:
            resolve_effective_policy(
                environment=environment,
                agent=agent,
                stamp=stamp,
                project=project,
                provider=provider,
                requested_target=target,
            )
        assert case["layer"] in {"provider", "project", "environment", "harness", "agent"}
        assert str(exc_info.value)
        return
    policy = resolve_effective_policy(
        environment=environment,
        agent=agent,
        stamp=stamp,
        project=project,
        provider=provider,
        requested_target=target,
    )
    assert policy.target is target
    assert policy.provider == provider.provider
