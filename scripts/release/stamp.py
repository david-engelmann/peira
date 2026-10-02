"""Stamp the release version into a pristine build tree (proposal P-8).

The repo always carries ``0.0.0`` (tag-is-version). At publish time the
release build materializes ``git archive <tag>`` into a temp dir and this
module stamps the tag version into exactly the files that carry it:

- ``pyproject.toml``: ``version = "0.0.0"`` under ``[project]``
- ``pyproject.toml``: the ``[project.urls]`` Documentation URL, which is
  pinned to the release (``tree/v0.0.0/docs`` in the repo, ``tree/vX.Y.Z/docs``
  after stamping), never ``main``
- ``python/peira/__init__.py``: ``__version__ = "0.0.0"``

The Rust crates under ``crates/`` are versioned independently and are never
stamped (they build the ``peira._core`` extension, not the PyPI package).

Stamping is fail-loud: each file must contain its marker exactly once, or
this raises instead of guessing. Nothing outside these markers is touched.
"""

from __future__ import annotations

from pathlib import Path

from .validate import ReleaseError, release_version

REPO_VERSION = "0.0.0"

# (relative path, exact marker line fragment, replacement template)
#
# NB: the Rust crates under crates/ are deliberately NOT stamped. They build
# the peira._core native extension, not the peira PyPI package, and are
# versioned independently (like the dataset). If the build backend ever needs
# the crate version to track releases, that is a deliberate decision for
# that lane, not something to guess at here.
#
# STAMP_TARGETS is public: scripts/release/preflight.py derives the
# tag-is-version gate from the same list, so the gate and the stamper can
# never disagree about which markers must be present exactly once.
STAMP_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("pyproject.toml", 'version = "0.0.0"', 'version = "{version}"'),
    ("pyproject.toml", "tree/v0.0.0/docs", "tree/v{version}/docs"),
    (
        "python/peira/__init__.py",
        '__version__ = "0.0.0"',
        '__version__ = "{version}"',
    ),
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
    for rel, marker, template in STAMP_TARGETS:
        path = root / rel
        if not path.is_file():
            continue
        if _stamp_file(path, marker, template.format(version=version)):
            if rel not in stamped:
                stamped.append(rel)
        else:
            raise ReleaseError(
                f"{rel} exists but has no '{marker}' marker; "
                "repo version drifted from tag-is-version"
            )
    if "pyproject.toml" not in stamped:
        raise ReleaseError("pyproject.toml was not stamped; refusing to build")
    return stamped
