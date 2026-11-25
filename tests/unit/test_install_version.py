import os
import stat
from pathlib import Path

import pytest

from plural.harness import install


def _cli(folder: Path, name: str, prints: str) -> None:
    path = folder / name
    path.write_text(f"#!/bin/sh\necho '{prints}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_a_preinstalled_cli_counts_only_at_the_pinned_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    _cli(tmp_path, "claude", "2.1.236 (Claude Code)")
    _cli(tmp_path, "codex", "codex-cli 0.153.2")

    claude = install._version_on_path("claude")
    codex = install._version_on_path("codex")
    assert claude is not None and codex is not None
    assert install._is_version(claude, "2.1.236")
    assert install._is_version(codex, "0.153.2")
    assert not install._is_version(claude, "2.1.23")
    assert not install._is_version(codex, "0.153.20")
    assert install._version_on_path("hermes") is None


def test_an_image_with_the_pinned_cli_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PLURAL_RUNTIME_PROVIDER", "daytona")
    monkeypatch.setenv("PLURAL_TOOLS_PREFIX", str(tmp_path / "tools"))
    _cli(tmp_path, "claude", "2.1.236 (Claude Code)")
    installed: list[str] = []
    monkeypatch.setattr(install, "_install_npm", lambda *args: installed.append(args[0]))

    install.main(["claude-code", "2.1.236"])
    assert installed == []
    assert capsys.readouterr().err == ""

    _cli(tmp_path, "claude", "2.1.100 (Claude Code)")
    install.main(["claude-code", "2.1.236"])
    assert installed == ["@anthropic-ai/claude-code"]
    assert capsys.readouterr().err == (
        "Replacing claude 2.1.100 on PATH with the pinned 2.1.236.\n"
    )
