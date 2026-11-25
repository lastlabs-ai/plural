import re
from pathlib import Path

from plural.harness.builtins import BUILTIN_HARNESSES

DOCKERFILE = Path(__file__).resolve().parents[2] / "docker" / "sandbox" / "Dockerfile"


def _arg(name: str) -> str:
    match = re.search(rf"^ARG {name}=(\S+)$", DOCKERFILE.read_text(), re.MULTILINE)
    assert match, f"docker/sandbox/Dockerfile declares no ARG {name}"
    return match.group(1)


def test_the_vendor_image_preinstalls_the_cli_versions_plural_pins() -> None:
    assert _arg("CLAUDE_CODE_VERSION") == BUILTIN_HARNESSES["claude-code"].pinned_version
    assert _arg("CODEX_VERSION") == BUILTIN_HARNESSES["codex"].pinned_version


def test_the_base_image_stays_the_default_build_target() -> None:
    stages = re.findall(r"^FROM (.+)$", DOCKERFILE.read_text(), re.MULTILINE)
    assert stages[-1].strip() == "base"
