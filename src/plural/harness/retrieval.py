"""Deterministic harness archives, verified retrieval, and safe extraction."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

import yaml

from plural.common import HarnessPackage

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def tree_digest(root: Path) -> str:
    """Hash a package tree by relative path and bytes."""
    ignore_file = root.resolve() / ".pluralignore"
    ignored = (
        {
            line.strip().removeprefix("./")
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        if ignore_file.is_file()
        else set()
    )
    digest = hashlib.sha256()
    for path in sorted(root.resolve().rglob("*")):
        relative = path.relative_to(root.resolve())
        if any(part in {".git", ".plural", "__pycache__"} for part in relative.parts):
            continue
        if relative.as_posix() in ignored:
            continue
        if path.is_symlink():
            raise ValueError(f"package contains a symlink: {relative}")
        if path.is_file():
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def build_archive(source: Path, destination: Path) -> str:
    """Build a normalized gzip tar archive and return its byte digest."""
    root = source.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in {".git", ".plural", "__pycache__"} for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError(f"package contains a symlink: {relative}")
            if not path.is_file():
                continue
            data = path.read_bytes()
            info = tarfile.TarInfo(relative.as_posix())
            info.size = len(data)
            info.mode = path.stat().st_mode & 0o777
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as output:
        output.write(buffer.getvalue())
    payload = compressed.getvalue()
    _atomic_write(destination, payload)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def retrieve_archive(
    uri: str,
    digest: str,
    *,
    cache_root: Path | None = None,
) -> Path:
    """Retrieve and safely extract an immutable file or HTTPS archive."""
    expected = digest.removeprefix("sha256:")
    if len(expected) != 64:
        raise ValueError("archive digest must be sha256:<64 hex>")
    cache = (cache_root or Path.home() / ".cache" / "plural" / "harnesses") / expected
    complete = cache / ".complete"
    if complete.exists() and _revalidate_cache(cache, expected):
        return cache / "package"
    if cache.exists():
        shutil.rmtree(cache)
    payload = _read_uri(uri)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(
            f"archive digest mismatch: expected sha256:{expected}, got sha256:{actual}"
        )
    cache.mkdir(parents=True, exist_ok=True)
    _atomic_write(cache / "archive.tar.gz", payload)
    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=cache))
    package = staging / "package"
    package.mkdir()
    try:
        _extract(payload, package)
        if not (package / "harness.yaml").is_file():
            raise ValueError("archive does not contain harness.yaml")
        final = cache / "package"
        if final.exists():
            shutil.rmtree(final)
        package.replace(final)
        _atomic_write(
            complete,
            (
                f'{{"archive_digest":"sha256:{expected}","tree_digest":"{tree_digest(final)}"}}\n'
            ).encode(),
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return cache / "package"


def _revalidate_cache(cache: Path, expected: str) -> bool:
    archive_path = cache / "archive.tar.gz"
    package = cache / "package"
    if not archive_path.is_file() or not package.is_dir():
        return False
    payload = archive_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        return False
    staging = Path(tempfile.mkdtemp(prefix=".validate-", dir=cache))
    authenticated = staging / "package"
    authenticated.mkdir()
    try:
        _extract(payload, authenticated)
        if not (authenticated / "harness.yaml").is_file():
            return False
        if tree_digest(authenticated) == tree_digest(package):
            return True
        shutil.rmtree(package)
        authenticated.replace(package)
        _atomic_write(
            cache / ".complete",
            (
                f'{{"archive_digest":"sha256:{expected}","tree_digest":"{tree_digest(package)}"}}\n'
            ).encode(),
        )
        return True
    except (OSError, ValueError, tarfile.TarError):
        return False
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def package_from_archive(
    uri: str,
    digest: str,
    *,
    cache_root: Path | None = None,
) -> HarnessPackage:
    """Load a verified archive and retain its immutable source identity."""
    root = retrieve_archive(uri, digest, cache_root=cache_root)
    payload = yaml.safe_load((root / "harness.yaml").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("harness.yaml must contain a mapping")
    if payload.get("kind") == "harness" or not ({"definition", "manifest"} & payload.keys()):
        from plural.harness.models import Harness
        from plural.project import Resolver

        public = Resolver(root=root).load("harness.yaml")
        if not isinstance(public, Harness):
            raise TypeError("archived harness.yaml did not resolve to a Harness subclass")
        return HarnessPackage.model_validate(
            {
                "definition": public._package().definition,
                "source": {"kind": "archive", "uri": uri, "digest": digest},
            }
        )
    payload["source"] = {"kind": "archive", "uri": uri, "digest": digest}
    package = HarnessPackage.model_validate(payload)
    return package


def materialize_package(
    package: HarnessPackage,
    *,
    cache_root: Path | None = None,
) -> Path | None:
    """Return a local package tree, or None for OCI image packages."""
    if package.source.kind == "oci":
        return None
    if package.source.kind == "archive":
        if package.source.digest is None:  # pragma: no cover - model invariant
            raise ValueError("archive source requires digest")
        return retrieve_archive(package.source.uri, package.source.digest, cache_root=cache_root)
    return Path(package.source.uri).expanduser().resolve()


def _read_uri(uri: str) -> bytes:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme == "https":
        request = urllib.request.Request(uri, headers={"User-Agent": "plural-package/1"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            if urllib.parse.urlparse(response.geturl()).scheme != "https":
                raise ValueError("HTTPS archive retrieval refused a protocol downgrade")
            payload = bytes(response.read(MAX_ARCHIVE_BYTES + 1))
    elif parsed.scheme == "file":
        payload = Path(urllib.request.url2pathname(parsed.path)).read_bytes()
    elif not parsed.scheme:
        payload = Path(uri).expanduser().read_bytes()
    else:
        raise ValueError("archive URI must use HTTPS, file://, or a local path")
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError(f"archive exceeds {MAX_ARCHIVE_BYTES} bytes")
    return payload


def _extract(payload: bytes, destination: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            _extract_members(archive, destination)
    except tarfile.TarError as exc:
        raise ValueError("invalid harness archive") from exc


def _extract_members(archive: tarfile.TarFile, destination: Path) -> None:
    total = 0
    seen: set[str] = set()
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or path.parts in {(), (".",)}:
            raise ValueError(f"unsafe archive path: {member.name!r}")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"unsupported archive member: {member.name!r}")
        normalized = path.as_posix()
        if normalized in seen:
            raise ValueError(f"duplicate archive member: {member.name!r}")
        seen.add(normalized)
        if member.isdir():
            (destination / path.as_posix()).mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            raise ValueError(f"unsupported archive member: {member.name!r}")
        total += member.size
        if total > MAX_ARCHIVE_BYTES:
            raise ValueError(f"extracted archive exceeds {MAX_ARCHIVE_BYTES} bytes")
        source = archive.extractfile(member)
        if source is None:
            raise ValueError(f"cannot read archive member: {member.name!r}")
        target = destination / path.as_posix()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read())
        target.chmod(member.mode & 0o777)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


__all__ = [
    "MAX_ARCHIVE_BYTES",
    "build_archive",
    "materialize_package",
    "package_from_archive",
    "retrieve_archive",
    "tree_digest",
]
