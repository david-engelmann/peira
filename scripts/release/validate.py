"""Input validation for the release tooling (proposal P-8).

Every check raises ReleaseError inline rather than returning a boolean, so
the accepted value is only reachable past the test. Mirrors the shape of
decant's scripts/release/validate.ts, adapted to Python packaging.
"""

from __future__ import annotations

import re


class ReleaseError(Exception):
    """A release input failed validation. Message is safe to print."""


_PEP440_CORE = r"(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
_PEP440_PRE = r"(?P<pre>(?P<pre_kind>a|b|rc)(?P<pre_num>0|[1-9]\d*))"
# PEP 440 versions: 1.2.3, 1.2.3rc1, 1.2.3a0, 1.2.3b2. PyPI requires PEP 440,
# so the release version is always PEP 440; the tag is v + PEP 440.
PEP440_RE = re.compile(rf"^{_PEP440_CORE}{_PEP440_PRE}?$")
RELEASE_TAG_RE = re.compile(rf"^v{_PEP440_CORE}{_PEP440_PRE}?$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# SemVer prerelease syntax, rejected with a pointer to the PEP 440 form.
_SEMVER_PRERELEASE_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-[0-9A-Za-z.-]+$"
)
# Absolute or repo-relative path that no command can read as an option.
SAFE_PATH_RE = re.compile(r"^(?!-)[A-Za-z0-9._@+/][A-Za-z0-9._@+/-]*$")
ABSOLUTE_PATH_RE = re.compile(r"^/(?!-)[A-Za-z0-9._@+/-]*$")


def release_version(value: str) -> str:
    """Validate a PEP 440 version (``1.2.3`` or ``1.2.3rc1``).

    PyPI requires PEP 440, so the release version is always PEP 440 and the
    tag is ``v`` + PEP 440. SemVer prerelease syntax (``1.2.3-rc.1``) is
    rejected with a pointer to the PEP 440 form: silently normalizing would
    break tag-is-version (the tag David creates must equal the version).
    """
    if _SEMVER_PRERELEASE_RE.match(value):
        raise ReleaseError(
            f"'{value}' uses SemVer prerelease syntax; "
            f"use PEP 440 instead (e.g. '1.2.3rc1')"
        )
    if not PEP440_RE.match(value):
        raise ReleaseError(f"'{value}' is not a PEP 440 version")
    return value


def release_tag(value: str) -> str:
    """Validate a release tag (``v`` + PEP 440, e.g. ``v1.2.3``)."""
    if not RELEASE_TAG_RE.match(value):
        raise ReleaseError(
            f"release tag must be 'v' followed by a PEP 440 version, got '{value}'"
        )
    return value


def version_from_tag(tag: str) -> str:
    """Strip the leading ``v`` from a validated release tag."""
    return release_tag(tag)[1:]


def commit_sha(name: str, value: str) -> str:
    """Validate a 40-char lowercase hex commit SHA."""
    if not COMMIT_SHA_RE.match(value):
        raise ReleaseError(f"{name} must be a 40-character lowercase hex SHA")
    return value


def safe_path(name: str, value: str) -> str:
    """Validate a path no shell or command can misread as flags."""
    if not SAFE_PATH_RE.match(value):
        raise ReleaseError(
            f"{name} must be a path of letters, digits, and ._@+/- "
            f"characters that does not start with '-', got '{value}'"
        )
    return value


def absolute_path(name: str, value: str) -> str:
    """Validate an absolute path no command can misread as flags."""
    if not ABSOLUTE_PATH_RE.match(value):
        raise ReleaseError(
            f"{name} must be an absolute path of letters, digits, and "
            f"._@+/- characters, got '{value}'"
        )
    return value
