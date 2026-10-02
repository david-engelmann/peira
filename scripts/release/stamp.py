"""Stamp the release version into a pristine build tree (proposal P-8).

The repo always carries ``0.0.0`` (tag-is-version). At publish time the
release build materializes ``git archive <tag>`` into a temp dir and this
module stamps the tag version into exactly the files that carry it:

- ``pyproject.toml``: ``version = "0.0.0"`` under ``[project]``
- ``python/peira/__init__.py``: ``__version__ = "0.0.0"``
- ``crates/peira-python/Cargo.toml``: ``version = "0.0.0"`` (maturin
  migration; stamped only when the file exists, so this keeps working
  before and after that lane lands)

Stamping is fail-loud: each file must contain its marker exactly once, or
this raises instead of guessing. Nothing outside these markers is touched.
"""

from __future__ import annotations

from pathlib import Path

from .validate import ReleaseError, release_version

REPO_VERSION = "0.0.0"

# (relative path, exact marker line fragment, replacement template)
_STAMP_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("pyproject.toml", 'version = "0.0.0"', 'version = "{version}"'),
    (
        "python/peira/__init__.py",
        '__version__ = "0.0.0"',
        '__version__ = "{version}"',
    ),
    ("crates/peira-python/Cargo.toml", 'version = "0.0.0"', 'version = "{version}"'),
)


def _stamp_file(path: Path, marker: str, replacement: str) -> bool:
    """Replace the marker line in one file. Returns True when stamped."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    hits = text.count(marker)
    if hits == 0:
        return False
    if hits > 1:
        raise ReleaseError(
            f"{path}: version marker occurs {hits} times, refusing to guess"
        )
    path.write_text(text.replace(marker, replacement), encoding="utf-8")
    return True


def stamp_version(tree: str | Path, version: str) -> list[str]:
    """Stamp ``version`` into a pristine source tree. Returns stamped files.

    Raises ReleaseError when a present target file lacks its marker, or a
    marker occurs more than once. Files that do not exist are skipped.
    """
    version = release_version(version)
    root = Path(tree)
    stamped: list[str] = []
    for rel, marker, template in _STAMP_TARGETS:
        path = root / rel
        if not path.is_file():
            continue
        if _stamp_file(path, marker, template.format(version=version)):
            stamped.append(rel)
        else:
            raise ReleaseError(
                f"{rel} exists but has no '{marker}' marker; "
                "repo version drifted from tag-is-version"
            )
    if "pyproject.toml" not in stamped:
        raise ReleaseError("pyproject.toml was not stamped; refusing to build")
    return stamped
