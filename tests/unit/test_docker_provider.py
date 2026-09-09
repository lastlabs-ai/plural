from __future__ import annotations

from plural.sandbox import DockerProvider, NetworkMode, ResourceRequirements, SandboxRequirements


class MockDockerProvider(DockerProvider):
    def __init__(self) -> None:
        super().__init__(executable="true")
        self.calls: list[tuple[str, ...]] = []

    async def _run(
        self,
        *args: str,
        stdin: bytes | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> tuple[int, bytes, bytes]:
        self.calls.append(args)
        if args[:2] == ("version", "--format"):
            return 0, b'{"Version":"29.0"}', b""
        if args[:2] == ("image", "inspect"):
            return 0, b"sha256:image\n", b""
        if args and args[0] == "create":
            return 0, b"container-id\n", b""
        if args[-3:-1] == ("test", "-L"):
            return 1, b"", b""
        if len(args) >= 3 and args[-2] == "cat":
            return 0, b"artifact", b""
        return 0, b"", b""


async def test_docker_create_uses_lockdown_and_resource_arguments() -> None:
    provider = MockDockerProvider()
    requirements = SandboxRequirements(
        image="python:3.12",
        network=NetworkMode.NONE,
        resources=ResourceRequirements(cpu=1.5, memory_mb=512, pids=32),
        read_only_root=True,
    )
    handle = await provider.create(requirements)
    create = next(call for call in provider.calls if call and call[0] == "create")

    assert "--privileged" not in create
    assert "--network" in create and create[create.index("--network") + 1] == "none"
    assert "--cap-drop" in create and create[create.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges=true" in create
    assert "--read-only" in create
    assert create[create.index("--pids-limit") + 1] == "32"
    assert create[create.index("--memory") + 1] == "512m"
    assert handle.image_identity == "sha256:image"

    await provider.destroy(handle)
    assert ("rm", "--force", "container-id") in provider.calls


async def test_docker_download_streams_exact_regular_file() -> None:
    provider = MockDockerProvider()
    handle = await provider.create(SandboxRequirements(image="python:3.12"))

    files = await provider.download_files(handle, ("result.json",))

    assert files[0].path == "result.json"
    assert files[0].data == b"artifact"
    assert not any(call and call[0] == "cp" for call in provider.calls)
