"""Install a pinned built-in Harness CLI inside a fresh Runtime."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

NPM_PACKAGES = {
    "claude-code": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
}
PIP_PACKAGES = {
    "hermes": "hermes-agent",
}
BINARIES = {
    "claude-code": "claude",
    "codex": "codex",
    "hermes": "hermes",
}


def main(argv: list[str] | None = None) -> None:
    """Install one built-in CLI into the Runtime workspace or system prefix."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: python install.py {hermes|claude-code|codex} VERSION")
    name, version = args
    if name not in BINARIES:
        raise SystemExit(f"unknown built-in Harness {name!r}")
    provider = os.environ.get("PLURAL_RUNTIME_PROVIDER", "local")
    given = os.environ.get("PLURAL_TOOLS_PREFIX", str(Path.cwd() / ".plural" / "tools"))
    root = os.environ.get("PLURAL_SANDBOX_ROOT")
    if root and (given == "/workspace" or given.startswith("/workspace/")):
        # The local Runtime keeps /workspace under its own folder.
        given = str(Path(root) / given.removeprefix("/"))
    prefix = Path(given)
    if provider == "local":
        # Elsewhere setup installs system-wide; the workspace is not root's to write.
        prefix.mkdir(parents=True, exist_ok=True)
    binary = BINARIES[name]
    if _on_path(binary):
        found = _version_on_path(binary)
        if found is not None and _is_version(found, version):
            return
        print(
            f"Replacing {binary} {_release(found) or 'of unknown version'} on PATH "
            f"with the pinned {version}.",
            file=sys.stderr,
        )
    try:
        if name in NPM_PACKAGES:
            _install_npm(NPM_PACKAGES[name], version, provider, prefix)
        else:
            _install_pip(PIP_PACKAGES[name], version, provider, prefix, binary)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or b"").decode("utf-8", errors="replace")
        raise SystemExit(
            f"Could not install {name} {version} in the {provider} Runtime.\n"
            "The Runtime needs network access and the installer tools for this CLI.\n"
            f"{detail[:2000]}"
        ) from exc
    if not _on_path(binary, prefix / "bin"):
        raise SystemExit(
            f"{name} installed but {binary!r} is not on PATH. "
            "The Runtime image is missing expected CLI tools."
        )


def _on_path(binary: str, extra: Path | None = None) -> bool:
    path = os.environ.get("PATH", "")
    if extra is not None:
        os.environ["PATH"] = f"{extra}{os.pathsep}{path}"
    return shutil.which(binary) is not None


def _version_on_path(binary: str) -> str | None:
    """What the CLI on PATH prints for ``--version``, or None when it can't say."""
    path = shutil.which(binary)
    if path is None:
        return None
    try:
        completed = subprocess.run(
            (path, "--version"), check=False, capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (completed.stdout + completed.stderr).decode("utf-8", errors="replace")


def _is_version(output: str, version: str) -> bool:
    """Whether ``--version`` output names exactly ``version``."""
    return re.search(rf"(?<![0-9.]){re.escape(version)}(?![0-9])", output) is not None


def _release(output: str | None) -> str | None:
    """The release number in ``--version`` output."""
    match = re.search(r"[0-9]+(\.[0-9]+)+\S*", output or "")
    return match.group(0) if match else None


def _install_npm(package: str, version: str, provider: str, prefix: Path) -> None:
    npm = shutil.which("npm")
    if npm is None:
        if provider == "local":
            raise SystemExit(
                "The local Runtime needs Node.js and npm to install this Harness, "
                "or the CLI must already be on PATH."
            )
        _ensure_node()
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit(
                "The Runtime image is missing npm after the Node.js installer ran. "
                "Use an image with Node.js, or allow network so setup can install it."
            )
    spec = f"{package}@{version}"
    if provider == "local":
        _run((npm, "install", "--global", "--prefix", str(prefix), spec))
        return
    _run((npm, "install", "--global", spec))


def _install_pip(package: str, version: str, provider: str, prefix: Path, binary: str) -> None:
    python = sys.executable
    spec = f"{package}=={version}"
    if provider != "local":
        _run((python, "-m", "pip", "install", spec))
        return
    # Its own environment: Plural's may have no pip (uv makes none), and the CLI's
    # dependencies stay out of it.
    venv = prefix / "venvs" / package
    if not (venv / "bin" / "python").exists():
        _run((python, "-m", "venv", str(venv)))
    _run((str(venv / "bin" / "python"), "-m", "pip", "install", "--quiet", spec))
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    link = prefix / "bin" / binary
    if not link.exists():
        link.symlink_to(venv / "bin" / binary)


def _ensure_node() -> None:
    apt = shutil.which("apt-get")
    if apt is None:
        raise SystemExit(
            "This Runtime image is missing Node.js/npm and has no apt-get installer. "
            "Use an image that includes Node.js, or choose Runtime.local() with the CLI on PATH."
        )
    _run((apt, "update"))
    _run((apt, "install", "-y", "curl", "ca-certificates", "gnupg"))
    curl = shutil.which("curl")
    if curl is None:
        raise SystemExit("curl is required to install Node.js in the Runtime")
    _run(
        (
            "sh",
            "-c",
            "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
        )
    )
    _run((apt, "install", "-y", "nodejs"))


def _run(command: tuple[str, ...]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        error = subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
        raise error


if __name__ == "__main__":
    main()
