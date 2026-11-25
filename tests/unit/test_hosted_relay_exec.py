import asyncio
from typing import Any

import pytest

from plural.errors import PluralError
from plural.sandbox.hosted_daytona import _HostedSandbox


class _Studio:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.result


def _exec(result: dict[str, Any]) -> tuple[int, str, str]:
    sandbox = _HostedSandbox(_Studio(result), {"id": "sbx"})  # type: ignore[arg-type]
    return asyncio.run(sandbox.exec(("ls",), cwd="/workspace", env={}, timeout=10))


def test_relayed_output_says_when_its_start_was_cut() -> None:
    code, stdout, stderr = _exec(
        {"exit_code": 0, "stdout": "tail\n", "stderr": "err\n", "stdout_cut_bytes": 4096}
    )
    assert code == 0
    assert stdout == "[4096 earlier bytes not relayed]\ntail\n"
    assert stderr == "err\n"


def test_a_relay_failure_after_the_command_started_raises() -> None:
    with pytest.raises(PluralError, match="toolbox unreachable"):
        _exec({"exit_code": -1, "stdout": "", "stderr": "", "error": "toolbox unreachable"})
