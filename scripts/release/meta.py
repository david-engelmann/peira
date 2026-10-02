"""Release metadata: version/tag parsing and channel decisions (proposal P-8).

A prerelease never moves the stable channel. A stable release is the
``latest`` channel only when it is the highest stable tag on record, so a
backport cut after a newer stable (e.g. v0.2.5 after v0.3.0) can never roll
the public install target backwards.
"""

from __future__ import annotations

from dataclasses import dataclass

from .validate import PEP440_RE, release_version, version_from_tag


@dataclass(frozen=True)
class ReleaseMeta:
    version: str
    tag: str


def parse_release_version(raw: str) -> ReleaseMeta:
    """Accept ``1.2.3`` or ``v1.2.3``; return the canonical version and tag."""
    raw = raw.strip()
    version = version_from_tag(raw) if raw.startswith("v") else release_version(raw)
    return ReleaseMeta(version=version, tag=f"v{version}")


def _is_stable(version: str) -> bool:
    """True when the PEP 440 version has no prerelease segment."""
    match = PEP440_RE.match(version)
    return match is not None and match.group("pre") is None


def stable_versions_from_ls_remote(output: str) -> list[str]:
    """Stable versions named by ``git ls-remote --tags`` output.

    Peeled ``^{}`` refs are folded in; anything that is not ``v`` + plain
    ``X.Y.Z`` is ignored.
    """
    versions: set[str] = set()
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        ref = parts[1].strip()
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/") :]
        if name.endswith("^{}"):
            name = name[: -len("^{}")]
        if not name.startswith("v"):
            continue
        version = name[1:]
        if _is_stable(version):
            # Validate shape via release_version; skip anything malformed.
            try:
                release_version(version)
            except Exception:
                continue
            versions.add(version)
    return sorted(versions, key=_version_key)


def _version_key(version: str) -> tuple[int, int, int, int, int]:
    """Sort key with PEP 440 prerelease ordering.

    ``1.2.3a0 < 1.2.3b0 < 1.2.3rc1 < 1.2.3``: prereleases sort before the
    stable release they lead up to.
    """
    match = PEP440_RE.match(version)
    if match is None:  # pragma: no cover - callers validate first
        raise ValueError(f"not a PEP 440 version: {version!r}")
    major, minor, patch = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
    if match.group("pre") is None:
        return (major, minor, patch, 3, 0)
    rank = {"a": 0, "b": 1, "rc": 2}[match.group("pre_kind")]
    return (major, minor, patch, rank, int(match.group("pre_num")))


def compare_versions(a: str, b: str) -> int:
    """Compare two PEP 440 versions. Returns negative/zero/positive."""
    ka, kb = _version_key(release_version(a)), _version_key(release_version(b))
    return (ka > kb) - (ka < kb)


def channel_for(version: str, known_stable: list[str]) -> str:
    """Decide the distribution channel for a release.

    Returns ``"prerelease"`` for PEP 440 prereleases (``1.2.3rc1``),
    ``"latest"`` when the version is the highest stable tag known, and
    ``"backport"`` for a stable release that is not the highest (it ships,
    but never moves the ``latest`` pointer).
    """
    version = release_version(version)
    if not _is_stable(version):
        return "prerelease"
    for known in known_stable:
        if compare_versions(version, known) < 0:
            return "backport"
    return "latest"
