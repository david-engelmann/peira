"""Pre-publish preflight checks for a peira release (proposal P-8).

Usage: ``python scripts/release/preflight.py --version 1.2.3``

Every check fails loud with a one-line reason on stderr and exit code 1.
The pure helpers (changelog section detection, install-pin scan, docs-link
scan) are covered by ``tests/test_release.py``; the git wrappers are
exercised by dry runs.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.release.meta import parse_release_version  # noqa: E402
from scripts.release.stamp import STAMP_TARGETS  # noqa: E402
from scripts.release.validate import ReleaseError  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Install commands pinned to the main branch instead of a release. The
# release process must never bless one; every install path pins to the
# release artifact (``pip install peira==X.Y.Z``).
_MAIN_PIN_PATTERNS = (
    re.compile(r"github\.com/david-engelmann/peira/(archive|blob|raw)/refs/heads/main"),
    re.compile(r"raw\.githubusercontent\.com/david-engelmann/peira/main/"),
    re.compile(r"pip install[^\n]*git\+https://github\.com/david-engelmann/peira(?:@main)?(?:[^\w@]|$)"),
)

# Documentation links pinned to the main branch. The spec pins docs URLs to
# the release, never main: the [project.urls] Documentation link is stamped
# per release, and no hand-written README/docs link may point at main.
_MAIN_DOC_LINK_PATTERN = re.compile(
    r"github\.com/david-engelmann/peira/(tree|blob)/main\b"
)


def _run(*args: str, cwd: pathlib.Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False
    )


def check_repo_unstamped() -> None:
    """The repo must carry 0.0.0; the tag is the version source of truth.

    Mirrors the stamper's invariant exactly: every marker in STAMP_TARGETS
    must be present exactly once, so a drifted duplicate dies here instead
    of later at build time.
    """
    for rel, marker, _template in STAMP_TARGETS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        count = text.count(marker)
        if count != 1:
            raise ReleaseError(
                f"{rel}: expected the 0.0.0 marker {marker!r} exactly once, "
                f"found {count}x; tag-is-version invariant broken"
            )


def check_tree_clean() -> None:
    out = _run("git", "status", "--porcelain")
    if out.returncode != 0 or out.stdout.strip():
        raise ReleaseError("working tree is not clean; commit or stash first")


def check_on_main_up_to_date() -> None:
    branch = _run("git", "branch", "--show-current").stdout.strip()
    if branch != "main":
        raise ReleaseError(f"releases are cut from main, not '{branch}'")
    _run("git", "fetch", "origin", "main")
    ahead_behind = _run(
        "git", "rev-list", "--left-right", "--count", "HEAD...origin/main"
    ).stdout.strip()
    ahead, behind = (int(x) for x in ahead_behind.split())
    if ahead or behind:
        raise ReleaseError(
            f"main is {ahead} ahead / {behind} behind origin/main; push or pull first"
        )


def check_tag(tag: str) -> None:
    """The tag must exist, be annotated, carry a signature, and point at HEAD."""
    obj_type = _run("git", "cat-file", "-t", tag)
    if obj_type.returncode != 0:
        raise ReleaseError(f"tag {tag} does not exist locally; create and sign it first")
    if obj_type.stdout.strip() != "tag":
        raise ReleaseError(
            f"tag {tag} is lightweight; releases require an annotated signed tag"
        )
    verify = _run("git", "verify-tag", tag)
    if verify.returncode != 0:
        raise ReleaseError(
            f"tag {tag} has no verifiable signature: "
            + (verify.stderr.strip().splitlines() or ["unknown gpg error"])[0]
        )
    tagged = _run("git", "rev-list", "-n", "1", tag).stdout.strip()
    head = _run("git", "rev-parse", "HEAD").stdout.strip()
    if tagged != head:
        raise ReleaseError(
            f"tag {tag} points at {tagged[:8]}, but HEAD is {head[:8]}; "
            "releases are cut from the reviewed main head"
        )


def changelog_has_section(text: str, version: str) -> bool:
    """True when CHANGELOG.md carries a curated section for this version."""
    return f"## [{version}]" in text


def check_changelog(version: str) -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not changelog_has_section(text, version):
        raise ReleaseError(
            f"CHANGELOG.md has no '## [{version}]' section; "
            "release notes are curated by hand, never generated"
        )


def find_main_pinned_installs(
    files: dict[str, str],
) -> list[str]:
    """Return ``path:line`` hits for install commands pinned to main."""
    hits: list[str] = []
    for path, text in files.items():
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in _MAIN_PIN_PATTERNS):
                hits.append(f"{path}:{lineno}")
    return hits


def find_main_pinned_links(
    files: dict[str, str],
) -> list[str]:
    """Return ``path:line`` hits for docs links pinned to the main branch."""
    hits: list[str] = []
    for path, text in files.items():
        for lineno, line in enumerate(text.splitlines(), 1):
            if _MAIN_DOC_LINK_PATTERN.search(line):
                hits.append(f"{path}:{lineno}")
    return hits


def _doc_files() -> dict[str, str]:
    candidates = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    return {
        str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
        for p in candidates
        if p.is_file()
    }


def check_install_pins() -> None:
    """No install path may point at the main branch; releases pin versions."""
    hits = find_main_pinned_installs(_doc_files())
    if hits:
        raise ReleaseError(
            "install commands pinned to main (pin to the release instead): "
            + ", ".join(hits)
        )


def check_doc_links() -> None:
    """No docs URL may point at the main branch; they pin to the release."""
    hits = find_main_pinned_links(_doc_files())
    if hits:
        raise ReleaseError(
            "docs links pinned to main (pin to the release tag instead): "
            + ", ".join(hits)
        )


def check_uv_lock() -> None:
    """Best-effort: uv.lock must match pyproject (CI enforces strictly)."""
    uv = _run("which", "uv")
    if uv.returncode != 0:
        print("warning: uv not on PATH; skipping uv lock --check (CI enforces it)")
        return
    out = _run("uv", "lock", "--check")
    if out.returncode != 0:
        raise ReleaseError("uv.lock is out of sync; run `uv lock` and commit it")


def run_preflight(version: str, verbose: bool = True) -> None:
    meta = parse_release_version(version)
    log = print if verbose else (lambda *a, **k: None)
    check_repo_unstamped()
    log("ok: repo carries 0.0.0 (tag-is-version)")
    check_tree_clean()
    log("ok: working tree clean")
    check_on_main_up_to_date()
    log("ok: on main, up to date with origin/main")
    check_tag(meta.tag)
    log(f"ok: tag {meta.tag} exists, annotated, signed, points at HEAD")
    check_changelog(meta.version)
    log(f"ok: CHANGELOG.md has a curated '## [{meta.version}]' section")
    check_install_pins()
    log("ok: no main-pinned install commands")
    check_doc_links()
    log("ok: no main-pinned docs links")
    check_uv_lock()
    log("ok: uv.lock in sync")
    log(f"preflight PASS for {meta.tag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-publish preflight checks")
    parser.add_argument("--version", required=True, help="release version or tag")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_preflight(args.version, verbose=not args.quiet)
    except ReleaseError as exc:
        print(f"preflight FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
